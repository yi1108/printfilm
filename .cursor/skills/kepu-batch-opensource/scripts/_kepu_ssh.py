# -*- coding: utf-8 -*-
"""SSH helpers for kepu.printfilm.com batch jobs."""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import paramiko

REPO_ROOT = Path(__file__).resolve().parents[4]
DEPLOY_KEPU = REPO_ROOT / "deploy" / "scripts" / "deploy_kepu.py"
DEFAULT_API = "http://127.0.0.1:8000"
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"


def load_ssh_creds() -> tuple[str, str, str]:
    host = os.environ.get("KEPU_SSH_HOST", "").strip()
    user = os.environ.get("KEPU_SSH_USER", "").strip()
    password = os.environ.get("KEPU_SSH_PASSWORD", "").strip()
    if host and user and password:
        return host, user, password
    if not DEPLOY_KEPU.is_file():
        raise FileNotFoundError(
            "Set KEPU_SSH_HOST/USER/PASSWORD or provide deploy/scripts/deploy_kepu.py"
        )
    text = DEPLOY_KEPU.read_text(encoding="utf-8", errors="replace")

    def grab(name: str) -> str:
        m = re.search(rf'^{name}\s*=\s*([\'"])(.*?)\1', text, re.M)
        if not m:
            raise ValueError(f"{name} not found in {DEPLOY_KEPU}")
        return m.group(2)

    return grab("HOST"), grab("USER"), grab("PASSWORD")


def connect() -> paramiko.SSHClient:
    host, user, password = load_ssh_creds()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)
    return ssh


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[str, str]:
    _i, o, e = ssh.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


def put_bytes(ssh: paramiko.SSHClient, remote_path: str, data: bytes) -> None:
    b64 = base64.b64encode(data).decode("ascii")
    py = (
        "python3 - <<'PY'\n"
        "import base64\n"
        f"open({remote_path!r},'wb').write(base64.b64decode({b64!r}))\n"
        f"print('wrote', {remote_path!r}, len(open({remote_path!r},'rb').read()))\n"
        "PY"
    )
    out, err = run(ssh, py, timeout=180)
    if "wrote" not in out:
        raise RuntimeError(f"put_bytes failed: {out}\n{err}")


def put_text(ssh: paramiko.SSHClient, remote_path: str, text: str) -> None:
    put_bytes(ssh, remote_path, text.encode("utf-8"))
