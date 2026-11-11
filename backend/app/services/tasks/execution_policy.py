"""文字 LLM 直接执行；媒体生成和混合流水线继续受队列限流。"""
from sqlalchemy import and_, func, or_

DIRECT_DRAMA_TYPES = ("script_summary", "episode_script", "fragment_plan", "seed_assets")
INLINE_DRAMA_TYPES = ("agent_chat", "skill_optimize", "voice_prompt")


def is_direct_llm_task(domain: str, task_type: str, payload: dict | None = None) -> bool:
    """只包含有真实执行器的纯文字任务，不能按 text 队列笼统绕过配音限流。"""
    return (domain == "drama" and task_type in DIRECT_DRAMA_TYPES) or (
        domain == "kepu" and task_type == "project_pipeline" and (payload or {}).get("phase") == "script"
    )


def llm_task_condition(model, *, runnable_only: bool = False):
    """SQL 口径与入口分类一致；内联聊天记录也不占队列容量。"""
    types = DIRECT_DRAMA_TYPES if runnable_only else DIRECT_DRAMA_TYPES + INLINE_DRAMA_TYPES
    terms = [
        and_(model.domain == "drama", model.task_type.in_(types)),
        and_(model.domain == "kepu", model.task_type == "project_pipeline", func.coalesce(model.payload["phase"].as_string(), "") == "script"),
    ]
    if not runnable_only:
        terms.append(and_(model.domain == "studio", model.task_type.in_(("agent_chat", "node_writing"))))
        terms.append(and_(model.domain == "kepu", model.task_type == "content_expand"))
    return or_(*terms)


def execution_mode(domain: str, task_type: str, payload: dict | None = None) -> str:
    """对外区分即时文字执行与调度队列，仍保留原任务类型和历史记录。"""
    inline = (domain == "studio" and task_type in {"agent_chat", "node_writing"}) or (domain == "drama" and task_type in INLINE_DRAMA_TYPES) or (domain == "kepu" and task_type == "content_expand")
    return "direct" if inline or is_direct_llm_task(domain, task_type, payload) else "queued"
