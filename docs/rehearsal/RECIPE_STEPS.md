# RECIPE — seonrin-crawl-r3-core  (generated from recipe.json; edit the json, not this file)

- [ ] step 1: workdir   target: local kitchen (L1 FAKE sandbox)
  check_before: test -d /tmp/r3k
  do: ['mkdir -p /tmp/r3k']
  expect: exit 0; work dir writable
  check_after: test -w /tmp/r3k
  undo: rm -rf /tmp/r3k
  on_fail: ['permission-denied', 'disk-full']
- [ ] step 2: deps   target: local kitchen (L1 FAKE sandbox)
  check_before: python3 -c 'import scrapy,trafilatura,protego'
  do: ['pip install -q scrapy trafilatura --break-system-packages', 'pip install -q scrapy trafilatura']
  expect: imports succeed
  check_after: python3 -c 'import scrapy,trafilatura,protego'
  undo: none: packages stay installed
  on_fail: ['network-drop', 'disk-full', 'permission-denied']
- [ ] step 3: unit   target: local kitchen (L1 FAKE sandbox)
  check_before: tail -3 /tmp/r3k/unit.txt | grep -q '^OK'
  do: ['cd /home/claude/r3 && python3 -m unittest tests.test_units > /tmp/r3k/unit.txt 2>&1']
  expect: 11 unit tests OK
  check_after: tail -3 /tmp/r3k/unit.txt | grep -q '^OK'
  undo: rm -f /tmp/r3k/unit.txt
  on_fail: ['disk-full', 'permission-denied']
- [ ] step 4: sites_up   target: local kitchen (L1 FAKE sandbox)
  check_before: curl -sf http://127.0.0.1:18201/robots.txt > /dev/null
  do: ['python3 /home/claude/r3/tests/kitchen.py up']
  expect: fake sites answer on 18201
  check_after: curl -sf http://127.0.0.1:18201/robots.txt > /dev/null
  undo: python3 /home/claude/r3/tests/kitchen.py down
  on_fail: ['port-in-use', 'network-drop', 'permission-denied']
- [ ] step 5: crawl   target: local kitchen (L1 FAKE sandbox)
  check_before: test -s /tmp/r3k/items0.jsonl && test -s /tmp/r3k/items1.jsonl
  do: ['cd /home/claude/r3 && python3 tests/kitchen.py crawl', 'cd /home/claude/r3 && R3_NO_TRAFILATURA=1 python3 tests/kitchen.py crawl']
  expect: two slices written; 2nd method = plain-text fallback
  check_after: test -s /tmp/r3k/items0.jsonl && test -s /tmp/r3k/items1.jsonl
  undo: rm -f /tmp/r3k/items0.jsonl /tmp/r3k/items1.jsonl
  on_fail: ['trafilatura-missing', 'sites-down', 'network-drop', 'disk-full']
- [ ] step 6: fallback_crawl   target: local kitchen (L1 FAKE sandbox)
  check_before: test -s /tmp/r3k/items0_fb.jsonl
  do: ['cd /home/claude/r3 && python3 tests/kitchen.py fallback']
  expect: forced plain-text run written
  check_after: test -s /tmp/r3k/items0_fb.jsonl
  undo: rm -f /tmp/r3k/items0_fb.jsonl
  on_fail: ['sites-down', 'disk-full']
- [ ] step 7: scout   target: local kitchen (L1 FAKE sandbox)
  check_before: test -s /tmp/r3k/scout.jsonl
  do: ['cd /home/claude/r3 && python3 tests/kitchen.py scout']
  expect: scout items written
  check_after: test -s /tmp/r3k/scout.jsonl
  undo: rm -f /tmp/r3k/scout.jsonl
  on_fail: ['sites-down', 'disk-full']
- [ ] step 8: post   target: local kitchen (L1 FAKE sandbox)
  check_before: test -s /tmp/r3k/convert/summary.json && test -s /tmp/r3k/graph.csv
  do: ['cd /home/claude/r3 && python3 tests/kitchen.py post']
  expect: converter + link graph outputs
  check_after: test -s /tmp/r3k/convert/summary.json && test -s /tmp/r3k/graph.csv
  undo: rm -rf /tmp/r3k/convert /tmp/r3k/graph.csv
  on_fail: ['disk-full', 'permission-denied']
- [ ] step 9: assert   target: local kitchen (L1 FAKE sandbox)
  check_before: grep -q 'ALL PASS' /tmp/r3k/check.txt
  do: ['cd /home/claude/r3 && python3 tests/check_kitchen.py > /tmp/r3k/check.txt 2>&1']
  expect: every kitchen check passes
  check_after: grep -q 'ALL PASS' /tmp/r3k/check.txt
  undo: rm -f /tmp/r3k/check.txt
  on_fail: ['disk-full']
- [ ] step 10: sites_down   target: local kitchen (L1 FAKE sandbox)
  check_before: ! curl -sf http://127.0.0.1:18201/robots.txt > /dev/null
  do: ['python3 /home/claude/r3/tests/kitchen.py down']
  expect: fake sites stopped
  check_after: ! curl -sf http://127.0.0.1:18201/robots.txt > /dev/null
  undo: none: fake sites are throw-away
  on_fail: ['permission-denied']

done_check: grep -q 'ALL PASS' /tmp/r3k/check.txt && tail -3 /tmp/r3k/unit.txt | grep -q '^OK'
