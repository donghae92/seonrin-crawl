import pkgutil
from pathlib import Path
from urllib.parse import urlparse

import scrapy
from protego import Protego
from scrapy.linkextractors import LinkExtractor
from scrapy.utils.sitemap import sitemap_urls_from_robots

from crawler.common import BLOCK_CODES, extract_page, now_iso, parse_seed_lines


class ScoutSpider(scrapy.Spider):
    """Candidate check from the SAME network the collector uses: robots, reachability, readable text.
    At most 3 pages per candidate. robots.txt is evaluated by us (so a denial becomes a visible row);
    a denied page is never requested."""
    name = "scout"
    handle_httpstatus_list = list(range(400, 600))
    custom_settings = {"ROBOTSTXT_OBEY": False, "CLOSESPIDER_PAGECOUNT": 3000}

    def __init__(self, candidates=None, hosts=None, pages=3, *a, **kw):
        super().__init__(*a, **kw)
        # hosts="a.kr,https://b.kr/x" lets a job carry its own list (no redeploy); file/packaged list otherwise
        text = "\n".join(hosts.split(",")) if hosts else Path(candidates).read_text(encoding="utf-8") if candidates else \
            pkgutil.get_data("crawler", "candidates.txt").decode("utf-8")
        lines = [l if "://" in l.split()[0] else "https://" + l for l in
                 (x.strip() for x in text.splitlines()) if l and not l.startswith("#")] if text.strip() else []
        self.cands = {}
        for sd in parse_seed_lines("\n".join(lines)):
            self.cands.setdefault(sd["host"], {**sd, "rp": None, "n": 0, "sm": 0, "robots": "?"})
        self.max_pages = int(pages)
        self.ua = None
        self.link_ex = LinkExtractor()

    async def start(self):
        self.ua = self.settings.get("USER_AGENT")
        for c in self.cands.values():
            yield scrapy.Request(c["origin"] + "/robots.txt", callback=self.on_robots, errback=self.on_err,
                                 meta={"host": c["host"], "dont_obey_robots": True}, dont_filter=True)

    def on_robots(self, response):
        c = self.cands[response.meta["host"]]
        txt = response.text if response.status == 200 else ""
        c["rp"] = Protego.parse(txt)
        c["sm"] = len(list(sitemap_urls_from_robots(txt, base_url=response.url))) if txt else 0
        c["robots"] = f"http{response.status}"
        if not c["rp"].can_fetch(c["url"], self.ua):
            yield {"host": c["host"], "url": c["url"], "status": None, "robots": "denied", "sitemap_n": c["sm"],
                   "fetched_at": now_iso()}
            return
        c["n"] = 1
        yield scrapy.Request(c["url"], callback=self.on_page, errback=self.on_err, meta={"host": c["host"]})

    def on_page(self, response):
        c = self.cands[response.meta["host"]]
        row = {"host": c["host"], "url": response.request.url, "status": response.status, "robots": "allowed",
               "robots_http": c["robots"], "sitemap_n": c["sm"], "fetched_at": now_iso()}
        if response.status in BLOCK_CODES:
            yield {**row, "blocked": True}; return
        if response.status >= 400 or not isinstance(response, scrapy.http.TextResponse):
            yield {**row, "error": f"http {response.status}"}; return
        xp = " ".join(t.strip() for t in response.xpath(
            "//body//text()[not(ancestor::script) and not(ancestor::style)]").getall() if t.strip())
        ex = extract_page(response.text, response.url, xp, {})
        yield {**row, "readable_chars": len(ex["text"]), "extractor": ex["extractor"],
               "lang": response.xpath("//html/@lang").get(), "title": (response.xpath("//title/text()").get() or "").strip()}
        if c["n"] < self.max_pages:
            for l in self.link_ex.extract_links(response):
                if c["n"] >= self.max_pages:
                    break
                u = l.url.split("#")[0]
                if urlparse(u).netloc == c["host"] and u != c["url"] and c["rp"].can_fetch(u, self.ua):
                    c["n"] += 1
                    yield scrapy.Request(u, callback=self.on_page, errback=self.on_err, meta={"host": c["host"]})

    def on_err(self, failure):
        h = failure.request.meta.get("host")
        yield {"host": h, "url": failure.request.url, "status": None, "robots": "?", "fetched_at": now_iso(),
               "error": f"unreachable: {failure.value.__class__.__name__}"}
