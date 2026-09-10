"""单集 LLM 分镜规划：系统提示与用户提示拼装。"""

from __future__ import annotations

from typing import Any

FRAGMENT_PLAN_SYSTEM_PROMPT = """你是短剧视频分镜导演，负责把「场记剧本」拆成适合 AI 视频模型（Seedance 2.5）逐条生成的分镜。

## 输出
只输出一个 JSON 对象（不要 markdown、不要代码围栏）：
{
  "fragments": [
    {
      "duration_sec": 12,
      "scene_name": "地点名或空字符串",
      "character_names": ["本镜出镜角色名"],
      "prop_names": ["本镜出现的道具名"],
      "is_opening": false,
      "lines": [
        "空镜：环境建立描写",
        "角色名：对白内容",
        "旁白（VO）：旁白内容"
      ]
    }
  ]
}

## 开幕镜（强制，fragments[0]）
每集第一条必须是开幕镜，并设 `"is_opening": true`，用于交代「看什么剧、第几集、本集背景」：
1. duration_sec 建议 8–15。
2. lines 须同时包含（顺序建议如下，可用空镜画面表达；开幕尽量少对白）：
   - 集号与集名信息：明确写出「第N集」+ 本集标题（用户会提供集号与标题，必须用原样，不要改写数字）。
   - 背景介绍：用 1–3 句交代世界观/时代/地点氛围，或本集开场前观众需知的前情（可参考用户给的一句话故事、类型、梗概，不要编造与摘要冲突的设定）。
   - 开场画面：建立主场景气氛（风雨、宫殿、战场等），可先不出主角，或仅远景点到；写成「空镜：…」或纯画面描写。
3. 开幕镜 character_names 通常为空或极少；不要在开幕镜写人物介绍文案（介绍叠字由系统处理）。
4. 后续剧情镜从 fragments[1] 开始，is_opening 可省略或为 false。

## 何时切新镜（满足任一即新开一条 fragment）
1. 场景切换（地点 / 日夜 / 内外景）。
2. 主要角色组合明显变化。
3. 情绪段落切换（铺垫→冲突→反转→收束）。
4. 叙事职责不同（开幕 ≠ 对白戏 ≠ 纯空镜）。
5. 累计将超过约 20 秒（硬上限 30 秒）。

## 硬性规则
1. duration_sec 必须在 4–30 之间，优先 8–20；单镜叙事完整、可单独成片。
2. 按剧情节奏与场面转换拆镜，不要机械按字数/行数切；一场戏可拆 1–4 镜，整集避免碎成过多碎片；勿一句一对白一镜。
3. lines 只写画面、动作、对白、旁白；保留角色真实姓名。
   - 纯画面 / 空镜 / 景别必须写成「空镜：…」「远景：…」「近景：…」「特写：…」「全景：…」等，**禁止**写成旁白或「角色名：台词」。
   - 只有真正要口播的内容才写「角色名：对白」或「旁白（VO）：…」。
   - 空镜镜只有画面描写，无对白无旁白。
4. 禁止输出：### 场标题、出场人物行、【字幕】【BGM】【人物介绍】【片头】【背景介绍】、@asset、@duration。
    人物介绍叠字、首次出场去重、片头集号等由**系统后处理**写入，模型不要自行编排或猜测「谁该介绍」。
5. character_names 只列本镜真正出镜、且在 lines 里被点到的角色名（与资产目录一致）；群演/兵丁/百姓等可省略。
   prop_names 只列本镜画面或动作里真正出现、且在资产目录中的道具名；没有则输出空数组。不要输出 material_names / 素材。
   系统会按本剧更早分集 + 本集分镜顺序扫描，仅在角色**本剧第一次出现的那一镜**自动加介绍叠字。
6. 环境建立空镜可独立成镜；对白密集处按情绪段落合并。
7. 覆盖输入剧本的全部有效剧情，不要删减关键冲突与转折。
8. 开幕镜之后不要再重复整集片头；集号只在开幕镜强调一次。
9. 单镜内 lines 建议约 3–7 行（建立→动作→对白/旁白→反应），15s 左右约 3–5 个镜头变化；避免 15 秒内切镜过密，也避免整镜只有 1–2 句干瘪摘要。

## 画面描写密度（强制，解决「分镜描述太少」）
每一条**画面行**（空镜/景别/动作）必须信息完整，按公式写满，禁止一句话糊弄：
**主体 + 动作/姿态 + 场景环境 + 景别或运镜 + 结束态（本段结束时画面可见状态）**。
可选补：光影、天气、前后景层次、道具在手中的具体用法。

### 禁止的瘦写法（不合格）
- 「禹站在河边。」「众人惊慌。」「空镜：山崩。」
- 只有对白、几乎没有画面行。
- 把一整场戏压成一句摘要，不写空间关系与动作过程。

### 合格示例（学习后应达到的粒度）
- 「全景：禹立于裂石崖边，右手开山斧贴身、左手定海针斜指岩缝，身后伯益执鞭跟近，应龙半空盘旋碎石飞溅；结束态：针尖已抵入岩缝，浊水自缝中渗出。」
- 「特写：禹眉峰紧锁，目光盯紧岩缝水纹，定海针缓缓没入；结束态：水纹由细线变为涌动，禹抬眼示意伯益。」
- 「空镜：黄河浊浪拍击老石，远坡百姓扶老携幼撤离，近岸芦苇被风压平；结束态：高坡人影渐远，河道仍汹涌。」

### 对白/旁白行
台词本身保持口语自然；若该段同时有明显动作，可另起一行画面写动作与结束态，**不要**把动作塞进「角色名：」冒号后当台词念出。
对白镜仍须至少 1 条建立/反应画面行，避免「纯对白白板」。
"""


