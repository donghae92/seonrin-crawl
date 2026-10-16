"""Fake kitchen: five tiny sites on loopback aliases. Logs every request to $R3K_LOG (port + path)."""
import gzip, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = os.environ.get("R3K_LOG", "/tmp/r3k/req.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
lock = threading.Lock()
A, B, C, D = 18201, 18202, 18203, 18204


def article(i, tag, links=""):
    body = " ".join(f"이 문장은 {tag} 사이트의 {i}번 글 본문입니다. 소상공인 정책자금과 농어민 복지 제도에 대한 안내를 길게 적어 두었습니다." for _ in range(14))
    return (f'<html lang="ko"><head><title>글 {i} - {tag}</title><meta name="author" content="김철수">'
            f'<meta property="article:published_time" content="2026-10-{10 + i % 10:02d}T09:00:00+09:00"></head>'
            f'<body><nav>메뉴 홈 소개 로그인 사이트맵 검색</nav><article><h1>글 {i}</h1><p>{body}</p></article>'
            f'<footer>저작권 안내 로그인 사이트맵 이용약관</footer>{links}</body></html>').encode()


def a_sitemap():
    rows = ['<url><loc>http://127.0.0.1:%d/private/secret</loc><lastmod>2026-10-30</lastmod></url>' % A]
    rows += ['<url><loc>http://127.0.0.1:%d/a/p%d</loc><lastmod>2026-10-%02d</lastmod></url>' % (A, i, 29 - i) for i in range(30)]
    rows.append('<url><loc>http://127.0.0.1:%d/a/dup</loc><lastmod>2026-09-01</lastmod></url>' % A)
    return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(rows) + "</urlset>").encode()


def c_children():
    one = "".join('<url><loc>http://127.0.0.1:%d/c/p%03d</loc></url>' % (C, i) for i in range(60))
    two = "".join('<url><loc>http://127.0.0.1:%d/c/p%03d</loc></url>' % (C, i) for i in range(60, 100)) + \
          '<url><loc>http://127.0.0.1:%d/c/limited</loc></url>' % C
    w = lambda x: ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + x + "</urlset>").encode()
    return gzip.compress(w(one)), w(two)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def reply(self, code, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        port, path = self.server.server_address[1], self.path.split("?")[0]
        with lock, open(LOG, "a") as f: f.write(f"{port} {path}\n")
        if port == A:
            if path == "/robots.txt": return self.reply(200, f"User-agent: *\nDisallow: /private/\nSitemap: http://127.0.0.1:{A}/sitemap.xml\n".encode(), "text/plain")
            if path == "/sitemap.xml": return self.reply(200, a_sitemap(), "application/xml")
            if path == "/private/secret": return self.reply(200, article(999, "SECRET"))
            if path == "/a/dup": return self.reply(200, article(1, "A", f'<a href="http://127.0.0.1:{C}/">c</a>'))
            if path.startswith("/a/p"): return self.reply(200, article(int(path[4:]), "A", f'<a href="http://127.0.0.1:{C}/">c</a>'))
            return self.reply(200, article(0, "A-root"))
        if port == B:
            if path in ("/robots.txt", "/sitemap.xml"): return self.reply(404)
            if path == "/b/blocked": return self.reply(403, b"no")
            if path.startswith("/b/p"): return self.reply(200, article(int(path[4:]), "B"))
            links = f'<a href="/b/p1">1</a><a href="/b/blocked">x</a>' + "".join(f'<a href="/b/p{i}">{i}</a>' for i in range(2, 20)) + \
                    f'<a href="http://127.0.0.1:{A}/a/p1">a</a><a href="http://127.0.0.1:{C}/c/p001">c</a>'
            return self.reply(200, article(0, "B-root", links))
        if port == C:
            c1, c2 = c_children()
            if path == "/robots.txt": return self.reply(200, f"User-agent: *\nSitemap: http://127.0.0.1:{C}/sm_index.xml\n".encode(), "text/plain")
            if path == "/sm_index.xml":
                return self.reply(200, ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                        f'<sitemap><loc>http://127.0.0.1:{C}/child1.xml.gz</loc></sitemap>'
                                        f'<sitemap><loc>http://127.0.0.1:{C}/child2.xml</loc></sitemap></sitemapindex>').encode(), "application/xml")
            if path == "/child1.xml.gz": return self.reply(200, c1, "application/gzip")
            if path == "/child2.xml": return self.reply(200, c2, "application/xml")
            if path == "/c/limited": return self.reply(429, b"slow down")
            if path.startswith("/c/p"): return self.reply(200, article(int(path[4:]), "C", f'<a href="http://127.0.0.1:{A}/a/p2">a</a>'))
            return self.reply(200, article(0, "C-root", f'<a href="http://127.0.0.1:{A}/a/p3">a</a>'))
        if port == D:
            if path == "/robots.txt": return self.reply(200, b"User-agent: *\nDisallow: /\n", "text/plain")
            return self.reply(200, article(0, "D"))
        self.reply(404)


if __name__ == "__main__":
    servers = [ThreadingHTTPServer(("0.0.0.0", p), H) for p in (A, B, C, D)]
    for s in servers: threading.Thread(target=s.serve_forever, daemon=True).start()
    print("fake sites up", flush=True)
    threading.Event().wait()
