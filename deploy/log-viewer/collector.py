"""Publish bounded original log snapshots for the password-protected viewer."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timezone

SNAPSHOTS = Path('/run/printfilm-log-viewer')
MAX_BYTES = 1024 * 1024
MAX_LINES = 1000
SOURCES = {
    'api': ('API 服务', '最近 1 小时，最多 1000 行'),
    'access': ('Nginx 访问', '主站与管理后台最近日志，最多 1000 行'),
    'error': ('Nginx 错误', '主站与管理后台最近错误，最多 1000 行'),
}

def severity(line):
    if re.search(r'\b(?:ERROR|CRITICAL|FATAL|Traceback)\b|(?:→|HTTP/\d(?:\.\d)?["\']?)\s+5\d\d\b|\[(?:error|crit|alert|emerg)\]', line):
        return 'error'
    if re.search(r'\b(?:WARNING|WARN)\b|(?:→|HTTP/\d(?:\.\d)?["\']?)\s+4\d\d\b|\[warn\]', line):
        return 'warning'
    return 'info'


def tail_file(path):
    with Path(path).open('rb') as file:
        file.seek(0, 2)
        size = file.tell()
        file.seek(max(0, size - MAX_BYTES))
        data = file.read(MAX_BYTES)
    lines = data.decode('utf-8', errors='replace').splitlines()
    return lines[1:] if size > MAX_BYTES else lines


def api_lines():
    # A fixed command; no client input or shell evaluation.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ['/usr/bin/docker', 'logs', '--timestamps', '--since', '1h', '--tail', str(MAX_LINES), 'printfilm-prod-api'],
            stdout=output, stderr=subprocess.STDOUT, timeout=10, check=False,
        )
        if result.returncode:
            raise RuntimeError('API log collection failed')
        size = output.tell()
        output.seek(max(0, size - MAX_BYTES))
        lines = output.read(MAX_BYTES).decode('utf-8', errors='replace').splitlines()
        return lines[1:] if size > MAX_BYTES else lines


def nginx_lines(kind):
    suffix = '.ssl.log' if kind == 'access' else '.ssl.error.log'
    result = []
    for domain, label in [('www.printfilm.com', '主站'), ('admin.printfilm.com', '后台')]:
        result.extend(f'[{label}] {line}' for line in tail_file('/www/wwwlogs/' + domain + suffix)[-500:])
    return result


def collect():
    SNAPSHOTS.mkdir(mode=0o750, parents=True, exist_ok=True)
    for source, (label, window) in SOURCES.items():
        try:
            raw = api_lines() if source == 'api' else nginx_lines(source)
            lines = raw[-MAX_LINES:]
            snapshot = {
                'source': source, 'label': label, 'window': window,
                'collected_at': datetime.now(timezone.utc).isoformat(),
                'lines': [{'level': severity(line), 'text': line} for line in lines],
            }
            target = SNAPSHOTS / (source + '.json')
            temporary = target.with_suffix('.tmp')
            with temporary.open('w', encoding='utf-8') as file:
                json.dump(snapshot, file, ensure_ascii=False)
            temporary.chmod(0o640)
            os.replace(temporary, target)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            # Preserve the last good snapshot; the UI explicitly reports its age.
            print('collection_failed source=' + source, flush=True)


if __name__ == '__main__':
    collect()
