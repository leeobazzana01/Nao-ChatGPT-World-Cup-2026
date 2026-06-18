#simulating calls to the real HTTP server (starts it on a temporary port)
#run python3 tests/test_api.py

import sys
import os
import pathlib
import threading
import time
import json
import io
import uuid
import unittest
import http.client

#add the project root to this path
_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

#you must configure the test .env BEFORE importing config
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-testing")
os.environ.setdefault("PORT", "18080")
os.environ.setdefault("AUTH_TOKEN", "change-this-auth-token")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("KNOWLEDGE_DIR", str(_ROOT / "data" / "knowledge"))
os.environ.setdefault("SESSIONS_DIR", str(_ROOT / "data" / "sessions"))

#unit tests for the componentes                                      
class TestMultipartParser(unittest.TestCase):
    #tests the multipart form-data parser

    def _build_multipart(self, boundary: str, parts: list[tuple]) -> bytes:
        buf = io.BytesIO()
        for name, value, content_type, filename in parts:
            buf.write(f"--{boundary}\r\n".encode())
            if filename:
                buf.write(
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
                )
                buf.write(f"Content-Type: {content_type}\r\n\r\n".encode())
                buf.write(value if isinstance(value, bytes) else value.encode())
            else:
                buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
                buf.write(value.encode() if isinstance(value, str) else value)
            buf.write(b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        return buf.getvalue()

    def test_parse_text_field(self):
        from app.utils.multipart import parse
        boundary = "testboundary123"
        #accent test for UTF handling
        body = self._build_multipart(boundary, [
            ("message", "Olá robô", "text/plain", None),
        ])
        result = parse(body, f"multipart/form-data; boundary={boundary}")
        self.assertEqual(result.get_field("message"), "Olá robô")

    def test_parse_audio_file(self):
        from app.utils.multipart import parse
        boundary = "testboundary456"
        fake_audio = b"FAKE_OGG_DATA_" * 100
        body = self._build_multipart(boundary, [
            ("audio", fake_audio, "audio/ogg", "recording.ogg"),
        ])
        result = parse(body, f"multipart/form-data; boundary={boundary}")
        f = result.get_file("audio")
        self.assertIsNotNone(f)
        self.assertEqual(f.filename, "recording.ogg")
        self.assertEqual(f.data, fake_audio)
        self.assertEqual(f.size, len(fake_audio))

    def test_parse_both_fields(self):
        from app.utils.multipart import parse
        boundary = "testboundary789"
        audio_data = b"FAKE_AUDIO"
        photo_data = b"FAKE_JPEG\xff\xd8\xff"
        body = self._build_multipart(boundary, [
            ("audio", audio_data, "audio/ogg", "recording.ogg"),
            ("photo", photo_data, "image/jpeg", "image.jpg"),
        ])
        result = parse(body, f"multipart/form-data; boundary={boundary}")
        self.assertIsNotNone(result.get_file("audio"))
        self.assertIsNotNone(result.get_file("photo"))
        self.assertEqual(result.get_file("audio").data, audio_data)

    def test_missing_boundary(self):
        from app.utils.multipart import parse, MultipartParseError
        with self.assertRaises(MultipartParseError):
            parse(b"some body", "multipart/form-data")

    def test_empty_body(self):
        from app.utils.multipart import parse
        result = parse(b"--testboundary--\r\n", "multipart/form-data; boundary=testboundary")
        self.assertEqual(result.fields, {})
        self.assertEqual(result.files, {})


class TestKnowledgeBase(unittest.TestCase):
    #testing the rag engine
    def setUp(self):
        import tempfile
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        #creating test knowledge files
        (self.tmpdir / "info.txt").write_text(
            "O robô NAO é fabricado pela SoftBank Robotics.\n"
            "O NAO possui sensores de toque na cabeça e nas mãos.\n"
            "A câmera do NAO pode capturar fotos em alta resolução.\n\n"
            "O NAO usa o framework NAOqi para programação.\n"
            "Choregraphe é a IDE visual para criar comportamentos do NAO.",
            encoding="utf-8"
        )
        (self.tmpdir / "faq.txt").write_text(
            "Pergunta: Como o robô se move?\n"
            "Resposta: O NAO usa servomotores nas articulações para se mover.\n\n"
            "Pergunta: Quantos microfones o NAO tem?\n"
            "Resposta: O NAO possui 4 microfones para captura de áudio 360 graus.",
            encoding="utf-8"
        )

    def test_load(self):
        from app.services.knowledge import KnowledgeBase
        kb = KnowledgeBase(self.tmpdir, chunk_size=300)
        n = kb.load()
        self.assertGreater(n, 0)
        self.assertTrue(kb.is_loaded)

    def test_search_relevance(self):
        from app.services.knowledge import KnowledgeBase
        kb = KnowledgeBase(self.tmpdir, chunk_size=300)
        kb.load()

        results = kb.search("microfone áudio", top_k=3)
        self.assertGreater(len(results), 0)
        # The most relevant result must have score > 0
        self.assertGreater(results[0][0], 0)

    def test_search_returns_relevant_chunk(self):
        from app.services.knowledge import KnowledgeBase
        kb = KnowledgeBase(self.tmpdir, chunk_size=500)
        kb.load()

        results = kb.search("câmera foto resolução", top_k=5)
        combined = " ".join(c for _, c in results).lower()
        self.assertIn("câmera", combined)

    def test_format_context(self):
        from app.services.knowledge import KnowledgeBase
        kb = KnowledgeBase(self.tmpdir, chunk_size=300)
        kb.load()

        ctx = kb.format_context("NAO microfone", top_k=3)
        self.assertIn("Relevant Knowledge", ctx)

    def test_empty_dir(self):
        import tempfile
        empty_dir = pathlib.Path(tempfile.mkdtemp())
        from app.services.knowledge import KnowledgeBase
        kb = KnowledgeBase(empty_dir)
        n = kb.load()
        self.assertEqual(n, 0)
        results = kb.search("anything")
        self.assertEqual(results, [])


class TestSessionManager(unittest.TestCase):
    #tests session management

    def setUp(self):
        import tempfile
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())

    def test_empty_session(self):
        from app.services.sessions import SessionManager
        sm = SessionManager(self.tmpdir, ttl_seconds=3600)
        history = sm.get_history("nonexistent-id")
        self.assertEqual(history, [])

    def test_append_and_retrieve(self):
        from app.services.sessions import SessionManager
        sm = SessionManager(self.tmpdir, ttl_seconds=3600)
        cid = str(uuid.uuid4())
        sm.append_messages(cid, "TestBot", [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ])
        history = sm.get_history(cid)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "Hello")

    def test_max_history_limit(self):
        from app.services.sessions import SessionManager
        sm = SessionManager(self.tmpdir, ttl_seconds=3600, max_history=4)
        cid = str(uuid.uuid4())
        for i in range(10):
            sm.append_messages(cid, "Bot", [{"role": "user", "content": f"msg {i}"}])
        history = sm.get_history(cid)
        self.assertLessEqual(len(history), 4)

    def test_deduplication(self):
        from app.services.sessions import SessionManager
        sm = SessionManager(self.tmpdir)
        cid = str(uuid.uuid4())
        sm.mark_request(cid, "hash123")
        self.assertTrue(sm.is_duplicate(cid, "hash123"))
        self.assertFalse(sm.is_duplicate(cid, "hash456"))

    def test_clear(self):
        from app.services.sessions import SessionManager
        sm = SessionManager(self.tmpdir)
        cid = str(uuid.uuid4())
        sm.append_messages(cid, "Bot", [{"role": "user", "content": "test"}])
        sm.clear(cid)
        history = sm.get_history(cid)
        self.assertEqual(history, [])

    def test_persistence(self):
        from app.services.sessions import SessionManager
        cid = str(uuid.uuid4())
        sm1 = SessionManager(self.tmpdir)
        sm1.append_messages(cid, "Bot", [{"role": "user", "content": "persisted"}])
        # New instance, same files
        sm2 = SessionManager(self.tmpdir)
        history = sm2.get_history(cid)
        self.assertEqual(history[0]["content"], "persisted")


