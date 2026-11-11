"""Standalone HTTP log viewer with dedicated Basic authentication."""
import base64
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
SNAPSHOTS = Path('/run/printfilm-log-viewer')
SOURCES = frozenset({'api', 'access', 'error'})
STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}
AUTH = None
RATE_LOCK = threading.Lock()
BUCKETS = {}


def authorize(authorization):
    if not AUTH or not authorization.startswith('Basic ') or len(authorization) > 4096:
        return False
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode('utf-8')
        username, password = decoded.split(':', 1)
    except (ValueError, UnicodeError):
        return False
    digest = hashlib.sha256(password.encode()).hexdigest()
    return secrets.compare_digest(username, AUTH['username']) and secrets.compare_digest(digest, AUTH['password_sha256'])


def allow_request(ip):
    now = time.monotonic()
    with RATE_LOCK:
        if len(BUCKETS) > 4096:
            for key, (_, used) in list(BUCKETS.items()):
                if now - used > 60:
                    del BUCKETS[key]
            if len(BUCKETS) > 4096:
                return False
        tokens, last = BUCKETS.get(ip, (20, now))
        tokens = min(20, tokens + (now - last) * 2)
        allowed = tokens >= 1
        BUCKETS[ip] = (tokens - 1 if allowed else tokens, now)
        return allowed


class Handler(BaseHTTPRequestHandler):
    server_version = 'PrintfilmLogViewer'

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, format, *args):
        pass

    def send(self, status, body, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if status == 401:
            self.send_header('WWW-Authenticate', 'Basic realm="PRINTFILM production logs", charset="UTF-8"')
        if status == 429:
            self.send_header('Retry-After', '5')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def error(self, status, message):
        self.send(status, json.dumps({'message': message}, ensure_ascii=False).encode())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not allow_request(self.client_address[0]):
            return self.error(429, '请求过于频繁，请稍后重试')
        if not authorize(self.headers.get('Authorization', '')):
            return self.error(401, '请输入日志访问账号和密码')
        url = urlsplit(self.path)
        if url.path in STATIC:
            name, content_type = STATIC[url.path]
            return self.send(200, (ROOT / name).read_bytes(), content_type)
        if url.path != '/api/logs':
            return self.error(404, '页面不存在')
        params = parse_qs(url.query)
        if set(params) - {'source'}:
            return self.error(400, '不支持的查询参数')
        source = params.get('source', ['api'])
        if len(source) != 1 or source[0] not in SOURCES:
            return self.error(400, '不支持的日志来源')
        try:
            data = (SNAPSHOTS / (source[0] + '.json')).read_bytes()
        except OSError:
            return self.error(503, '日志采集中，请稍后刷新')
        return self.send(200, data)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    slots = threading.BoundedSemaphore(16)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


if __name__ == '__main__':
    credentials = Path(os.environ['CREDENTIALS_DIRECTORY']) / 'auth.json'
    AUTH = json.loads(credentials.read_text())
    assert AUTH.get('username') and len(AUTH.get('password_sha256', '')) == 64
    Server(('0.0.0.0', 8066), Handler).serve_forever()
