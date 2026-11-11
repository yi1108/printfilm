"""Printfilm Studio additive schema 回归测试。"""

from types import SimpleNamespace

from app.printfilm_studio.schema import apply_printfilm_studio_schema_patches


class RecordingConnection:
    """记录 ORM 建表目标，不依赖真实数据库。"""

    def __init__(self):
        self.dialect = SimpleNamespace(name="postgresql")
        self.statements = []
        self.tables = []

    async def execute(self, statement):
        self.statements.append(str(statement))

    async def run_sync(self, fn, **_kwargs):
        # schema.py 的 lambda 通过默认参数携带 Table；不执行真实 DDL。
        self.tables.append(fn.__defaults__[0].name)


async def test_schema_patch_creates_workflow_run_table():
    conn = RecordingConnection()
    await apply_printfilm_studio_schema_patches(conn)
    assert "printfilm_studio_workflow_runs" in conn.tables
    assert "printfilm_studio_agent_runs" in conn.tables
    assert "printfilm_studio_agent_events" in conn.tables
    assert "printfilm_studio_recipes" in conn.tables
    assert any("CREATE TABLE IF NOT EXISTS printfilm_studio_canvas_documents" in statement for statement in conn.statements)
