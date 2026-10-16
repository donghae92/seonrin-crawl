# seonrin-crawl r3 — index collector for Zyte Scrapy Cloud (project 881926)

Rules (unchanged since r1): seeds only · say who we are (User-Agent) · obey robots.txt · slow per domain ·
if blocked: stop that site and record it, never work around.

## What r3 adds to r2
| Need | How |
|---|---|
| Read sites that hide their links | sitemap first (robots.txt `Sitemap:` lines, index files, `.gz`), links as the automatic fallback |
| One month of running without re-reading the same 47 pages | `mode=recent` (newest sitemap entries first) or `mode=rotate` (a different slice each run; stateless, wraps around) |
| Hard per-site limit | `cap=N` counts pages **scheduled**, so it cannot leak (r2 leaked to ~47 with cap 25) |
| Clean text, author, date | `trafilatura` for main text/date; our own meta + JSON-LD reading for author. Measured: trafilatura **drops Korean author names**, so our reading is not optional. Plain-text fallback if trafilatura cannot be imported |
| Zero rows must never be silent | every error / robots denial / block becomes a row (`error`, `blocked`) |
| Find new sites | rows carry `outlink_hosts`; `tools/outlink_graph.py` ranks outside sites linked from several seed sites |
| Vet candidates from the collector's own network | spider `scout` (≤3 pages per candidate; robots denial is recorded, the page is not requested) |

## Spiders and arguments
`seeded` — `tier=daily|weekly|monthly|all` (default all) · `slice=N` (default: today's date ÷ tier period) · `cap=N` (override) · `seeds=path` (local tests)
`scout` — `hosts=a.kr,https://b.kr/x` (a list carried by the job, no redeploy) · `candidates=path` · `pages=3`

Seed line format (`crawler/seeds_<tier>.txt`): `URL  cap=60  mode=recent|rotate|links|auto`

## Periodic Jobs (Zyte, once)
Spider `seeded` with argument `tier=daily` every day · `tier=weekly` weekly · `tier=monthly` monthly.
(Zyte schedules in UTC. Whether the free unit allows Periodic Jobs was not verified.)

## Tools (`tools/`, stdlib only)
`site_report.py` per-site health of a run · `outlink_graph.py` candidate sites from links · `scout_report.py` verdict per candidate ·
`merge_candidates.py` research CSVs → candidate list · `to_index_spec.py` items → docs/passages (night-work chunk rules; spec-side fields `--source/--grade` must be validated against `~/index-spec` before any ingest)

## Tests
`python3 -m unittest tests.test_units` (11) · rehearsal kitchen: `tests/kitchen.py up|crawl|fallback|scout|post|down` + `tests/check_kitchen.py` (33 checks on five fake sites).
All fake sites live on `127.0.0.1` with different ports (no loopback aliases, so it also runs on macOS; the first r3 build used 127.0.0.2-4 and failed on the Mac mini for that reason only).
`docs/rehearsal/` holds the chef's recipe and certificate (fidelity: L1 fake sandbox — not a real-site proof).
Site key = `host:port` (production hosts have no port, so nothing changes there).
