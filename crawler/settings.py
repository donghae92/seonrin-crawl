# Collection rules (unchanged since r1): seeds only / say who we are / obey robots.txt /
# slow per domain / if blocked, stop that domain and record it - never work around.
BOT_NAME = "seonrin-index-collector"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

USER_AGENT = "seonrin-index-collector/1.0 (+mailto:weebm13@gmail.com; personal search index, obeys robots.txt)"
ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 3
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 30

RETRY_TIMES = 1
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]   # 403/429 are never retried
COOKIES_ENABLED = False
CLOSESPIDER_PAGECOUNT = 4000   # safety ceiling per run
DOWNLOAD_TIMEOUT = 30
TELNETCONSOLE_ENABLED = False
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
