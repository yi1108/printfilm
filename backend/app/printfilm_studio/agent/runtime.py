"""助手多轮工具循环：读取项目、修改画布并提交媒体任务。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from time import monotonic
from typing import Any

from app.printfilm_studio.agent.actions import split_assistant_action
from app.printfilm_studio.agent.executor import CANVAS_WRITE_TOOLS, execute_canvas_tool_batch, execute_studio_tool, summarize_canvas
from app.printfilm_studio.agent.tools import TOOL_NAMES, tool_definitions, validate_canvas_operations, validate_tool_input
from app.printfilm_studio.agent.streaming import VisibleReplyBuffer
from app.services.agent.compose import with_skill_system
from app.services.llm_client import chat_completions

SYSTEM_PROMPT = """你是 Printfilm Studio 创作助手。用简体中文回答。
需要查看项目、分集、资产、任务或画布时，只输出一个 JSON 对象：{"tool":"工具名","input":{}}。
需要修改画布时，只输出：{"tool":"add_canvas_node","input":{...}}，或在可见回复后附加 ```json {"canvas_operations":[...]} ```。
多条工具调用使用 JSON 数组 [{"tool":"add_canvas_node","input":{...}}, ...]，每轮最多 12 个工具。画布节点增删改和连接的数组会原子提交。
必须等待成功工具结果后才说明操作已完成；不要把工具 JSON 当作给用户的操作说明。
可用画布操作：add_canvas_node、update_canvas_node、remove_canvas_node、connect_canvas_nodes、attach_asset_to_node。
你工作在画布中。用户要求写剧本、创建剧本、规划角色或分镜时，必须把完整内容写入画布节点，不能仅在聊天中展示文本或更新项目资料。
创建剧本直接调用 {"tool":"add_canvas_node","input":{"type":"script","label":"剧本标题","text":"完整剧本正文"}}；修改已有剧本节点用 update_canvas_node。没有分集也能直接创建剧本节点，无需先创建项目剧本或分集。
剧本节点独立放置，不与其他节点连线；通过 sourceScriptId 记录归属。连接写作节点到对应图片或视频，角色场景参考图也要连入分镜写作节点和视频节点。运行到某个节点时先执行其上游依赖，已有有效结果复用；规划阶段禁止把最终提示词填到写作节点正文。
创作按阶段推进，完成当前阶段后停止并让用户选择下一步：写剧本 → 抽取角色与场景 → 拆分分镜 → 用户逐个生成参考图和分镜视频。不要在写完剧本后自行跳到后续阶段。
抽取角色/场景时先调用 read_canvas，node_ids 指定剧本以读取完整正文，不能只用画布摘要或聊天概述。然后调用 plan_story_assets，一次抽取全部角色和场景，每项写用于生成图片提示词的创作要求，最终提示词留待文本节点运行时生成；角色保持外貌、服饰和时代特征，场景保持时间、环境、光线和风格一致。不得只建文本节点或只在回复中列名单。
分镜分组按剧本场次命名为场1、场2；每集从场1开始，按剧情顺序递增，同场多镜共用 scene_number，换场或时空转换后即使返回同一地点也使用新场次序号。
画布的一个分镜节点代表一个可生成的视频片段，不是每次景别变化或每个微动作。默认少分镜、长片段，优先 12–15 秒，单段硬上限 15 秒；未提供时长按 15 秒规划。先估算完整对白、动作和反应所需总时间，再以尽量少的片段覆盖剧情。同场连续的进场、交接、对白与反应优先组成一个有因果的动作链；景别变化可写在同一片段的内部时间段，不为每句台词、每次反应或特写单建节点。仅在超过 15 秒、必要的时空转换或明确节奏要求时拆分。短片段允许用于用户指定时长、独立转场或收尾，但不能默认批量拆成 3–6 秒；不要为了凑满 15 秒添加空等、重复动作或删减原对白。写清可见起点、动作因果、结束状态、景别机位、主导运镜及对白声音，同场片段保持轴线、站位、视线和道具连续。
规划镜头时必须在 plan_story_shots 每项明确提供 duration（秒）和 ratio（画幅），与该镜头写作要求一致。reference_node_ids 必须指向实际角色/场景图片节点；提示词写作通过 outputNodeId/promptNodeId 绑定下游视频，后续以视频节点实际参数为准，不得只在聊天中口头承诺同步。
拆分分镜时使用 plan_story_shots，每个镜头创建一个text提示词节点和一个videoGeneration视频节点，提示词文本和对应角色场景图片分别连入视频节点。先读取剧本完整正文和相关角色场景节点，按故事顺序填写景别、机位、动作、对白、时长、用于生成最终视频提示词的写作要求及所需角色/场景节点ID（必须包含对应场景和出镜角色）。不得把全部分镜塞入一个文本节点。没有抽取角色场景时先引导用户完成抽取。
只有工具结果成功才能宣告该阶段完成；失败时说明未完成。规划后等待用户点击下一步，不自动提交付费生成任务。
只有用户明确要求修改项目剧本资料或分集记录时才使用 update_script、update_shot；这两个工具不创建画布节点，不能替代 add_canvas_node。
可以使用 estimate_generation_price 报价，使用 create_image_task、create_video_task、create_audio_task 提交任务。
媒体工具只代表任务已排队，不要声称图片、视频或音频已经完成。完成工具调用后再给用户可见说明。"""

Complete = Callable[..., Awaitable[str]]
Stream = Callable[..., AsyncGenerator[str, None]]


def _history_lines(history: list[dict[str, Any]]) -> list[str]:
    """把最近消息收成短文本。"""
    lines = []
    for message in history[-8:]:
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        lines.append(f"{message.get('role') or 'user'}：{text[:500]}")
    return lines


async def iter_agent_turn(
    *,
    view: dict[str, Any],
    canvas,
    prompt: str,
    history: list[dict[str, Any]] | None = None,
    allow_write: bool = True,
    stopped: Callable[[], bool] | None = None,
    complete: Complete = chat_completions,
    stream: Stream | None = None,
    guard: Callable[[], Awaitable[None]] | None = None,
    enabled_tools: list[str] | None = None,
    review_changes: bool = False,
    skill_block: str = "",
    required_tool: str | None = None,
    planning_node_ids: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Bounded tool loop; disabled tools are omitted from model context and enforced."""
    document, version = await canvas.load()
    conversation = [
        f"项目：{json.dumps({key: view.get(key) for key in ('id', 'title', 'description', 'workflow')}, ensure_ascii=False)}",
        f"画布摘要：{json.dumps(summarize_canvas(document, version), ensure_ascii=False)}",
        *_history_lines(history or []),
        f"用户请求：{prompt}",
    ]
    definitions = [{key: value for key, value in tool.items() if key != 'execute'} for tool in tool_definitions() if enabled_tools is None or tool['name'] in enabled_tools]
    system = with_skill_system(SYSTEM_PROMPT, skill_block) + '\n工具参数说明：' + json.dumps(definitions, ensure_ascii=False)
    if enabled_tools == []:
        # The writing request already contains the exact node, references and
        # output constraints. A whole-canvas summary introduces unrelated shots.
        conversation = [*_history_lines(history or []), f'用户请求：{prompt}']
        system = with_skill_system(
            '你是影视创作编辑。只完成用户指定的当前文本任务，返回可直接使用的最终正文。'
            '以当前镜头事实和实际参数为准；参考文本只提供人物、场景和连续性，不能替代当前任务。'
            '细化可见动作、空间关系、摄影和声音，不堆砌形容词，不复述创作要求，不添加未要求的剧情。'
            '自行检查动作能否在指定时长完成、运镜是否自相矛盾、台词是否来自当前镜头。'
            '不要解释过程，不调用工具，不输出开场白或结束语。', skill_block)
    if review_changes:
        system += '\n本次使用改动预览：画布工具只产生待应用卡片，不会立即修改画布。请把当前阶段的节点与连线放在同一次调用中，之后等待用户应用。角色和场景会各自分组，每个参考图配套独立写作文本节点；分镜也成对分组。不要宣称已应用或已生成。'
    if required_tool:
        system += f'\n本次创作必须实际调用 {required_tool}。不得以“现在提交”“现在创建”等过渡语结束；下一步必须立即输出该工具的 JSON 调用，只有工具成功或形成改动卡片后才算完成。'
    executions = 0
    if planning_node_ids and required_tool in {'plan_story_assets', 'plan_story_shots'} and (enabled_tools is None or 'read_canvas' in enabled_tools):
        # The stage already knows the source script and owned assets. Read them
        # directly instead of spending model round trips deciding which IDs to read.
        ids = list(dict.fromkeys(planning_node_ids))
        for offset in range(0, len(ids), 20):
            if guard:
                await guard()
            if stopped and stopped():
                return
            payload = {'node_ids': ids[offset:offset + 20]}
            call_id = f'prefetch-{offset // 20}'
            yield {'type': 'tool_start', 'tool': 'read_canvas', 'call_id': call_id, 'data': payload}
            result = await execute_studio_tool('read_canvas', payload, view, canvas, allow_write=False)
            yield {'type': 'tool_result', 'tool': 'read_canvas', 'call_id': call_id, 'ok': result.get('ok', False), 'summary': '已读取规划资料' if result.get('ok') else '规划资料读取失败', 'data': result}
            if not result.get('ok'):
                raise ValueError('规划资料已变化，请重新选择剧本后重试')
            conversation.append('系统已调用 read_canvas 读取的完整规划资料：' + json.dumps(result, ensure_ascii=False))
        system += '\n系统已经执行 read_canvas 并提供完整规划资料。不要重复读取相同节点，直接生成当前阶段的规划工具调用；只有缺少额外资料才补读。'
    review_failures = 0
    required_retries = 0
    required_satisfied = required_tool is None
    for _step in range(12):
        if stopped and stopped():
            return
        if guard:
            await guard()
        if stopped and stopped():
            return
        buffer = VisibleReplyBuffer()
        progress_name = '分镜方案' if required_tool == 'plan_story_shots' else '资产方案'
        if required_tool:
            yield {'type': 'model_progress', 'content': f'正在等待模型返回{progress_name}（第 {_step + 1} 轮）'}
        # 必需工具缺席后的纠正轮使用完整响应，避免流式特殊标记截断工具 JSON。
        if stream is not None and required_retries == 0:
            source = stream(system, "\n".join(conversation))
            pending = None
            queued = ''
            last_flush = 0.0
            last_progress = 0.0
            try:
                while True:
                    pending = asyncio.create_task(anext(source))
                    while not pending.done():
                        await asyncio.wait({pending}, timeout=.1)
                        if stopped and stopped():
                            return
                        if queued and monotonic() - last_flush >= .1:
                            yield {'type': 'message_delta', 'content': queued}
                            queued, last_flush = '', monotonic()
                    if stopped and stopped():
                        return
                    try:
                        chunk = pending.result()
                    except StopAsyncIteration:
                        break
                    queued += buffer.push(chunk)
                    if required_tool and monotonic() - last_progress >= 2:
                        yield {'type': 'model_progress', 'content': f'正在接收{progress_name}，已收到 {len(buffer.raw)} 字符'}
                        last_progress = monotonic()
                    if queued and (len(queued) >= 128 or monotonic() - last_flush >= .1):
                        yield {'type': 'message_delta', 'content': queued}
                        queued, last_flush = '', monotonic()
                if queued:
                    yield {'type': 'message_delta', 'content': queued}
                    queued = ''
                answer = buffer.raw
            except Exception:
                if queued:
                    yield {'type': 'message_delta', 'content': queued}
                raise
            finally:
                if pending is not None:
                    if not pending.done():
                        pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                await source.aclose()
        else:
            pending = asyncio.create_task(complete(system, "\n".join(conversation)))
            try:
                while not pending.done():
                    await asyncio.wait({pending}, timeout=.25)
                    if stopped and stopped():
                        return
                answer = pending.result()
            finally:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        if stopped and stopped():
            return
        visible, action = split_assistant_action(answer)
        if required_tool and action:
            yield {'type': 'model_progress', 'content': f'{progress_name}已接收，正在校验节点与连线'}
        remaining = buffer.remainder(visible)
        calls = action.get('tool_calls', [action]) if action else []
        if action:
            try:
                if action.get('action_error'):
                    raise ValueError(action['action_error'])
                if sum(key in action for key in ('tool', 'tool_calls', 'canvas_operations')) != 1:
                    raise ValueError('请在一次回复中使用同一种工具调用格式')
                if 'canvas_operations' in action:
                    validate_canvas_operations(action['canvas_operations'])
                else:
                    if not isinstance(calls, list) or not calls or len(calls) > 12 - executions:
                        raise ValueError('单轮最多执行 12 个工具，请拆分请求')
                    for call in calls:
                        if not isinstance(call, dict) or call.get('tool') not in TOOL_NAMES or not isinstance(call.get('input', {}), dict) or any(key in call for key in ('tool_calls', 'canvas_operations')):
                            raise ValueError('工具名称或参数格式无效，操作未执行')
                        validate_tool_input(call['tool'], call.get('input', {}))
            except ValueError as exc:
                yield {'type': 'error', 'code': 'invalid_tool_action', 'message': str(exc)}
                yield {'type': 'message_delta', 'content': f'操作未执行：{exc}。'}
                return
        if action and guard:
            await guard()
        if stopped and stopped():
            return
        if action and enabled_tools is not None:
            needed = CANVAS_WRITE_TOOLS if 'canvas_operations' in action else {call['tool'] for call in calls}
            if not needed.issubset(set(enabled_tools)):
                yield {'type': 'tool_result', 'tool': str(action.get('tool') or 'canvas_operations'), 'ok': False, 'summary': '该工具已在当前对话的工具控制中关闭'}
                yield {'type': 'message_delta', 'content': '此操作需要启用对应工具。请在工具控制中调整后重试。'}
                return
        if not action:
            if not required_satisfied:
                if required_retries < 2:
                    required_retries += 1
                    conversation.append(f"上一轮助手回复：{answer[:4000]}")
                    conversation.append(f"系统纠正：上一轮没有实际调用 {required_tool}，不能就此结束。不要复述计划或过渡语，请立即只输出 {required_tool} 的完整 JSON 工具调用。")
                    continue
                raise RuntimeError(f'模型连续未实际调用 {required_tool}，本次创作未提交')
            if remaining:
                yield {"type": "message_delta", "content": remaining}
            return
        from app.printfilm_studio.agent.proposals import REVIEW_TOOLS, prepare_proposal
        if review_changes and ('canvas_operations' in action or any(call['tool'] in REVIEW_TOOLS for call in calls)):
            if 'canvas_operations' not in action and not all(call['tool'] in REVIEW_TOOLS for call in calls):
                yield {'type': 'error', 'message': '请将画布改动与查询、生成任务分开规划，本批未执行。'}
                return
            result = await prepare_proposal(action, view, canvas, allow_write)
            if result.get('ok'):
                if any(call.get('tool') == required_tool for call in calls):
                    required_satisfied = True
                yield {'type': 'proposal', 'data': result['proposal']}
                yield {'type': 'message_delta', 'content': '这批节点与连线已规划好，请查看改动卡片。点击「只应用」写入画布，或「应用并运行」选择模型、确认费用后生成。'}
            else:
                if any(call.get('tool') == 'plan_story_shots' for call in calls) and review_failures < 2:
                    review_failures += 1
                    conversation.append('分镜方案校验未通过，尚未修改画布。请修正整批参数并重新调用 plan_story_shots，不要只回复说明：' + str(result.get('error')))
                    yield {'type': 'thinking', 'content': '正在补齐分镜对应的场景引用…'}
                    continue
                yield {'type': 'error', 'message': result.get('error') or '规划失败，画布未修改'}
                yield {'type': 'message_delta', 'content': '本次分镜方案未通过校验，未应用到画布。请核对上方提示的场景关联后重试。'}
            return
        if 'canvas_operations' in action:
            call_id = str(executions)
            yield {"type": "tool_start", "tool": "canvas_operations", "call_id": call_id, "data": action}
            result = await execute_studio_tool("apply_canvas_operations", action, view, canvas, allow_write=allow_write)
            yield {"type": "tool_result", "tool": "canvas_operations", "call_id": call_id, "ok": result.get("ok") is True, "summary": result.get("error") or "已更新画布", "data": result}
            if result.get("ok"):
                yield {"type": "canvas_patch", "base_version": result['version'] - 1, "operations": result['operations']}
                yield {"type": "canvas_updated", "version": result.get("version")}
            if remaining:
                yield {"type": "message_delta", "content": remaining}
            elif not visible and result.get("ok"):
                yield {"type": "message_delta", "content": "已按你的要求更新画布。"}
            elif not visible:
                yield {"type": "message_delta", "content": str(result.get("error") or "画布没有更新")}
            return
        if remaining:
            yield {"type": "message_delta", "content": remaining}
        if len(calls) > 1 and all(call['tool'] in CANVAS_WRITE_TOOLS for call in calls):
            for index, call in enumerate(calls):
                yield {'type': 'tool_start', 'tool': call['tool'], 'call_id': str(executions + index), 'data': call.get('input', {})}
            if guard:
                await guard()
            if stopped and stopped():
                return
            result = await execute_canvas_tool_batch(calls, canvas, allow_write=allow_write)
            for index, call in enumerate(calls):
                yield {'type': 'tool_result', 'tool': call['tool'], 'call_id': str(executions + index), 'ok': result.get('ok') is True, 'summary': result.get('error') or '已完成', 'data': result}
            if result.get('ok'):
                yield {'type': 'canvas_patch', 'base_version': result['version'] - 1, 'operations': result['operations']}
                yield {'type': 'canvas_updated', 'version': result['version']}
            executions += len(calls)
            conversation.append(f"画布批量工具结果：{json.dumps(result, ensure_ascii=False)[:4000]}")
        else:
            for call in calls:
                if guard:
                    await guard()
                if stopped and stopped():
                    return
                name, tool_input = call['tool'], call.get('input', {})
                call_id = str(executions)
                executions += 1
                yield {"type": "tool_start", "tool": name, "call_id": call_id, "data": tool_input}
                result = await execute_studio_tool(name, tool_input, view, canvas, allow_write=allow_write)
                yield {"type": "tool_result", "tool": name, "call_id": call_id, "ok": result.get("ok") is True, "summary": result.get("error") or "已完成", "data": result}
                if name == required_tool and result.get('ok'):
                    required_satisfied = True
                if result.get("ok") and result.get("task_id"):
                    yield {"type": "task_created", "task_id": result["task_id"], "platform_task_id": result.get("platform_task_id"), "node_id": result.get("node_id"), "status": result.get("status", "queued")}
                if result.get("ok") and result.get("version"):
                    yield {"type": "canvas_updated", "version": result.get("version")}
                if result.get('ok') and name in {'plan_story_assets', 'plan_story_shots'}:
                    message = '角色与场景的写作要求和图片节点已准备好；最终提示词会在运行写作节点时生成。检查后可点击「拆分分镜」继续。' if name == 'plan_story_assets' else '已创建分镜写作要求与视频节点，并连接对应角色和场景参考图。选择「运行到这里」可按依赖生成上游素材、最终提示词及目标结果。'
                    yield {'type': 'message_delta', 'content': '\n\n' + message}
                    return
                result_limit = 100000 if name == 'read_canvas' and tool_input.get('node_ids') else 16000 if name in {'plan_story_assets', 'plan_story_shots'} else 4000
                conversation.append(f"工具 {name} 结果：{json.dumps(result, ensure_ascii=False)[:result_limit]}")
        if executions >= 12:
            break
    if not required_satisfied:
        raise RuntimeError(f'模型连续未实际调用 {required_tool}，本次创作未提交')
    yield {"type": "message_delta", "content": "本轮已执行 12 个工具步骤，达到单轮上限。已完成的内容已保留，可以继续发送消息处理剩余步骤。"}
