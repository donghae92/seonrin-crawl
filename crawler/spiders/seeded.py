import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor

BLOCK_CODES = (401, 403, 429, 451)


class SeededSpider(scrapy.Spider):
    """Reads seeds.txt (one URL per line, # comments). Stays on seed domains."""
    name = "seeded"
    handle_httpstatus_list = list(BLOCK_CODES)

    def __init__(self, seeds="seeds.txt", *a, **kw):
        super().__init__(*a, **kw)
        p = Path(seeds)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / seeds
        self.seed_urls = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                          if l.strip() and not l.strip().startswith("#")]
        self.allowed_domains = sorted({urlparse(u).hostname for u in self.seed_urls if urlparse(u).hostname})
        self.blocked = set()
        self.link_ex = LinkExtractor()  # domain filter is done by hostname below (works with ports too)

    async def start(self):
        if not self.seed_urls:
            self.logger.error("seeds.txt is empty - add URLs first. Nothing collected.")
            return
        for u in self.seed_urls:
            yield scrapy.Request(u, callback=self.parse, cb_kwargs={"depth": 0})

    def parse(self, response, depth=0):
        host = urlparse(response.url).hostname
        if response.status in BLOCK_CODES:
            self.blocked.add(host)  # stop this domain, never work around
            yield {"url": response.url, "status": response.status, "blocked": True,
                   "fetched_at": datetime.now(timezone.utc).isoformat()}
            return
        if not isinstance(response, scrapy.http.TextResponse):
            return
        text = " ".join(t.strip() for t in response.xpath(
            "//body//text()[not(ancestor::script) and not(ancestor::style)]").getall() if t.strip())
        meta = lambda *names: next((response.xpath(f'//meta[@{k}="{n}"]/@content').get()
                                    for n in names for k in ("name", "property")
                                    if response.xpath(f'//meta[@{k}="{n}"]/@content').get()), None)
        yield {
            "url": response.request.url, "final_url": response.url, "status": response.status,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "depth": depth,
            "title": (response.xpath("//title/text()").get() or "").strip(),
            "author": meta("author", "article:author"),
            "published": meta("article:published_time", "date"),
            "lang": response.xpath("//html/@lang").get(),
            "text": text[:20000],
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        if depth < 1:
            for link in self.link_ex.extract_links(response):
                h = urlparse(link.url).hostname
                if h not in self.allowed_domains or h in self.blocked:
                    continue  # seeds only; blocked domain = stop
                yield response.follow(link.url, callback=self.parse, cb_kwargs={"depth": depth + 1})
