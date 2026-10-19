// node --test worker/test/landing.test.mjs   (in-memory R2; no network, no Cloudflare)
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

function fakeR2() {
  const m = new Map();
  return {
    m,
    async head(k) { return m.has(k) ? { customMetadata: m.get(k).meta } : null; },
    async put(k, body, o) { m.set(k, { body: new Uint8Array(body), meta: o.customMetadata }); },
    async get(k) { const v = m.get(k); return v ? { body: new Blob([v.body]).stream() } : null; },
    async list({ prefix }) {
      const objects = [...m.entries()].filter(([k]) => k.startsWith(prefix)).map(([k, v]) => ({ key: k, size: v.body.length }));
      return { objects, truncated: false };
    },
  };
}
const env = () => ({ RAW: fakeR2(), WRITE_TOKEN: "w-secret", READ_TOKEN: "r-secret" });
const call = (e, method, path, tok, body) =>
  worker.fetch(new Request("https://x" + path, { method, headers: tok ? { authorization: "Bearer " + tok } : {}, body }), e);
const KEY = "zyte/seeded/daily/881926-1-5/00001.jsonl";
const DATA = '{"url":"https://a"}\n{"url":"https://b"}\n';

test("health", async () => {
  const r = await call(env(), "GET", "/health");
  assert.deepEqual(await r.json(), { ok: true });
});
test("put new file -> 200 with line count", async () => {
  const e = env();
  const r = await call(e, "PUT", "/put?key=" + KEY, "w-secret", DATA);
  const j = await r.json();
  assert.equal(r.status, 200); assert.equal(j.lines, 2); assert.equal(e.RAW.m.size, 1);
});
test("same bytes again -> duplicate:true, nothing added", async () => {
  const e = env();
  await call(e, "PUT", "/put?key=" + KEY, "w-secret", DATA);
  const j = await (await call(e, "PUT", "/put?key=" + KEY, "w-secret", DATA)).json();
  assert.equal(j.duplicate, true); assert.equal(e.RAW.m.size, 1);
});
test("different bytes under existing key -> 409, file untouched", async () => {
  const e = env();
  await call(e, "PUT", "/put?key=" + KEY, "w-secret", DATA);
  const r = await call(e, "PUT", "/put?key=" + KEY, "w-secret", '{"url":"https://c"}\n');
  assert.equal(r.status, 409); assert.equal(e.RAW.m.size, 1);
});
test("missing / wrong / read token on put -> 401", async () => {
  const e = env();
  for (const t of [null, "nope", "r-secret"]) {
    assert.equal((await call(e, "PUT", "/put?key=" + KEY, t, DATA)).status, 401);
  }
  assert.equal(e.RAW.m.size, 0);
});
test("keys outside zyte/ or malformed -> 400", async () => {
  const e = env();
  for (const k of ["other/x.jsonl", "zyte/../x.jsonl", "zyte/a.txt", "zyte//a.jsonl", ""]) {
    assert.equal((await call(e, "PUT", "/put?key=" + k, "w-secret", DATA)).status, 400, k);
  }
});
test("empty body -> 400, over 50MB declared -> 413", async () => {
  const e = env();
  assert.equal((await call(e, "PUT", "/put?key=" + KEY, "w-secret", "")).status, 400);
  const r = await worker.fetch(new Request("https://x/put?key=" + KEY, { method: "PUT", body: DATA,
    headers: { authorization: "Bearer w-secret", "content-length": String(60 * 1024 * 1024) } }), e);
  assert.equal(r.status, 413);
});
test("list and get need the read token; write token gets 401", async () => {
  const e = env();
  await call(e, "PUT", "/put?key=" + KEY, "w-secret", DATA);
  assert.equal((await call(e, "GET", "/list?prefix=zyte/", "w-secret")).status, 401);
  assert.equal((await call(e, "GET", "/get?key=" + KEY, "w-secret")).status, 401);
  const l = await (await call(e, "GET", "/list?prefix=zyte/", "r-secret")).json();
  assert.equal(l.keys.length, 1); assert.equal(l.keys[0].key, KEY);
  const g = await call(e, "GET", "/get?key=" + KEY, "r-secret");
  assert.equal(await g.text(), DATA);
});
test("list outside zyte/ -> 400; unknown path -> 404; missing key -> 404", async () => {
  const e = env();
  assert.equal((await call(e, "GET", "/list?prefix=other/", "r-secret")).status, 400);
  assert.equal((await call(e, "GET", "/nope", "r-secret")).status, 404);
  assert.equal((await call(e, "GET", "/get?key=zyte/none.jsonl", "r-secret")).status, 404);
});
test("unset secrets never authenticate", async () => {
  const e = { RAW: fakeR2() };
  assert.equal((await call(e, "PUT", "/put?key=" + KEY, "", DATA)).status, 401);
  assert.equal((await call(e, "PUT", "/put?key=" + KEY, "undefined", DATA)).status, 401);
});