class TestRateLimiter(unittest.TestCase):
    #tests rates limiter

    def test_allows_within_limit(self):
        from app.utils.rate_limiter import RateLimiter
        rl = RateLimiter(max_calls=5, window_seconds=60)
        for _ in range(5):
            self.assertTrue(rl.allow("testkey"))

    def test_blocks_above_limit(self):
        from app.utils.rate_limiter import RateLimiter
        rl = RateLimiter(max_calls=3, window_seconds=60)
        for _ in range(3):
            rl.allow("k")
        self.assertFalse(rl.allow("k"))

    def test_different_keys_independent(self):
        from app.utils.rate_limiter import RateLimiter
        rl = RateLimiter(max_calls=2, window_seconds=60)
        rl.allow("a"); rl.allow("a")
        self.assertFalse(rl.allow("a"))
        self.assertTrue(rl.allow("b"))  # "b" is unaffected

    def test_window_expires(self):
        from app.utils.rate_limiter import RateLimiter
        rl = RateLimiter(max_calls=2, window_seconds=1)
        rl.allow("x"); rl.allow("x")
        self.assertFalse(rl.allow("x"))
        time.sleep(1.1)
        self.assertTrue(rl.allow("x"))


class TestCleanForSpeech(unittest.TestCase):
    #tests the text cleanup for TTS 

    def test_removes_markdown(self):
        from app.services.chat import _clean_for_speech
        text = "# Title\n**bold** and _italic_"
        result = _clean_for_speech(text)
        self.assertNotIn("#", result)
        self.assertNotIn("**", result)
        self.assertIn("bold", result)

    def test_removes_urls(self):
        from app.services.chat import _clean_for_speech
        text = "See https://example.com/page for more details."
        result = _clean_for_speech(text)
        self.assertNotIn("https://", result)
        self.assertIn("details", result)

    def test_normalizes_newlines(self):
        from app.services.chat import _clean_for_speech
        text = "First sentence.\n\nSecond sentence.\n\nThird."
        result = _clean_for_speech(text)
        self.assertNotIn("\n\n", result)

