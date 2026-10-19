"""python -m unittest tests.test_landing   (needs scrapy installed; no network - a local fake Worker)"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from twisted.internet import defer

from crawler import pipelines
from crawler.pipelines import LandingPipeline, job_slug, put_batch


class Stats:
    def __init__(self): self.v = {}
    def inc_value(self, k, n=1): self.v[k] = self.v.get(k, 0) + n


def make_server(mode="ok"):
    store = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_PUT(self):
            n = int(self.headers.get("content-length", 0))
            body = self.rfile.read(n)
            key = parse_qs(urlparse(self.path).query)["key"][0]
            if self.headers.get("authorization") != "Bearer good":
                code, out = 401, {"error": "unauthorized"}
            elif mode == "down":
                code, out = 503, {"error": "down"}
            elif key in store:
                code, out = (200, {"ok": True, "duplicate": True}) if store[key] == body else (409, {"error": "x"})
            else:
                store[key] = body
                code, out = 200, {"ok": True, "key": key}
            data = json.dumps(out).encode()
            self.send_response(code); self.send_header("content-length", str(len(data))); self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, store


def sync_runner(fn, *a, **kw):
    try:
        return defer.succeed(fn(*a, **kw))
    except Exception as e:
        return defer.fail(e)


def pipe(srv, token="good", batch=500, stats=None):
    p = LandingPipeline(f"http://127.0.0.1:{srv.server_port}", token, batch, stats or Stats(), "seeded", "daily", "881926-1-5")
    p.runner = staticmethod(sync_runner)
    return p


class LandingTests(unittest.TestCase):
    def setUp(self):
        self._w = pipelines.RETRY_WAITS
        pipelines.RETRY_WAITS = (0, 0, 0)
        put_batch.__defaults__ = (60, (0, 0, 0), lambda s: None)

    def tearDown(self):
        pipelines.RETRY_WAITS = self._w

    def test_batches_and_line_counts(self):
        srv, store = make_server(); st = Stats(); p = pipe(srv, batch=500, stats=st)
        for i in range(1200):
            self.assertEqual(p.process_item({"url": f"https://a/{i}", "text": "한글"})["url"], f"https://a/{i}")
        p.close_spider()
        self.assertEqual(sorted(store), [f"zyte/seeded/daily/881926-1-5/{n:05d}.jsonl" for n in (1, 2, 3)])
        self.assertEqual(sum(len(b.decode().splitlines()) for b in store.values()), 1200)
        self.assertEqual(st.v["land/items_landed"], 1200)
        self.assertEqual(st.v.get("land/failed_batches", 0), 0)
        self.assertIn("한글", list(store.values())[0].decode())           # not escaped to \uXXXX

    def test_empty_run_lands_nothing(self):
        srv, store = make_server(); p = pipe(srv); p.close_spider()
        self.assertEqual(store, {})

    def test_server_down_counts_failure_but_items_pass_through(self):
        srv, store = make_server("down"); st = Stats(); p = pipe(srv, stats=st, batch=2)
        out = [p.process_item({"url": str(i)}) for i in range(4)]
        p.close_spider()
        self.assertEqual(len(out), 4); self.assertEqual(store, {})
        self.assertEqual(st.v["land/failed_batches"], 2); self.assertEqual(st.v["land/items_failed"], 4)

    def test_wrong_token_is_refused_without_retry(self):
        srv, store = make_server()
        with self.assertRaises(RuntimeError) as c:
            put_batch(f"http://127.0.0.1:{srv.server_port}", "bad", "zyte/a/b/c/00001.jsonl", b"{}\n")
        self.assertIn("401", str(c.exception)); self.assertEqual(store, {})

    def test_same_batch_twice_is_duplicate(self):
        srv, store = make_server(); u = f"http://127.0.0.1:{srv.server_port}"
        put_batch(u, "good", "zyte/a/b/c/00001.jsonl", b'{"a":1}\n')
        r = put_batch(u, "good", "zyte/a/b/c/00001.jsonl", b'{"a":1}\n')
        self.assertTrue(r["duplicate"]); self.assertEqual(len(store), 1)

    def test_job_slug(self):
        self.assertEqual(job_slug({"SCRAPY_JOB": "881926/1/5"}), "881926-1-5")
        self.assertTrue(job_slug({}).startswith("local-"))

    def test_off_without_settings(self):
        from scrapy.exceptions import NotConfigured
        from scrapy.settings import Settings
        class C: settings = Settings({}); stats = Stats()
        import os
        for k in ("LAND_URL", "LAND_TOKEN"):
            os.environ.pop(k, None)
        with self.assertRaises(NotConfigured):
            LandingPipeline.from_crawler(C)


if __name__ == "__main__":
    unittest.main()
