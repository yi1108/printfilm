"""A completed text/chat task has one fixed retail charge; media pricing is unchanged."""
from app.services.tasks.execution_policy import execution_mode

TEXT_PRICE_FEN = 5


def is_text_task(task):
    return (task.domain == 'studio' and task.task_type in {'agent_chat', 'node_writing'}) or execution_mode(task.domain, task.task_type, task.payload) == 'direct'


def text_charge(task, events, fallback):
    if not is_text_task(task):
        return fallback
    charge = TEXT_PRICE_FEN if task.status == 'succeeded' and task.billing_status != 'skipped' and task.billing_enabled_snapshot is not False else 0
    # Keep upstream cost/token evidence, but retail usage totals must match the ledger.
    for index, event in enumerate(events):
        event.charge_fen = charge if index == 0 else 0
    return charge