class TestHTTPIntegration(unittest.TestCase):
    #HTTP integration tests (real server on a temporary port)

    @classmethod
    def setUpClass(cls):
        #starting the server in a background task
        import app.config as config
        from app.server import NaoAPIServer, _ThreadedServer, _Handler

        os.environ["PORT"] = "18081"
        os.environ["OPENAI_API_KEY"] = "sk-test-INVALID"

        cls.port = 18081
        cls.token = "change-this-auth-token"

        #instanting the server without calling OpenAI (HTTP-only test)
        cls.nao_server = NaoAPIServer()
        cls.nao_server.knowledge.load()  #load KB (may be empty)

        cls.httpd = _ThreadedServer(("127.0.0.1", cls.port), _Handler, cls.nao_server)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)  #waiting for the server to come up

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _conn(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)

    def _get(self, path: str) -> tuple[int, bytes]:
        conn = self._conn()
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()

    def _post_multipart(self, path: str, token: str,
                        audio: bytes = None, photo: bytes = None) -> tuple[int, bytes]:
        boundary = "testboundary" + uuid.uuid4().hex[:8]
        body = b""
        if audio:
            body += f"--{boundary}\r\n".encode()
            body += b'Content-Disposition: form-data; name="audio"; filename="recording.ogg"\r\n'
            body += b"Content-Type: audio/ogg\r\n\r\n"
            body += audio + b"\r\n"
        if photo:
            body += f"--{boundary}\r\n".encode()
            body += b'Content-Disposition: form-data; name="photo"; filename="image.jpg"\r\n'
            body += b"Content-Type: image/jpeg\r\n\r\n"
            body += photo + b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        conn = self._conn()
        conn.request("POST", path, body=body, headers={
            "Authorization": token,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        return resp.status, resp.read()

    #health tests
    def test_health_endpoint(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertIn("uptime_seconds", data)

    def test_status_endpoint(self):
        status, body = self._get("/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("config", data)
        self.assertIn("sessions", data)

    def test_dashboard_returns_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"NAO", body)

    def test_not_found(self):
        status, _ = self._get("/nonexistent-route")
        self.assertEqual(status, 404)

    #authentication tests
    def test_invalid_token_returns_401(self):
        path = "/speech/id/test-id/culture/en-GB/raw/false/persona/Bot/responselength/short/ai-version/gpt-4o"
        status, body = self._post_multipart(path, "WRONG_TOKEN", audio=b"AUDIO")
        self.assertEqual(status, 401)

    def test_valid_token_accepted(self):
        #with a valid token but no real audio -> whisper will fail invalid OpenAI key but 401 error stats may no appear
        path = "/speech/id/test-id/culture/en-GB/raw/false/persona/Bot/responselength/short/ai-version/gpt-4o"
        status, _ = self._post_multipart(path, self.token, audio=b"NOT_REAL_OGG")
        self.assertNotEqual(status, 401)

    #rate limiting tests
    def test_rate_limit_triggers(self):
        #sending 35 fast requests
        path = "/speech/id/rl-test/culture/en-GB/raw/false/persona/Bot/responselength/short/ai-version/gpt-4o"
        statuses = []
        for _ in range(35):
            try:
                s, _ = self._post_multipart(path, self.token, audio=b"X")
                statuses.append(s)
            except Exception:
                break
        self.assertIn(429, statuses)

    #route validanting tests 
    def test_options_cors(self):
        conn = self._conn()
        conn.request("OPTIONS", "/speech/id/x/culture/en/raw/false/persona/Bot/responselength/short/ai-version/gpt-4o")
        resp = conn.getresponse()
        self.assertIn(resp.status, (200, 204))

    def test_no_files_returns_400(self):
        path = "/speech/id/test/culture/en-GB/raw/false/persona/Bot/responselength/short/ai-version/gpt-4o"
        #send an empty  multipart
        boundary = "emptyboundary"
        body = f"--{boundary}--\r\n".encode()
        conn = self._conn()
        conn.request("POST", path, body=body, headers={
            "Authorization": self.token,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        })
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)


#entry point                                                        
def run_tests():
    print("\n" + "="*60)
    print("  NAO API — Test Suite")
    print("="*60 + "\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    #unit tests with no network needed
    suite.addTests(loader.loadTestsFromTestCase(TestMultipartParser))
    suite.addTests(loader.loadTestsFromTestCase(TestKnowledgeBase))
    suite.addTests(loader.loadTestsFromTestCase(TestSessionManager))
    suite.addTests(loader.loadTestsFromTestCase(TestRateLimiter))
    suite.addTests(loader.loadTestsFromTestCase(TestCleanForSpeech))

    #http integration
    suite.addTests(loader.loadTestsFromTestCase(TestHTTPIntegration))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("\n" + "="*60)
    if result.wasSuccessful():
        print("  ✅ All tests passed!")
    else:
        print(f"  ❌ {len(result.failures)} failures, {len(result.errors)} errors")
    print("="*60 + "\n")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
