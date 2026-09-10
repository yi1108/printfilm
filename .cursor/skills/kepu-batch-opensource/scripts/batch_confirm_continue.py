# -*- coding: utf-8 -*-
"""Wait until SCRIPT_READY then continue full pipeline for project ids.

Usage:
  python batch_confirm_continue.py --ids 49-58
  python batch_confirm_continue.py --ids 49,50,51
  python batch_confirm_continue.py --from-results .tmp/submit-results.json
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kepu_ssh import DEFAULT_API, DEMO_EMAIL, DEMO_PASSWORD, connect, put_text, run

REMOTE_RUNNER = "/tmp/kepu_batch_confirm_runner.py"
REMOTE_OUT = "/tmp/kepu_batch_confirm_results.json"


def parse_ids(spec: str) -> list[int]:
    ids: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ids.extend(range(int(a), int(b) + 1))
        else:
            ids.append(int(part))
    return ids


def build_runner(pids: list[int], wait_sec: int) -> str:
    return textwrap.dedent(
        f"""\
        # -*- coding: utf-8 -*-
        import json, time, urllib.request, urllib.error
        BASE = {DEFAULT_API!r}
        PIDS = {pids!r}
        OUT = {REMOTE_OUT!r}
        EMAIL = {DEMO_EMAIL!r}
        PASSWORD = {DEMO_PASSWORD!r}
        WAIT = {wait_sec}

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
                raise RuntimeError(f"{{method}} {{path}} -> {{e.code}}: {{text[:500]}}") from e

        tok = api("POST", "/api/auth/login", {{"email": EMAIL, "password": PASSWORD}})["access_token"]
        print("login ok", flush=True)
        deadline = time.time() + WAIT
        while time.time() < deadline:
            rows = []
            for pid in PIDS:
                p = api("GET", f"/api/projects/{{pid}}", token=tok)
                rows.append((pid, p.get("status"), len(p.get("shots") or []), p.get("title") or ""))
            scripting = [r for r in rows if r[1] == "SCRIPTING"]
            ready = [r for r in rows if r[1] == "SCRIPT_READY"]
            print(
                "poll ready=%d scripting=%d | %s"
                % (len(ready), len(scripting), " | ".join(f"{{a}}:{{b}}/{{c}}t" for a,b,c,*_ in rows)),
                flush=True,
            )
            if not scripting:
                break
            time.sleep(8)

        results = []
        for pid in PIDS:
            p = api("GET", f"/api/projects/{{pid}}", token=tok)
            st = p.get("status")
            title = p.get("title") or ""
            tpl = p.get("template_id")
            shots = len(p.get("shots") or [])
            if st == "SCRIPT_READY":
                try:
                    gen = api("POST", f"/api/projects/{{pid}}/generate", token=tok)
                    row = {{
                        "id": pid, "title": title, "template_id": tpl, "shots": shots,
                        "action": "continue", "status": gen.get("status"),
                        "url": f"https://kepu.printfilm.com/studio/{{pid}}",
                    }}
                    print("CONTINUE", pid, title, "->", gen.get("status"), flush=True)
                except Exception as ex:
                    row = {{
                        "id": pid, "title": title, "template_id": tpl, "shots": shots,
                        "action": "error", "status": str(ex),
                        "url": f"https://kepu.printfilm.com/studio/{{pid}}",
                    }}
                    print("FAIL", pid, ex, flush=True)
            else:
                row = {{
                    "id": pid, "title": title, "template_id": tpl, "shots": shots,
                    "action": "skip", "status": st,
                    "url": f"https://kepu.printfilm.com/studio/{{pid}}",
                }}
                print("SKIP", pid, st, "shots=", shots, title, flush=True)
            results.append(row)
            time.sleep(0.4)

        open(OUT, "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=2))
        print("DONE", OUT, flush=True)
        """
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="e.g. 49-58 or 49,50,51")
    ap.add_argument("--from-results", type=Path, help="submit-results.json with id fields")
    ap.add_argument("--wait", type=int, default=900, help="max seconds waiting for SCRIPT_READY")
    ap.add_argument("--out", type=Path, default=Path(".tmp/confirm-continue-results.json"))
    args = ap.parse_args()

    pids: list[int] = []
    if args.from_results:
        rows = json.loads(args.from_results.read_text(encoding="utf-8"))
        pids = [int(r["id"]) for r in rows]
    if args.ids:
        pids = parse_ids(args.ids)
    if not pids:
        print("provide --ids or --from-results", file=sys.stderr)
        return 2
    print("pids", pids)

    ssh = connect()
    try:
        put_text(ssh, REMOTE_RUNNER, build_runner(pids, args.wait))
        out, err = run(ssh, f"python3 {REMOTE_RUNNER}", timeout=args.wait + 120)
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
