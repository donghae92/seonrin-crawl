"""LandingPipeline: every item goes to the landing Worker (-> R2) in JSONL batches, so Zyte's own
storage is no longer the only copy. Off unless LAND_URL and LAND_TOKEN are set (job settings or env).

Contract with worker/src/index.js:
  PUT {LAND_URL}/put?key=zyte/<spider>/<tier>/<job>/<00001>.jsonl   Authorization: Bearer <write token>
  200 {"ok":true,...} new file | 200 {"duplicate":true} same bytes again | 4xx/5xx = failure.
A failed batch is retried, then counted (stat land/failed_batches); the item itself still goes on to
Zyte's storage, so nothing is lost silently. Stats: land/items_landed, land/batches_ok, land/failed_batches."""
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from scrapy.exceptions import NotConfigured
from twisted.internet import defer, threads

log = logging.getLogger(__name__)

DEFAULT_BATCH = 500
RETRY_WAITS = (2, 5, 15)           # seconds before attempt 2, 3, 4


def job_slug(env=None):
    """Zyte sets SCRAPY_JOB='881926/1/5'. Anything else (local run) gets a time stamp."""
    env = os.environ if env is None else env
    job = env.get("SCRAPY_JOB") or ""
    if job:
        return job.replace("/", "-")
    return "local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def put_batch(url, token, key, body, timeout=60, waits=RETRY_WAITS, sleep=time.sleep):
    """PUT one batch. Returns the parsed JSON reply, raises after the last attempt."""
    full = url.rstrip("/") + "/put?key=" + key
    last = None
    for attempt in range(len(waits) + 1):
        req = urllib.request.Request(full, data=body, method="PUT")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Content-Type", "application/x-ndjson")
        req.add_header("User-Agent", "seonrin-index-collector/1.0")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            last = f"http {e.code}"
            if e.code in (400, 401, 403, 409, 413):    # retrying cannot change these
                raise RuntimeError(f"landing refused {key}: {last}") from None
        except Exception as e:                         # network / timeout
            last = f"{type(e).__name__}: {e}"
        if attempt < len(waits):
            sleep(waits[attempt])
    raise RuntimeError(f"landing failed {key} after {len(waits) + 1} attempts: {last}")


class LandingPipeline:
    # tests swap this for a synchronous runner
    runner = staticmethod(threads.deferToThread)

    def __init__(self, url, token, batch, stats, spider_name, tier, slug):
        self.url, self.token, self.batch, self.stats = url, token, batch, stats
        self.prefix = f"zyte/{spider_name}/{tier}/{slug}/"
        self.buf, self.count, self.pending = [], 0, []

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        url = s.get("LAND_URL") or os.environ.get("LAND_URL")
        token = s.get("LAND_TOKEN") or os.environ.get("LAND_TOKEN")
        if not url or not token:
            raise NotConfigured("LAND_URL / LAND_TOKEN not set: landing is off")
        batch = int(s.get("LAND_BATCH_ITEMS") or os.environ.get("LAND_BATCH_ITEMS") or DEFAULT_BATCH)
        pipe = cls(url, token, max(1, batch), crawler.stats, "?", "all", job_slug())
        crawler.signals.connect(pipe.bind, signal=__import__("scrapy").signals.spider_opened)
        return pipe

    def bind(self, spider):
        tier = getattr(spider, "label", None) or getattr(spider, "tier", None) or "all"   # a curriculum lesson names its own folder
        self.prefix = f"zyte/{spider.name}/{tier}/{job_slug()}/"
        log.info("landing on: %s batch=%d", self.prefix, self.batch)

    def process_item(self, item, spider=None):
        self.buf.append(json.dumps(dict(item), ensure_ascii=False, default=str))
        if len(self.buf) >= self.batch:
            self._submit()
        return item

    def _submit(self):
        if not self.buf:
            return
        lines, self.buf = self.buf, []
        self.count += 1
        key = f"{self.prefix}{self.count:05d}.jsonl"
        body = ("\n".join(lines) + "\n").encode("utf-8")
        d = self.runner(put_batch, self.url, self.token, key, body)
        d.addCallbacks(self._ok, self._bad, callbackArgs=(len(lines), key, hashlib.sha256(body).hexdigest()),
                       errbackArgs=(len(lines), key))
        self.pending.append(d)

    def _ok(self, reply, n, key, digest):
        self.stats.inc_value("land/batches_ok")
        self.stats.inc_value("land/items_landed", n)
        log.info("landed %s items=%d%s", key, n, " (duplicate)" if reply.get("duplicate") else "")

    def _bad(self, failure, n, key):
        self.stats.inc_value("land/failed_batches")
        self.stats.inc_value("land/items_failed", n)
        log.error("LANDING FAILED %s items=%d: %s", key, n, failure.getErrorMessage())

    def close_spider(self, spider=None):
        self._submit()
        return defer.DeferredList(self.pending, consumeErrors=True)
