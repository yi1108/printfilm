# -*- coding: utf-8 -*-
"""Upload scripts JSON via SSH and create+generate projects on prod localhost API.

Usage:
  python .cursor/skills/kepu-batch-opensource/scripts/batch_submit.py .tmp/scripts.json
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

# allow running as script from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kepu_ssh import DEFAULT_API, DEMO_EMAIL, DEMO_PASSWORD, connect, put_bytes, put_text, run

REMOTE_SCRIPTS = "/tmp/kepu_batch_scripts.json"
REMOTE_RUNNER = "/tmp/kepu_batch_submit_runner.py"
REMOTE_OUT = "/tmp/kepu_batch_submit_results.json"


def build_runner() -> str:
    return textwrap.dedent(
        f"""\
        # -*- coding: utf-8 -*-
        import json, time, urllib.request, urllib.error
        BASE = {DEFAULT_API!r}
        SCRIPTS = {REMOTE_SCRIPTS!r}
        OUT = {REMOTE_OUT!r}
        EMAIL = {DEMO_EMAIL!r}
        PASSWORD = {DEMO_PASSWORD!r}

        def api(method, path, body=None, token=None, timeout=120):
            data = None
            headers = {{"Accept": "application/json"}}
            if token:
                headers["Authorization"] = "Bearer " + token
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json; charset=utf-8"
            req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {{}}
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                raise RuntimeError(f"{{method}} {{path}} -> {{e.code}}: {{text[:800]}}") from e

        tok = api("POST", "/api/auth/login", {{"email": EMAIL, "password": PASSWORD}})["access_token"]
        print("login ok", flush=True)
        items = json.load(open(SCRIPTS, encoding="utf-8"))
        print("count", len(items), "title0", items[0].get("title"), flush=True)
        results = []
        for i, it in enumerate(items, 1):
            print(f"=== {{i}}/{{len(items)}} {{it.get('title')}} tpl={{it.get('template_id')}}", flush=True)
            body = {{
                "template_id": it["template_id"],
                "title": it["title"],
                "source_type": "script",
                "source_text": it["source_text"],
                "resolution_mode": it.get("resolution_mode", "preview"),
                "pipeline_mode": it.get("pipeline_mode", "full"),
                "output_ratio": it["output_ratio"],
                "voice_id": it["voice_id"],
            }}
            if it.get("character_prompt"):
                body["character_prompt"] = it["character_prompt"]
            if it.get("extra_prompt"):
                body["extra_prompt"] = it["extra_prompt"]
            p = api("POST", "/api/projects", body, token=tok)
            pid = p["id"]
            patch = {{
                "output_ratio": it["output_ratio"],
                "voice_id": it["voice_id"],
                "pipeline_mode": it.get("pipeline_mode", "full"),
            }}
            if it.get("character_prompt"):
                patch["character_prompt"] = it["character_prompt"]
            if it.get("extra_prompt"):
                patch["extra_prompt"] = it["extra_prompt"]
            api("PATCH", f"/api/projects/{{pid}}", patch, token=tok)
            gen = api("POST", f"/api/projects/{{pid}}/generate", token=tok)
            row = {{
                "id": pid,
                "title": gen.get("title") or it["title"],
                "template_id": gen.get("template_id"),
                "status": gen.get("status"),
                "output_ratio": gen.get("output_ratio"),
                "voice_id": gen.get("voice_id"),
                "url": f"https://kepu.printfilm.com/studio/{{pid}}",
            }}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            time.sleep(0.5)

        for r in results:
            d = api("GET", f"/api/projects/{{r['id']}}", token=tok)
            print("verify", r["id"], ascii(d.get("title")), d.get("status"),
                  ascii((d.get("source_text") or "")[:16]), flush=True)

        open(OUT, "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=2))
        print("DONE", OUT, flush=True)
        """
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch create kepu projects from scripts JSON")
    ap.add_argument("scripts_json", type=Path)
    ap.add_argument("--out", type=Path, default=Path(".tmp/submit-results.json"))
    args = ap.parse_args()

    raw = args.scripts_json.read_bytes()
    items = json.loads(raw.decode("utf-8"))
    if not isinstance(items, list) or not items:
        print("scripts json must be a non-empty array", file=sys.stderr)
        return 2
    print("local0", items[0].get("title"), "count", len(items))

    ssh = connect()
    try:
        put_bytes(ssh, REMOTE_SCRIPTS, raw)
        put_text(ssh, REMOTE_RUNNER, build_runner())
        out, err = run(ssh, f"python3 {REMOTE_RUNNER}", timeout=600)
        print(out)
        if err.strip():
            print("STDERR", err[-800:], file=sys.stderr)
        out_bytes, _ = run(ssh, f"cat {REMOTE_OUT}", timeout=30)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_bytes, encoding="utf-8")
        print("saved", args.out)
    finally:
        ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
