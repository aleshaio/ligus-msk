"""Real PHP HTTP endpoint + local SMTP sink. No external messages or dependencies."""
import base64
import email
from email import policy
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PHP = os.environ.get('PHP_BIN') or shutil.which('php') or '/opt/homebrew/opt/php@8.4/bin/php'
SECRET = 'test-secret-never-use-in-production-0123456789'
VALID = dict(name='Тестовый заказчик', phone='+7 977 000 00 00', email='client@example.test', organization='Тестовая организация', comment='Нужны российские ноутбуки', consent='on', _honey='')
PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'

class Sink(socketserver.StreamRequestHandler):
    def handle(self):
        def reply(line):
            self.wfile.write((line + '\r\n').encode()); self.wfile.flush()
        reply('220 local.test SMTP test sink')
        recipients = []
        while raw := self.rfile.readline():
            line = raw.decode('utf-8', errors='replace').strip()
            cmd = line.split(' ', 1)[0].upper()
            if cmd in ('EHLO', 'HELO'):
                reply('250-local.test'); reply('250 SIZE 20000000')
            elif cmd == 'RCPT':
                recipients.append(line); reply('250 OK')
            elif cmd == 'DATA':
                if self.server.fail:
                    reply('451 Test failure'); continue
                reply('354 End with dot')
                body = []
                while (part := self.rfile.readline()) != b'.\r\n':
                    if not part: return
                    body.append(part[1:] if part.startswith(b'..') else part)
                self.server.messages.append((recipients[:], b''.join(body)))
                reply('250 Accepted')
            elif cmd == 'QUIT':
                reply('221 Bye'); return
            elif cmd in ('MAIL', 'RSET', 'NOOP'):
                if cmd == 'RSET': recipients = []
                reply('250 OK')
            else:
                reply('500 Unsupported')

class SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

class Harness:
    def __init__(self, public_source=None, port=0):
        self.temp = tempfile.TemporaryDirectory(prefix='ligus-smtp-test-')
        self.root = Path(self.temp.name)
        self.private = self.root / 'private' / 'contact'
        shutil.copytree(ROOT / 'server' / 'private' / 'contact', self.private,
                        ignore=shutil.ignore_patterns('config.php', 'runtime'))
        shutil.copytree(public_source or ROOT / 'server' / 'public', self.root / 'public_html')
        self.smtp = SMTPServer(('127.0.0.1', 0), Sink)
        self.smtp.messages = []
        self.smtp.fail = False
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port)); self.port = sock.getsockname()[1]
        self.origin = f'http://127.0.0.1:{self.port}'
        self.config = dict(enabled=True, environment='test', site_origin=self.origin, secret=SECRET,
            recipient='tender@example.test', runtime_dir=str(self.private / 'runtime'),
            smtp=dict(host='127.0.0.1', port=self.smtp.server_address[1], encryption='none',
                      username='', password='', from_email='website@example.test', from_name='Лигус'))
        self.write_config()
        self.log = open(self.root / 'php.log', 'w+')
        self.process = subprocess.Popen([PHP, '-d', 'upload_max_filesize=10M', '-d', 'post_max_size=12M',
            '-d', 'max_file_uploads=2', '-d', 'display_errors=0', '-S', f'127.0.0.1:{self.port}', '-t', str(self.root / 'public_html')],
            stdout=self.log, stderr=self.log)
        for _ in range(100):
            if self.process.poll() is not None: raise RuntimeError('PHP failed: ' + (self.root / 'php.log').read_text())
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=.1): break
            except OSError: time.sleep(.05)
        else: raise RuntimeError('PHP server did not start')

    def write_config(self):
        payload = base64.b64encode(json.dumps(self.config, ensure_ascii=False).encode()).decode()
        (self.private / 'config.php').write_text("<?php return json_decode(base64_decode('" + payload + "'), true);")

    def http(self, method='GET', fields=None, attachment=None, origin=None, path='/api/contact.php', raw=None):
        headers = {'Origin': self.origin if origin is None else origin}
        data = raw
        if fields is not None:
            boundary = 'LigusTestBoundary123456789'
            chunks = []
            for key, value in fields.items():
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            if attachment:
                name, content = attachment
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="attachment"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b'\r\n')
            chunks.append(f'--{boundary}--\r\n'.encode())
            data = b''.join(chunks); headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try: response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e: response = e
        content = response.read()
        try: result = json.loads(content)
        except ValueError: result = content
        return response.status, result, response.headers

    def token(self):
        code, body, _ = self.http()
        assert code == 200, body
        return body['token']

    def submit(self, **kwargs):
        fields = dict(VALID, token=kwargs.pop('token', None) or self.token())
        fields.update(kwargs.pop('fields', {}))
        return self.http('POST', fields=fields, **kwargs)

    def close(self):
        self.process.terminate(); self.process.wait(timeout=5)
        self.smtp.shutdown(); self.smtp.server_close(); self.log.close(); self.temp.cleanup()

class ContactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.h = Harness()
    @classmethod
    def tearDownClass(cls): cls.h.close()
    def setUp(self):
        self.h.smtp.messages.clear(); self.h.smtp.fail = False
        self.h.config['enabled'] = True; self.h.config['environment'] = 'test'; self.h.write_config()
        db = self.h.private / 'runtime' / 'state.sqlite'
        if db.exists():
            with sqlite3.connect(db) as conn:
                conn.execute('DELETE FROM events'); conn.execute('DELETE FROM requests')

    def test_plain_message_headers_and_unicode(self):
        code, body, _ = self.h.submit(fields={'recipient': 'attacker@example.test', '_next': 'https://evil.test'})
        self.assertEqual(code, 200, body)
        recipients, raw = self.h.smtp.messages[0]
        self.assertEqual(recipients, ['RCPT TO:<tender@example.test>'])
        message = email.message_from_bytes(raw, policy=policy.default)
        self.assertEqual(message['Reply-To'], 'client@example.test')
        self.assertIn('website@example.test', message['From'])
        self.assertIn(VALID['name'], message.get_content())
        self.assertIn(VALID['comment'], message.get_content())
        self.assertIn('Согласие: отмечено', message.get_content())

    def test_attachment_and_cleanup(self):
        code, body, _ = self.h.submit(attachment=('Задание.pdf', PDF))
        self.assertEqual(code, 200, body)
        message = email.message_from_bytes(self.h.smtp.messages[0][1], policy=policy.default)
        part = next(message.iter_attachments())
        self.assertEqual(part.get_filename(), 'Задание.pdf')
        self.assertEqual(part.get_payload(decode=True), PDF)
        self.assertEqual(list((self.h.private / 'runtime').glob('upload-*')), [])

    def test_office_attachment(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as z:
            z.writestr('[Content_Types].xml', '<Types/>'); z.writestr('word/document.xml', '<document/>')
        self.assertEqual(self.h.submit(attachment=('test.docx', output.getvalue()))[0], 200)

    def test_replay_is_idempotent(self):
        token = self.h.token()
        first = self.h.submit(token=token)
        again = self.h.submit(token=token)
        self.assertEqual(first[:2], again[:2])
        self.assertEqual(len(self.h.smtp.messages), 1)

    def test_invalid_fields(self):
        for changes in [dict(name=''), dict(phone='123'), dict(email='bad'), dict(consent=''), dict(comment='x' * 5001)]:
            with self.subTest(changes=list(changes)):
                self.assertEqual(self.h.submit(fields=changes)[0], 422)
        self.assertEqual(self.h.smtp.messages, [])

    def test_injection_and_array(self):
        self.assertEqual(self.h.submit(fields={'email': 'user@example.test\r\nBcc: other@example.test'})[0], 422)
        fields = dict(VALID, token=self.h.token()); del fields['name']; fields['name[]'] = 'array'
        self.assertEqual(self.h.http('POST', fields=fields)[0], 422)
        self.assertEqual(self.h.smtp.messages, [])

    def test_bad_origin_and_methods(self):
        token = self.h.token()
        self.assertEqual(self.h.submit(token=token, origin='https://evil.test')[0], 403)
        self.assertEqual(self.h.submit(token=token, origin='')[0], 403)
        self.assertEqual(self.h.http('PUT')[0], 405)
        self.assertEqual(self.h.smtp.messages, [])

    def test_invalid_and_expired_token(self):
        self.assertEqual(self.h.submit(token='forged')[0], 403)
        payload = f'{int(time.time()) - 4000}.' + 'a' * 32
        peer = hmac.new(SECRET.encode(), b'127.0.0.1', hashlib.sha256).hexdigest()
        signature = hmac.new(SECRET.encode(), (payload + '.' + peer).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(self.h.submit(token=payload + '.' + signature)[0], 403)
        self.assertEqual(self.h.smtp.messages, [])

    def test_honeypot(self):
        self.assertEqual(self.h.submit(fields={'_honey': 'bot'})[0], 422)
        self.assertEqual(self.h.smtp.messages, [])

    def test_file_validation(self):
        for filename, content in [('x.php', b'<?php echo 1;'), ('x.pdf', b'not a PDF'), ('x.docx', b'not ZIP'), ('x.txt', b'\x00\x01\x02')]:
            with self.subTest(filename=filename):
                self.assertEqual(self.h.submit(attachment=(filename, content))[0], 422)
        self.assertEqual(self.h.smtp.messages, [])

    def test_oversize_file_and_body(self):
        self.assertEqual(self.h.submit(attachment=('big.pdf', PDF + b'x' * (10 * 1024 * 1024)))[0], 413)
        self.assertEqual(self.h.http('POST', raw=b'x' * (13 * 1024 * 1024))[0], 413)
        self.assertEqual(self.h.smtp.messages, [])

    def test_limits(self):
        for _ in range(5): self.assertEqual(self.h.submit(fields={'phone': 'bad'})[0], 422)
        code, _, headers = self.h.submit()
        self.assertEqual(code, 429); self.assertEqual(headers['Retry-After'], '600')

    def test_smtp_failure_no_false_success_and_cleanup(self):
        self.h.smtp.fail = True
        token = self.h.token()
        self.assertEqual(self.h.submit(token=token, attachment=('test.pdf', PDF))[0], 502)
        self.assertEqual(self.h.submit(token=token)[0], 409)
        self.assertEqual(self.h.smtp.messages, [])
        self.assertEqual(list((self.h.private / 'runtime').glob('upload-*')), [])

    def test_disabled_missing_and_unsafe_config(self):
        self.h.config['enabled'] = False; self.h.write_config()
        self.assertEqual(self.h.http()[0], 503)
        (self.h.private / 'config.php').unlink()
        self.assertEqual(self.h.http()[0], 503)
        self.h.config['enabled'] = True; self.h.config['environment'] = 'production'; self.h.write_config()
        self.assertEqual(self.h.http()[0], 503)
        self.assertEqual(self.h.smtp.messages, [])

    def test_state_redaction_private_files_and_headers(self):
        code, _, headers = self.h.submit()
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIsNone(headers.get('Set-Cookie'))
        self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
        with sqlite3.connect(self.h.private / 'runtime' / 'state.sqlite') as conn:
            state = str(conn.execute('SELECT * FROM events').fetchall()) + str(conn.execute('SELECT * FROM requests').fetchall())
        for value in [VALID['name'], VALID['email'], VALID['phone'], VALID['comment'], '127.0.0.1']:
            self.assertNotIn(value, state)
        self.assertEqual(self.h.http(path='/private/contact/config.php')[0], 404)
        self.assertNotIn(SECRET, (self.h.root / 'php.log').read_text())
        self.assertNotIn(VALID['comment'], (self.h.root / 'php.log').read_text())

    def test_maintenance(self):
        self.h.token()
        runtime = self.h.private / 'runtime'
        old = runtime / 'upload-old'; old.write_bytes(b'old upload'); os.utime(old, (time.time() - 7200,) * 2)
        with sqlite3.connect(runtime / 'state.sqlite') as conn:
            conn.execute('INSERT INTO events VALUES (?, ?, ?)', (time.time() - 8000, 'old', 'hash'))
        subprocess.run([PHP, str(self.h.private / 'check.php')], cwd=self.h.root, check=True, capture_output=True)
        subprocess.run([PHP, str(self.h.private / 'maintenance.php')], cwd=self.h.root, check=True, capture_output=True)
        self.assertFalse(old.exists())
        with sqlite3.connect(runtime / 'state.sqlite') as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM events WHERE kind='old'").fetchone()[0], 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