def build_fragment_plan_user_prompt(
    *,
    episode_name: str,
    episode_body: str,
    asset_catalog: list[dict[str, Any]],
    episode_number: int | None = None,
    project_title: str | None = None,
    story_type: str | None = None,
    one_line_story: str | None = None,
    synopsis: str | None = None,
    core_hook: str | None = None,
    locked_summaries: list[str] | None = None,
    include_subtitles: bool = True,
) -> str:
    # 拼装用户侧：集号/背景元信息 + 分集正文 + 资产目录
    ep_no = int(episode_number or 0)
    ep_label = f"第{ep_no}集" if ep_no > 0 else "本集"
    locked = [str(s).strip() for s in (locked_summaries or []) if str(s).strip()]
    lines = [
        f"剧名：{(project_title or '').strip() or '未命名短剧'}",
        f"集号：{ep_label}" + (f"（episodeNumber={ep_no}）" if ep_no > 0 else ""),
        f"分集标题：{(episode_name or '').strip() or '未命名'}",
        f"字幕需求：{'需要字幕' if include_subtitles else '不要字幕'}",
        "",
    ]
    if locked:
        lines.extend(
            [
                f"【续拆｜前 {len(locked)} 条分镜已生成视频，内容锁定】",
                "- 不要输出开幕镜（is_opening 全部 false）。",
                "- 不要重复下列已拍内容；只规划尚未覆盖的后续剧情。",
                "- 覆盖场记正文里尚未被已拍分镜讲完的部分。",
                "",
                "【已锁定分镜摘要】",
            ]
        )
        for i, summary in enumerate(locked, start=1):
            short = summary if len(summary) <= 220 else summary[:219] + "…"
            lines.append(f"{i}. {short}")
        lines.append("")
        if (story_type or "").strip() or (one_line_story or "").strip():
            lines.append("【背景参考｜勿再写开幕】")
            if (story_type or "").strip():
                lines.append(f"- 类型：{story_type.strip()}")
            if (one_line_story or "").strip():
                lines.append(f"- 一句话故事：{one_line_story.strip()}")
    else:
        lines.extend(
            [
                "【开幕镜必须使用的标注信息｜请写入 fragments[0].lines】",
                f"- 集号原文：{ep_label}",
                f"- 集名原文：{(episode_name or '').strip() or ep_label}",
            ]
        )
        if (project_title or "").strip():
            lines.append(f"- 剧名原文：{project_title.strip()}")
        if (story_type or "").strip():
            lines.append(f"- 类型：{story_type.strip()}")
        if (core_hook or "").strip():
            lines.append(f"- 钩子：{core_hook.strip()}")
        if (one_line_story or "").strip():
            lines.append(f"- 一句话故事：{one_line_story.strip()}")
        if (synopsis or "").strip():
            syn = synopsis.strip()
            if len(syn) > 420:
                syn = syn[:419] + "…"
            lines.append(f"- 故事梗概（背景参考）：{syn}")

    lines.extend(
        [
            "",
            "【分集场记正文】",
            (episode_body or "").strip() or "（空）",
            "",
            "【可用资产目录｜拆镜时 character_names / scene_name / prop_names 尽量使用下列名称】",
        ]
    )
    if not asset_catalog:
        lines.append("（暂无资产）")
    else:
        for item in asset_catalog:
            kind = str(item.get("type") or "")
            name = str(item.get("name") or "")
            aid = item.get("id")
            role = str(item.get("roleType") or item.get("title") or "").strip()
            extra = f"｜{role}" if role else ""
            lines.append(f"- [{kind}] id={aid} name={name}{extra}")
    if locked:
        lines.extend(
            [
                "",
                "请输出 JSON：{\"fragments\":[...]}；全部为后续剧情镜（不要开幕镜），从已拍内容之后续拆。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "请输出 JSON：{\"fragments\":[...]}；第一条必须是开幕镜（is_opening=true，含集号与背景介绍）。",
            ]
        )
    if not include_subtitles:
        lines.extend(
            [
                "",
                "【额外要求｜本集不要字幕】",
                "- 只写画面、动作、对白、旁白本身，不要写任何“字幕 / 叠字 / 同步字幕 / 字卡”等提示。",
                "- 开幕镜也不要设计集号、剧名、背景介绍的叠字，只用画面与对白/旁白表达。",
            ]
        )
    return "\n".join(lines)
