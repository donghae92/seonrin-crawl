Index collector for Zyte Scrapy Cloud (project 881926).
1) Edit USER_AGENT contact in crawler/settings.py  2) Fill seeds.txt  3) Run spider "seeded" in Zyte.
Local test: scrapy crawl seeded -O out.jsonl
Rules: seeds only / identify ourselves / obey robots.txt / slow per domain / blocked = stop, never work around.
