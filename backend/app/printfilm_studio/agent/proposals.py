"""Compute a reviewed canvas change on a private copy, without persistence/tasks."""
from copy import deepcopy
from uuid import uuid4

REVIEW_TOOLS = {'add_canvas_node', 'update_canvas_node', 'remove_canvas_node', 'connect_canvas_nodes',
                'attach_asset_to_node', 'plan_story_assets', 'plan_story_shots'}


class PreviewCanvas:
    def __init__(self, document, version, context_info=None):
        self.context_info = context_info or {}
        self.document, self.version = deepcopy(document), version

    async def load(self):
        return deepcopy(self.document), self.version

    async def save(self, document):
        from .node_defaults import apply_node_defaults
        apply_node_defaults(document, {node['id'] for node in self.document.get('nodes', [])}, self.context_info)
        self.document = deepcopy(document)
        self.version += 1
        return self.version


def canvas_proposal(before, after):
    changes = {}
    for key in ('nodes', 'edges'):
        old = {item['id']: item for item in before.get(key, [])}
        new = {item['id']: item for item in after.get(key, [])}
        changes[key] = [{'id': identity, 'before': old.get(identity), 'after': new.get(identity)}
                        for identity in dict.fromkeys([*old, *new]) if old.get(identity) != new.get(identity)]
    return {'id': str(uuid4()), **changes}


async def prepare_proposal(action, view, canvas, allow_write):
    from app.printfilm_studio.agent.executor import execute_studio_tool, execute_canvas_tool_batch, CANVAS_WRITE_TOOLS
    before, version = await canvas.load()
    from .node_defaults import canvas_context
    preview = PreviewCanvas(before, version, canvas_context(canvas))
    if 'canvas_operations' in action:
        result = await execute_studio_tool('apply_canvas_operations', action, view, preview, allow_write=allow_write)
    else:
        calls = action.get('tool_calls', [action])
        if len(calls) > 1 and all(call['tool'] in CANVAS_WRITE_TOOLS for call in calls):
            result = await execute_canvas_tool_batch(calls, preview, allow_write=allow_write)
        else:
            for call in calls:
                result = await execute_studio_tool(call['tool'], call.get('input', {}), view, preview, allow_write=allow_write)
                if not result.get('ok'):
                    break
    if not result.get('ok'):
        return result
    return {'ok': True, 'proposal': canvas_proposal(before, preview.document)}
