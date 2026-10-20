import json
import pkgutil
import re
from pathlib import Path
from urllib.parse import urlparse

import scrapy
from scrapy.exceptions import IgnoreRequest
from scrapy.linkextractors import LinkExtractor
from scrapy.utils.sitemap import Sitemap, sitemap_urls_from_robots

from crawler.common import (BLOCK_CODES, TIER_DAYS, choose_urls, content_hash, extract_page, gunzip_if_needed,
                            now_iso, parse_seed_lines, slice_index, top_outlink_hosts)


SM_DEAD_RUN = 10                                   # this many 4xx/5xx in a row from a site's sitemap pages = the sitemap is stale, stop fetching them
SM_KIDS, SM_MAX, ENTRIES_MAX = 15, 20, 200000   # sitemap-index children read per level / per site, entries kept per site


class SkipDeadSitemap:
    """Downloader middleware: drop queued sitemap pages of a site whose sitemap went stale (see SM_DEAD_RUN)."""
    def process_request(self, request, spider):
        d = getattr(spider, "doms", {}).get(request.meta.get("dom"))
        if d is not None and d.skip and request.meta.get("src") == "sitemap":
            raise IgnoreRequest("stale sitemap skipped: " + d.host)


class Dom:
    def __init__(self, seed):
        self.host, self.origin, self.seed_url = seed["host"], seed["origin"], seed["url"]
        o = seed["opts"]
        self.cap = int(o.get("cap", 40))
        self.mode = o.get("mode", "auto")          # auto | recent | rotate | links
        self.sched = 0                             # page requests scheduled so far (strict cap counts HERE)
        self.entries, self.pending, self.sm_seen = [], 0, 0
        self.blocked = self.dead = False
        self.bad_streak, self.skip = 0, False       # consecutive sitemap pages that came back 4xx/5xx; skip = stop fetching this site's sitemap pages
        self.seen = set()                          # link URLs already scheduled (a repeated link must not eat the cap)


