import os, re, sys, unittest
from datetime import date
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
from crawler.common import choose_urls, extract_page, parse_seed_lines, slice_index, top_outlink_hosts
from to_index_spec import convert, load_spec, trace_priority

SPEC_DIR = os.environ.get("INDEX_SPEC") or os.path.expanduser("~/index-spec")
HAVE_SPEC = os.path.isfile(os.path.join(SPEC_DIR, "index_spec_ref.py"))


class Units(unittest.TestCase):
    def test_seed_lines(self):
        s = parse_seed_lines("# c\n\nhttps://a.kr/x cap=5 mode=recent  # note\nnot a url\nhttp://b.kr:8080/ \n")
        self.assertEqual([x["host"] for x in s], ["a.kr", "b.kr:8080"])   # site key = host:port
        self.assertEqual(s[0]["opts"], {"cap": "5", "mode": "recent"})
        self.assertEqual(s[1]["origin"], "http://b.kr:8080")

    def test_recent_prefers_newest_lastmod(self):
        e = [(f"u{i}", f"2026-10-{i:02d}") for i in range(1, 11)] + [("none", None)]
        self.assertEqual(choose_urls(e, "recent", 3, 0), ["u10", "u9", "u8"])

    def test_recent_without_lastmod_becomes_rotate(self):
        e = [(f"u{i:02d}", None) for i in range(10)]
        self.assertEqual(choose_urls(e, "recent", 3, 1), ["u03", "u04", "u05"])

    def test_rotate_slices_are_disjoint_and_wrap(self):
        e = [(f"u{i:02d}", None) for i in range(10)]
        s0, s1, s3 = (choose_urls(e, "rotate", 3, k) for k in (0, 1, 3))
        self.assertTrue(set(s0).isdisjoint(s1))
        self.assertEqual(s3, ["u09", "u00", "u01"])            # wraps around, still 3 distinct
        self.assertEqual(len(choose_urls(e, "rotate", 20, 7)), 10)

    def test_since_keeps_only_fresh_dated_entries(self):
        e = [("u1", "2026-10-01"), ("u2", "2026-10-18T03:00:00Z"), ("u3", None), ("u4", "2026-10-19")]
        self.assertEqual(choose_urls(e, "recent", 10, 0, "2026-10-18"), ["u4", "u2"])
        self.assertEqual(choose_urls(e, "recent", 1, 0, "2026-10-18"), ["u4"])
        self.assertEqual(choose_urls(e, "recent", 10, 0, "2026-10-25"), [])

    def test_since_does_not_turn_sparse_lastmod_into_rotate(self):
        e = [("u%d" % i, None) for i in range(9)] + [("v", "2026-10-19")]
        self.assertEqual(choose_urls(e, "recent", 5, 0, "2026-10-19"), ["v"])

    def test_slice_index_moves_with_tier_period(self):
        d = date(2026, 10, 17)
        self.assertEqual(slice_index("daily", d), d.toordinal())
        self.assertEqual(slice_index("weekly", d), d.toordinal() // 7)
        self.assertEqual(slice_index("monthly", d), d.toordinal() // 30)

    def test_extract_falls_back_when_forced(self):
        os.environ["R3_NO_TRAFILATURA"] = "1"
        try:
            r = extract_page("<html></html>", "http://x/", "plain text", {"author": "a", "published": "d", "title": "t"})
        finally:
            del os.environ["R3_NO_TRAFILATURA"]
        self.assertEqual((r["extractor"], r["text"], r["author"]), ("xpath", "plain text", "a"))

    def test_extract_trafilatura_drops_menu_and_keeps_meta(self):
        body = " ".join(f"본문 문장 {i}번입니다. 소상공인 정책자금 안내를 적었습니다." for i in range(30))
        html = ('<html lang="ko"><head><title>T</title><meta name="author" content="홍길동">'
                '<meta property="article:published_time" content="2026-10-12T09:00:00+09:00"></head><body>'
                f'<nav>메뉴 로그인 사이트맵</nav><article><p>{body}</p></article><footer>이용약관 로그인</footer></body></html>')
        r = extract_page(html, "http://x/p", "FALLBACK", {"author": "홍길동"})   # our meta reading fills what trafilatura drops
        if r["extractor"] == "trafilatura":
            self.assertNotIn("사이트맵", r["text"]); self.assertEqual(r["author"], "홍길동"); self.assertTrue(r["published"].startswith("2026-10-12"))
        else:
            self.skipTest("trafilatura not importable here (fallback path is covered by the forced test)")

    def test_outlinks(self):
        self.assertEqual(top_outlink_hosts("a.kr", ["http://a.kr/1", "http://b.kr/x", "http://b.kr/y", "http://c.kr/"]), "b.kr:2;c.kr:1")

    def test_chunk_rules(self):
        text = ("가나다라마바사 아자차카타파하다. " * 200)
        if not HAVE_SPEC:
            self.skipTest("~/index-spec not found")
        spec = load_spec(SPEC_DIR)
        ps = spec.chunk_text(text)
        self.assertTrue(len(ps) > 1 and all(40 <= len(p) <= 800 for p in ps))
        self.assertEqual(spec.chunk_text("짧다"), [])

    def test_convert_matches_spec_schemas(self):
        if not HAVE_SPEC:
            self.skipTest("~/index-spec not found")
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        import json
        spec = load_spec(SPEC_DIR)
        S = json.load(open(os.path.join(SPEC_DIR, "schemas.json"), encoding="utf-8"))
        long = "공식 안내 문장입니다. " * 60
        rows = [{"url": "https://a.go.kr/1", "host": "a.go.kr", "status": 200, "text": long, "author": "기관", "published": "2026-10-01", "fetched_at": "2026-10-16T18:53:27+00:00", "lang": "ko"},
                {"url": "https://a.go.kr/2", "host": "a.go.kr", "status": 200, "text": long},
                {"url": "https://b.com/3", "host": "b.com", "status": 403, "blocked": True},
                {"url": "https://b.com/4", "host": "b.com", "status": None, "error": "boom"},
                {"url": "https://b.com/5", "host": "b.com", "status": 200, "text": "x"},
                {"url": "https://nocat.kr/6", "host": "nocat.kr", "status": 200, "text": long + "다른 내용 " * 40}]
        docs, ps, lex, rej, prio = convert(rows, spec, {"a.go.kr": "life.consumer", "b.com": "life.consumer"})
        self.assertEqual(len(docs), 1)
        self.assertEqual(sorted(r["reason"] for r in rej), ["blocked", "duplicate", "empty", "fetch_fail", "seed_out"])
        for kind, recs in (("doc", docs), ("passage", ps), ("lexical", lex), ("rejected", rej)):
            for r in recs:
                jsonschema.validate(r, S[kind])
        self.assertEqual(docs[0]["fetched_at"], "2026-10-17T03:53:27+09:00")
        self.assertEqual(prio[docs[0]["doc_id"]], 3)
        self.assertEqual(trace_priority("b.com", None, None), 0)

    def test_tier_files_load_without_network(self):
        from crawler.spiders.seeded import SeededSpider
        self.assertEqual(len(SeededSpider(tier="daily").doms), 11)
        self.assertEqual(len(SeededSpider(tier="all").doms), 11 + 17 + 6)
        self.assertEqual(len(SeededSpider(tier="weekly", cap="7").doms["finviz.com"].__dict__) > 0, True)
        self.assertEqual(SeededSpider(tier="weekly", cap="7").doms["finviz.com"].cap, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
