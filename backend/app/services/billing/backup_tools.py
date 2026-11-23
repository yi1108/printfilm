"""Resolve PostgreSQL tools even when a Windows launcher retains an old PATH."""
import os
import shutil
import sys

def windows_registered_path():
    import winreg
    paths = []
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "Path")
                if isinstance(value, str):
                    paths.append(os.path.expandvars(value))
        except OSError:
            continue
    return os.pathsep.join(paths)

def resolve(tool):
    if tool not in ("pg_dump", "pg_restore"):
        raise ValueError("Unsupported backup tool")
    found = shutil.which(tool)
    if not found and sys.platform == "win32":
        found = shutil.which(tool, path=windows_registered_path())
    if found:
        return found
    if sys.platform == "win32":
        raise ValueError("当前后端找不到 PostgreSQL 备份工具。请在运行后端的 Windows 账号中安装 pg_dump/pg_restore，并将 bin 目录加入用户或系统 PATH。")
    raise ValueError("服务器未安装 PostgreSQL 备份工具，请发布包含 pg_dump/pg_restore 的 API 镜像。")
