"""Shared helpers for the seeded and scout spiders (r3)."""
import gzip, hashlib, json, os, re
from datetime import datetime, timezone
from urllib.parse import urlparse

BLOCK_CODES = (401, 403, 429, 451)
TIER_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}
TEXT_MAX = 20000


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_seed_lines(text):
    """'URL key=value ...' per line, '#' starts a comment. -> [{url, host, origin, opts}]"""
    out = []
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip() if not raw.strip().startswith("#") else ""
        if not line:
            continue
        toks = line.split()
        u = urlparse(toks[0])
        if not u.scheme or not u.hostname:
            continue
        opts = dict(t.split("=", 1) for t in toks[1:] if "=" in t)
        out.append({"url": toks[0], "host": u.netloc, "origin": f"{u.scheme}://{u.netloc}", "opts": opts})
    return out


def choose_urls(entries, mode, cap, slice_idx, since=None):
    """entries: [(loc, lastmod|None)]. recent = newest lastmod first; rotate = a stateless slice
    that moves forward with slice_idx and wraps around. Returns at most `cap` distinct urls."""
    seen, uniq = set(), []
    for loc, lm in entries:
        if loc not in seen:
            seen.add(loc); uniq.append((loc, lm))
    if not uniq or cap <= 0:
        return []
    if mode == "recent" and not since and sum(1 for _, lm in uniq if lm) * 2 < len(uniq):
        mode = "rotate"                      # lastmod missing for most entries: recent would be arbitrary
    if mode == "recent":
        dated = sorted([e for e in uniq if e[1]], key=lambda e: (e[1], e[0]), reverse=True)
        if since:                              # fresh-only run: ISO date strings compare as text; undated pages are not "fresh"
            return [loc for loc, lm in dated if lm[:len(since)] >= since][:cap]
        undated = sorted([e for e in uniq if not e[1]], key=lambda e: e[0])
        return [loc for loc, _ in (dated + undated)[:cap]]
    uniq.sort(key=lambda e: e[0])
    n = len(uniq)
    if n <= cap:
        return [loc for loc, _ in uniq]
    start = (slice_idx * cap) % n
    return [uniq[(start + i) % n][0] for i in range(cap)]


def slice_index(tier, today=None):
    days = TIER_DAYS.get(tier or "", 1)
    d = today or datetime.now(timezone.utc).date()
    return d.toordinal() // days


def gunzip_if_needed(body):
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def extract_page(html, url, xpath_text, meta):
    """Main text via trafilatura (plain xpath text is the automatic fallback). Author/date/title: trafilatura's
    value first, then our own meta/JSON-LD reading. Measured 2026-10-17: trafilatura DROPS Korean author
    names ('홍길동', '행정안전부') - so our own reading is not optional."""
    ex = {"text": xpath_text[:TEXT_MAX], "extractor": "xpath", "author": None, "published": None, "title": None}
    if os.environ.get("R3_NO_TRAFILATURA") != "1":
        try:
            import trafilatura
            js = trafilatura.extract(html, url=url, output_format="json", with_metadata=True,
                                     include_comments=False, include_tables=True, favor_recall=True)
            if js:
                d = json.loads(js)
                text = (d.get("text") or "").strip()
                if len(text) >= 200:
                    ex = {"text": text[:TEXT_MAX], "extractor": "trafilatura", "author": d.get("author"),
                          "published": d.get("date"), "title": d.get("title")}
        except Exception:
            pass
    for k in ("author", "published", "title"):
        ex[k] = ex[k] or meta.get(k)
    return ex


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def top_outlink_hosts(host, urls, n=20):
    cnt = {}
    for u in urls:
        h = urlparse(u).netloc
        if h and h != host:
            cnt[h] = cnt.get(h, 0) + 1
    return ";".join(f"{h}:{c}" for h, c in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[:n])
