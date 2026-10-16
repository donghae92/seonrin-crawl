# Collection rules (fixed before any run):
# 1 seeds only: never leave the seed domains   2 say who we are (User-Agent)
# 3 obey robots.txt   4 slow per domain   5 if blocked, stop that domain - never work around
BOT_NAME = "seonrin-index-collector"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

USER_AGENT = "seonrin-index-collector/1.0 (+mailto:weebm13@gmail.com; personal search index, obeys robots.txt)"
ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 3
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 30

RETRY_TIMES = 1            # no hammering
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]  # 403/429 are never retried: blocked = stop
COOKIES_ENABLED = False
DEPTH_LIMIT = 1            # seed page + links one step away, same domain only
PER_DOMAIN_MAX = 25        # max pages followed per domain per run (seed page always read)
CLOSESPIDER_PAGECOUNT = 1200  # safety ceiling per run; raise by hand
DOWNLOAD_TIMEOUT = 30
TELNETCONSOLE_ENABLED = False
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