class SeededSpider(scrapy.Spider):
    """Reads seeds_<tier>.txt. Per site: sitemap (recent / rotating slice) else one level of links.
    Never leaves the seed host. Hard cap on scheduled pages per site. Block or error = stop, record it.
    Run arguments (all optional, so a controller can steer without a redeploy):
      since=YYYY-MM-DD  recent mode keeps only sitemap entries modified on/after that day (fresh-only run)
      mode=rotate       force sitemap rotation on every site whose seed mode is not "links" (backfill run)
      slice=N           rotation cursor (the controller increments it, so consecutive runs cover consecutive windows)
      max_depth=N       link-following depth for links-mode sites (default 3), shallowest pages first"""
    name = "seeded"
    handle_httpstatus_list = list(range(400, 600))   # 3xx must stay with the redirect middleware

    def __init__(self, seeds=None, tier="all", slice=None, cap=None, since=None, mode=None, max_depth=3,
                 seedlines=None, lesson=None, *a, **kw):
        super().__init__(*a, **kw)
        self.since = since or None
        self.max_depth = int(max_depth)
        # curriculum lesson (tools/zyte_curriculum.py): the job carries its own places as "URL key=value" lines joined by "|",
        # and a lesson name that gives its landing folder (zyte/seeded/lesson-<name>/<job>/)
        self.label = ("lesson-" + re.sub(r"[^A-Za-z0-9._-]", "-", str(lesson))[:40]) if lesson else None
        if seedlines:
            text = "\n".join(seedlines.split("|"))
            self.tier = tier if tier in TIER_DAYS else "daily"
        elif seeds:
            text = Path(seeds).read_text(encoding="utf-8")
            self.tier = tier if tier in TIER_DAYS else "daily"
        else:
            tiers = list(TIER_DAYS) if tier == "all" else [tier]
            text = "\n".join(pkgutil.get_data("crawler", f"seeds_{t}.txt").decode("utf-8") for t in tiers)
            self.tier = tier if tier in TIER_DAYS else "daily"
        self.slice_idx = int(slice) if slice is not None else slice_index(self.tier)
        self.doms = {}
        for sd in parse_seed_lines(text):
            if cap:
                sd["opts"]["cap"] = cap
            if mode and sd["opts"].get("mode") != "links":
                sd["opts"]["mode"] = mode
            self.doms.setdefault(sd["host"], Dom(sd))
        self.link_ex = LinkExtractor()

    # ---- start: robots -> sitemaps -> pick pages ------------------------------------------------
    async def start(self):
        if not self.doms:
            self.logger.error("no seeds - nothing collected"); return
        for d in self.doms.values():
            yield scrapy.Request(d.origin + "/robots.txt", callback=self.on_robots, errback=self.on_dom_error,
                                 meta={"dom": d.host, "dont_obey_robots": True}, dont_filter=True)

    def on_robots(self, response):
        d = self.doms[response.meta["dom"]]
        if d.mode == "links":
            yield from self.start_links(d); return
        sms = sitemap_urls_from_robots(response.text, base_url=response.url) if response.status == 200 else []
        sms = [u for u in sms if urlparse(u).netloc == d.host][:3] or [d.origin + "/sitemap.xml"]
        d.pending = len(sms)
        for u in sms:
            yield scrapy.Request(u, callback=self.on_sitemap, errback=self.on_sitemap_fail, meta={"dom": d.host, "lvl": 0})

    def on_sitemap(self, response):
        d = self.doms[response.meta["dom"]]
        d.pending -= 1
        try:
            if response.status != 200:
                raise ValueError(f"sitemap http {response.status}")
            sm = Sitemap(gunzip_if_needed(response.body))
            items = [x for x in sm if x.get("loc")]
            if sm.type == "sitemapindex":
                kids = sorted(items, key=lambda x: x.get("lastmod") or "", reverse=True)[:SM_KIDS]
                for k in kids:
                    if urlparse(k["loc"]).netloc == d.host and response.meta["lvl"] < 2 and d.sm_seen < SM_MAX:
                        d.sm_seen += 1; d.pending += 1
                        yield scrapy.Request(k["loc"], callback=self.on_sitemap, errback=self.on_sitemap_fail,
                                             meta={"dom": d.host, "lvl": response.meta["lvl"] + 1})
            else:
                room = max(0, ENTRIES_MAX - len(d.entries))
                d.entries += [(x["loc"], x.get("lastmod")) for x in items if urlparse(x["loc"]).netloc == d.host][:min(50000, room)]
        except Exception as e:
            self.logger.info("sitemap skipped %s: %s", response.url, e)
        yield from self.maybe_finish(d)

    def on_sitemap_fail(self, failure):
        d = self.doms[failure.request.meta["dom"]]
        d.pending -= 1
        yield from self.maybe_finish(d)

    def maybe_finish(self, d):
        if d.pending > 0 or d.sched > 0:
            return
        urls = choose_urls(d.entries, d.mode if d.mode in ("recent", "rotate") else "recent", d.cap, self.slice_idx,
                           self.since) if d.entries else []
        if not urls:
            if self.since and d.entries:          # fresh-only run and nothing fresh: that is a result, not a reason to crawl links
                self.logger.info("nothing newer than %s on %s", self.since, d.host); return
            yield from self.start_links(d); return
        for u in urls:
            if d.sched >= d.cap:
                break
            d.sched += 1
            yield scrapy.Request(u, callback=self.parse_page, errback=self.on_page_error,
                                 meta={"dom": d.host, "depth": 1, "src": "sitemap"})

    def start_links(self, d):
        d.sched = 1
        yield scrapy.Request(d.seed_url, callback=self.parse_page, errback=self.on_page_error,
                             meta={"dom": d.host, "depth": 0, "src": "seed"})

    # ---- pages -----------------------------------------------------------------------------------
    def parse_page(self, response):
        d = self.doms[response.meta["dom"]]
        base = {"url": response.request.url, "final_url": response.url, "host": d.host, "status": response.status,
                "fetched_at": now_iso(), "depth": response.meta["depth"], "source": response.meta["src"]}
        if response.meta["src"] == "sitemap":
            d.bad_streak = d.bad_streak + 1 if response.status >= 400 else 0
            if d.bad_streak >= SM_DEAD_RUN and not d.skip:
                d.skip = True
                self.logger.warning("sitemap pages on %s answer %s %d times in a row: skipping the rest of its sitemap pages",
                                    d.host, response.status, d.bad_streak)
        if response.status in BLOCK_CODES:
            d.blocked = True
            yield {**base, "blocked": True}; return
        if response.status >= 400 or not isinstance(response, scrapy.http.TextResponse):
            yield {**base, "error": f"http {response.status}"}; return
        xp = " ".join(t.strip() for t in response.xpath(
            "//body//text()[not(ancestor::script) and not(ancestor::style)]").getall() if t.strip())

        def meta(*names):
            for n in names:
                for k in ("name", "property"):
                    v = response.xpath(f'//meta[@{k}="{n}"]/@content').get()
                    if v and v.strip():
                        return v.strip()
        ld_author, ld_date = self.json_ld(response)
        ex = extract_page(response.text, response.url, xp,
                          {"author": meta("author", "article:author", "dc.creator", "DC.creator", "twitter:creator") or ld_author,
                           "published": meta("article:published_time", "datePublished", "date", "dc.date") or ld_date,
                           "title": (response.xpath("//title/text()").get() or "").strip()})
        links = [l.url for l in self.link_ex.extract_links(response)]
        yield {**base, "title": (ex["title"] or "").strip(), "author": ex["author"], "published": ex["published"],
               "lang": response.xpath("//html/@lang").get(), "extractor": ex["extractor"], "text": ex["text"],
               "content_hash": content_hash(ex["text"]), "outlink_hosts": top_outlink_hosts(d.host, links),
               "site_name": meta("og:site_name")}
        depth = response.meta["depth"]
        if response.meta["src"] in ("seed", "links") and depth < self.max_depth and not d.blocked:
            for u in links:
                if d.sched >= d.cap:
                    break
                u = u.split("#")[0]
                if urlparse(u).netloc == d.host and u != d.seed_url and u not in d.seen:
                    d.seen.add(u)
                    d.sched += 1
                    yield scrapy.Request(u, callback=self.parse_page, errback=self.on_page_error, priority=-(depth + 1),
                                         meta={"dom": d.host, "depth": depth + 1, "src": "links"})

    @staticmethod
    def json_ld(response):
        """author name + datePublished from <script type=application/ld+json>, if any."""
        author = date = None
        for raw in response.xpath('//script[@type="application/ld+json"]/text()').getall()[:5]:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            for node in (data if isinstance(data, list) else [data]):
                if not isinstance(node, dict):
                    continue
                a = node.get("author")
                a = a[0] if isinstance(a, list) and a else a
                author = author or (a.get("name") if isinstance(a, dict) else a if isinstance(a, str) else None)
                date = date or node.get("datePublished")
        return author, date

    # ---- errors become visible rows (a silent zero is the worst answer) ------------------------------
    def on_dom_error(self, failure):
        d = self.doms[failure.request.meta["dom"]]
        d.dead = True
        yield {"url": failure.request.url, "host": d.host, "status": None, "fetched_at": now_iso(),
               "error": f"unreachable: {failure.value.__class__.__name__}"}

    def on_page_error(self, failure):
        if failure.check(IgnoreRequest):          # dropped on purpose by SkipDeadSitemap; not an item
            return
        d = self.doms.get(failure.request.meta.get("dom"))
        yield {"url": failure.request.url, "host": d.host if d else None, "status": None, "fetched_at": now_iso(),
               "error": f"{failure.value.__class__.__name__}"}
