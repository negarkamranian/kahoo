import assert from "node:assert/strict";
import test from "node:test";
import {
  escapeHtml,
  saveItems,
  storedItems,
} from "../public/assets/js/shared.js";

test("escapeHtml handles text and double-quoted attribute values", () => {
  assert.equal(
    escapeHtml("<shop name=\"a&b\">'فروشگاه'"),
    "&lt;shop name=&quot;a&amp;b&quot;&gt;&#39;فروشگاه&#39;",
  );
  assert.equal(escapeHtml(0), "0");
  assert.equal(escapeHtml(null), "");
});

test("saved items handle corrupt or non-array browser storage", () => {
  let stored = null;
  globalThis.localStorage = {
    getItem: () => stored,
    setItem: (_key, value) => {
      stored = value;
    },
  };
  for (const value of [null, "broken", "null", "{}", '"text"']) {
    stored = value;
    assert.deepEqual(storedItems("saved"), []);
  }
  const items = [{ key: "1", name: "فروشگاه" }];
  saveItems("saved", items);
  assert.deepEqual(storedItems("saved"), items);
  delete globalThis.localStorage;
});
