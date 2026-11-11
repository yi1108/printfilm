import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import collector
import server

AUTH = {'username': 'logs', 'password_sha256': hashlib.sha256(b'test-password').hexdigest()}
HEADER = 'Basic ' + base64.b64encode(b'logs:test-password').decode()

class CollectorTests(unittest.TestCase):
    def test_original_logs_preserved(self):
        raw = ['GET /api/x?token=original-token user@example.com', 'prompt=original content', '<script>alert(1)</script>']
        with tempfile.TemporaryDirectory() as directory, patch.object(collector,'SNAPSHOTS',Path(directory)), patch.object(collector,'api_lines',return_value=raw), patch.object(collector,'nginx_lines',return_value=[]):
            collector.collect()
            data=json.loads((Path(directory)/'api.json').read_text(encoding='utf-8'))
            self.assertEqual([line['text'] for line in data['lines']],raw)

    def test_failed_collection_preserves_last_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector,'SNAPSHOTS',Path(directory)), patch.object(collector,'api_lines',side_effect=RuntimeError), patch.object(collector,'nginx_lines',return_value=[]):
            path=Path(directory)/'api.json';path.write_text('previous')
            collector.collect();self.assertEqual(path.read_text(),'previous')

    def test_http_error_severity(self):
        self.assertEqual(collector.severity('POST /api/x → 503 (10ms)'),'error')
        self.assertEqual(collector.severity('"GET /api/x HTTP/1.1" 401'),'warning')

class AuthTests(unittest.TestCase):
    def test_authentication_fails_closed(self):
        with patch.object(server,'AUTH',AUTH):
            for value in ['', 'Basic !!!', 'Basic YQ==', 'Bearer invalid', 'Basic '+base64.b64encode(b'logs:wrong').decode()]:
                self.assertFalse(server.authorize(value))
            self.assertTrue(server.authorize(HEADER))
        with patch.object(server,'AUTH',None):self.assertFalse(server.authorize(HEADER))

    def test_rate_limit(self):
        with patch.object(server,'BUCKETS',{}),patch.object(server.time,'monotonic',return_value=1):
            self.assertTrue(all(server.allow_request('test') for _ in range(20)))
            self.assertFalse(server.allow_request('test'))

class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.AUTH=AUTH
        cls.http=server.Server(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()
    def setUp(self):server.BUCKETS.clear()
    def fetch(self,path,auth=True):
        try:
            response=urlopen(Request(self.url+path,headers={'Authorization':HEADER} if auth else {}))
        except HTTPError as error:response=error
        with response:return response.code,response.headers,response.read()
    def test_every_resource_requires_password(self):
        for path in ['/','/app.js','/style.css','/api/logs?source=api']:
            status,headers,_=self.fetch(path,False)
            self.assertEqual(status,401);self.assertIn('Basic',headers['WWW-Authenticate'])
    def test_admin_only_fixed_paths(self):
        for path in ['/api/logs?source=../../etc/passwd','/api/logs?source=api&source=error','/api/logs?file=/etc/passwd']:
            self.assertEqual(self.fetch(path)[0],400)
        self.assertEqual(self.fetch('/server.py')[0],404)
        self.assertEqual(self.fetch('/../../etc/passwd')[0],404)
    def test_authenticated_raw_snapshot(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'SNAPSHOTS',Path(directory)):
            (Path(directory)/'api.json').write_text('{"lines":[{"text":"original"}]}')
            status,headers,body=self.fetch('/api/logs?source=api')
            self.assertEqual(status,200);self.assertEqual(json.loads(body)['lines'][0]['text'],'original')
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])

if __name__=='__main__':unittest.main()
