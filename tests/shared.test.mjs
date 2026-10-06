import assert from "node:assert/strict";
import test from "node:test";
import {
  api,
  escapeHtml,
  storedItems,
  initializeSession,
} from "../public/assets/js/shared.js";

test("escapeHtml handles text and double-quoted attribute values", () => {
  assert.equal(
    escapeHtml("<shop name=\"a&b\">'فروشگاه'"),
    "&lt;shop name=&quot;a&amp;b&quot;&gt;&#39;فروشگاه&#39;",
  );
  assert.throws(() => escapeHtml(0), TypeError);
  assert.throws(() => escapeHtml(null), TypeError);
});

test("saved items distinguish missing storage from corrupt data", () => {
  let stored = null;
  globalThis.localStorage = {
    getItem: () => stored,
    setItem: (_key, value) => {
      stored = value;
    },
  };
  assert.deepEqual(storedItems("saved"), []);
  for (const value of ["broken", "null", "{}", '"text"']) {
    stored = value;
    assert.throws(() => storedItems("saved"));
    assert.equal(stored, value);
  }
  const items = [{ key: "1", name: "فروشگاه" }];
  stored = JSON.stringify(items);
  assert.deepEqual(storedItems("saved"), items);
  delete globalThis.localStorage;
});

test("API requests preserve caller headers and include the current session", async (t) => {
  const headers = new Headers({ "X-Kahoo-Admin-Token": "admin" });
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path === "/api/session")
      return new Response(
        JSON.stringify({ session_id: "session123", user: null }),
      );
    if (path === "/api/saved")
      return new Response(JSON.stringify({ merchants: [], posts: [] }));
    assert.equal(path, "/api/admin/merchants");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("X-Kahoo-Admin-Token"), "admin");
    assert.equal(options.headers.get("X-Kahoo-Session"), "session123");
    assert.equal(options.credentials, "same-origin");
    return new Response('{"created":true}', {
      headers: { "Content-Type": "application/json" },
    });
  });
  globalThis.localStorage = { getItem: () => null, removeItem: () => {} };
  try {
    await initializeSession();
    assert.deepEqual(
      await api("/api/admin/merchants", { method: "POST", headers }),
      { created: true },
    );
    assert.equal(headers.has("X-Kahoo-Session"), false);
  } finally {
    delete globalThis.localStorage;
  }
});

test("API failures keep server messages and reject invalid successful JSON", async (t) => {
  const responses = [
    new Response('{"error":"invalid","message":"choose a category"}', {
      status: 400,
      headers: { "Content-Type": "application/json" },
    }),
    new Response("server error", { status: 500 }),
    new Response("invalid JSON", {
      headers: { "Content-Type": "application/json" },
    }),
  ];
  t.mock.method(globalThis, "fetch", async () => responses.shift());
  globalThis.localStorage = { getItem: () => null };
  try {
    await assert.rejects(api("/api/admin/merchants"), /choose a category/);
    await assert.rejects(api("/api/admin/merchants"), /API 500/);
    await assert.rejects(api("/api/merchants"), SyntaxError);
  } finally {
    delete globalThis.localStorage;
  }
});
