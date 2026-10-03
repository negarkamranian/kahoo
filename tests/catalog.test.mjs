import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const shared = await readFile(
  new URL("../public/assets/js/shared.js", import.meta.url),
  "utf8",
);

async function loadPage(page, script, response) {
  const html = await readFile(
    new URL(`../public/${page}`, import.meta.url),
    "utf8",
  );
  const source = await readFile(
    new URL(`../public/assets/js/${script}`, import.meta.url),
    "utf8",
  );
  const dom = new JSDOM(html, {
    url: "https://kahoo.test/",
    runScripts: "outside-only",
  });
  const { window } = dom;
  window.matchMedia = () => ({ matches: false });
  window.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  window.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  window.HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const requests = [];
  window.fetch = async (path, options) => {
    requests.push({ path, options });
    const data = response(path, options);
    return { ok: true, json: async () => data };
  };
  window.Headers = Headers;
  window.eval(
    `${shared.replaceAll("export ", "")}\n${source.replace(/^import[\s\S]*?;\s*/, "")}`,
  );
  await new Promise((resolve) => setImmediate(resolve));
  return { dom, window, requests };
}

const merchant = {
  id: 1,
  name: "فروشگاه",
  handle: "@shop",
  city: "تهران",
  description: "کفش",
  biography: "بیوی فروشگاه",
  avatar_url: "/api/avatars/1",
  instagram_url: "https://instagram.com/shop/",
  categories: [{ label: "کفش" }],
  category_label: "کفش",
  metrics_updated_at: null,
  posts: [1, 2, 3, 4].map((id) => ({
    post_id: id,
    key: `post-${id}`,
    permalink: `https://instagram.com/p/${id}/`,
    media_url: `/api/media/${id}`,
    media: [1, 2].map((position) => ({
      media_url: `/api/media/${id}-${position}`,
    })),
  })),
};

test("catalog cards keep click tracking, accessible reels and grouped post saves", async (t) => {
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => {
      if (path === "/api/categories") return [];
      if (path.startsWith("/api/merchants?")) return [merchant];
      if (path === "/api/merchants/1") return merchant;
      return { saved: true };
    },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  assert.equal(document.querySelectorAll("#shop-grid article").length, 1);
  assert.equal(document.querySelectorAll(".post-reel-track .post").length, 7);
  assert.equal(
    document.querySelectorAll('.post-reel-track [aria-hidden="false"]').length,
    3,
  );
  // Prevent external navigation while still exercising the real click handler.
  const visit = document.querySelector(".visit-link");
  visit.addEventListener("click", (event) => event.preventDefault());
  visit.click();
  assert.equal(
    requests.filter((request) => request.path === "/api/analytics/event")
      .length,
    1,
  );
  await window.openMerchantProfile(1);
  assert.equal(
    document.querySelector("#detail-name").textContent,
    merchant.name,
  );
  assert.equal(
    document.querySelectorAll("#detail-posts .saved-post-tile").length,
    4,
  );
  assert.equal(document.querySelectorAll("#detail-posts img").length, 8);
  document.querySelector(".post-save").click();
  const saved = JSON.parse(window.localStorage.getItem("kahoo_saved_posts"));
  assert.equal(saved[0].key, "post-1");
  assert.equal(saved[0].image_count, 2);
  assert.equal(
    document.querySelector(".post-save").getAttribute("aria-pressed"),
    "true",
  );
  document.querySelector(".post-save").click();
  assert.equal(
    JSON.parse(window.localStorage.getItem("kahoo_saved_posts")).length,
    0,
  );
});

test("saved page presents empty collections", async (t) => {
  const { dom, window } = await loadPage("saved.html", "saved.js", () => ({}));
  t.after(() => dom.window.close());
  assert.equal(
    window.document.querySelectorAll(".empty-state.compact").length,
    2,
  );
});
