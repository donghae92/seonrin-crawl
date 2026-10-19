// zyte-landing: the doorman in front of R2 bucket seonrin-index-raw (binding RAW).
// Secrets (wrangler secret put): WRITE_TOKEN (adds new files only), READ_TOKEN (list/get only).
//   GET  /health                  -> {"ok":true}
//   PUT  /put?key=zyte/...jsonl   write token. new file 200 | same bytes again 200 {"duplicate":true}
//                                 | different bytes under an existing key 409 | outside zyte/ 400 | >50MB 413
//   GET  /list?prefix=zyte/..     read token. {"keys":[{key,size}],"truncated":bool,"cursor":..}
//   GET  /get?key=zyte/...        read token. the file bytes
const MAX_BYTES = 50 * 1024 * 1024;
const KEY_RE = /^zyte\/[A-Za-z0-9_\-./]+\.jsonl$/;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

function bearer(req) {
  const h = req.headers.get("authorization") || "";
  return h.startsWith("Bearer ") ? h.slice(7).trim() : "";
}

function same(a, b) {            // length-independent compare of two secrets
  if (!a || !b) return false;
  let diff = a.length ^ b.length;
  const n = Math.max(a.length, b.length);
  for (let i = 0; i < n; i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

async function sha256Hex(buf) {
  const d = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(d)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function validKey(key) {
  return typeof key === "string" && key.length <= 300 && KEY_RE.test(key) && !key.includes("..") && !key.includes("//");
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname;

    if (path === "/health") return json({ ok: true });

    if (path === "/put") {
      if (req.method !== "PUT") return json({ error: "method" }, 405);
      if (!same(bearer(req), env.WRITE_TOKEN)) return json({ error: "unauthorized" }, 401);
      const key = url.searchParams.get("key");
      if (!validKey(key)) return json({ error: "bad key" }, 400);
      const declared = Number(req.headers.get("content-length") || 0);
      if (declared > MAX_BYTES) return json({ error: "too large" }, 413);
      const body = await req.arrayBuffer();
      if (body.byteLength > MAX_BYTES) return json({ error: "too large" }, 413);
      if (body.byteLength === 0) return json({ error: "empty" }, 400);
      const digest = await sha256Hex(body);
      const old = await env.RAW.head(key);
      if (old) {
        const prev = old.customMetadata && old.customMetadata.sha256;
        if (prev === digest) return json({ ok: true, duplicate: true, key, sha256: digest });
        return json({ error: "key exists with different bytes", key }, 409);
      }
      await env.RAW.put(key, body, { customMetadata: { sha256: digest } });
      const lines = new TextDecoder().decode(body).split("\n").filter((l) => l.trim()).length;
      return json({ ok: true, key, bytes: body.byteLength, lines, sha256: digest });
    }

    if (path === "/list" || path === "/get") {
      if (req.method !== "GET") return json({ error: "method" }, 405);
      if (!same(bearer(req), env.READ_TOKEN)) return json({ error: "unauthorized" }, 401);
      if (path === "/list") {
        const prefix = url.searchParams.get("prefix") || "zyte/";
        if (!prefix.startsWith("zyte/") || prefix.includes("..")) return json({ error: "bad prefix" }, 400);
        const cursor = url.searchParams.get("cursor") || undefined;
        const r = await env.RAW.list({ prefix, cursor, limit: 1000 });
        return json({
          keys: r.objects.map((o) => ({ key: o.key, size: o.size })),
          truncated: !!r.truncated,
          cursor: r.truncated ? r.cursor : null,
        });
      }
      const key = url.searchParams.get("key");
      if (!validKey(key)) return json({ error: "bad key" }, 400);
      const obj = await env.RAW.get(key);
      if (!obj) return json({ error: "not found" }, 404);
      return new Response(obj.body, { headers: { "content-type": "application/x-ndjson" } });
    }

    return json({ error: "not found" }, 404);
  },
};
