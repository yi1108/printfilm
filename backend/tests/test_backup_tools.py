from unittest.mock import Mock
import pytest
from app.services.billing import backup_tools

def test_existing_path_has_priority(monkeypatch):
    monkeypatch.setattr(backup_tools.shutil,"which",lambda name: "/usr/bin/"+name)
    assert backup_tools.resolve("pg_dump")=="/usr/bin/pg_dump"

def test_windows_refreshes_registered_path(monkeypatch):
    monkeypatch.setattr(backup_tools.sys,"platform","win32")
    monkeypatch.setattr(backup_tools,"windows_registered_path",lambda:"registered-bin")
    probe=Mock(side_effect=[None,"registered-bin/pg_restore.exe"])
    monkeypatch.setattr(backup_tools.shutil,"which",probe)
    assert backup_tools.resolve("pg_restore")=="registered-bin/pg_restore.exe"
    probe.assert_called_with("pg_restore",path="registered-bin")

def test_missing_windows_tool_has_local_instructions(monkeypatch):
    monkeypatch.setattr(backup_tools.sys,"platform","win32")
    monkeypatch.setattr(backup_tools,"windows_registered_path",lambda:"")
    monkeypatch.setattr(backup_tools.shutil,"which",lambda *a,**k:None)
    with pytest.raises(ValueError,match="Windows") as error:
        backup_tools.resolve("pg_dump")
    assert "镜像" not in str(error.value)
