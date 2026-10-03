import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const shared = await readFile(
  new URL("../public/assets/js/shared.js", import.meta.url),
  "utf8",
);

async function loadPage(page, script, response, stored = {}) {
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
  for (const [key, items] of Object.entries(stored))
    window.localStorage.setItem(key, JSON.stringify(items));
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
    `${shared.replaceAll("export ", "")}\n${source.replace(/^import[\s\S]*?;\s*/, script === "admin.js" ? "const fa = faNumber;" : "")}`,
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

test("saved cards preserve collection previews and delete only the selected item", async (t) => {
  const { dom, window } = await loadPage("saved.html", "saved.js", () => ({}), {
    kahoo_saved_merchants: [{ ...merchant, key: "1" }],
    kahoo_saved_posts: [
      {
        key: "post-1",
        merchant_name: merchant.name,
        media_url: "/api/media/1",
        permalink: merchant.posts[0].permalink,
        image_count: 2,
      },
      {
        key: "post-2",
        merchant_name: merchant.name,
        media_url: "/api/media/2",
        permalink: merchant.posts[1].permalink,
        image_count: 1,
      },
    ],
  });
  t.after(() => dom.window.close());
  assert.equal(window.document.querySelectorAll(".saved-merchant").length, 1);
  assert.equal(window.document.querySelectorAll(".saved-post").length, 2);
  window.document.querySelector(".saved-post .remove-button").click();
  assert.equal(window.document.querySelectorAll(".saved-post").length, 1);
  assert.equal(
    JSON.parse(window.localStorage.getItem("kahoo_saved_posts"))[0].key,
    "post-2",
  );
  window.document.querySelector(".saved-merchant .remove-button").click();
  assert.equal(
    JSON.parse(window.localStorage.getItem("kahoo_saved_merchants")).length,
    0,
  );
});

test("admin dashboard renders metrics and managed merchants independently", async (t) => {
  const metrics = {
    kpis: {
      searches: 5,
      visitors: 3,
      clicks: 2,
      zero_rate: 0,
      search_to_click: 50,
    },
    daily: [{ date: "2026-10-03", searches: 5, clicks: 2 }],
    top_queries: [],
    missed_queries: [],
    top_merchants: [],
    funnel: {
      visitors: 3,
      searched: 2,
      clicked: 1,
      oauth_started: 0,
      oauth_completed: 0,
    },
    catalog: {
      merchants: 1,
      used_categories: 1,
      posts: 4,
      avatars: 1,
      descriptions: 1,
    },
    generated_at: "2026-10-03T10:00:00",
  };
  const { dom, window } = await loadPage("admin.html", "admin.js", (path) => {
    if (path.startsWith("/api/admin/metrics")) return metrics;
    if (path.startsWith("/api/admin/merchants"))
      return {
        total: 1,
        items: [{ ...merchant, post_count: 4, followers_count: 10 }],
      };
    return [];
  });
  t.after(() => dom.window.close());
  assert.equal(window.document.querySelector("#dashboard").hidden, false);
  assert.equal(window.document.querySelectorAll("#trend-chart svg").length, 1);
  assert.equal(window.document.querySelectorAll(".managed-row").length, 1);
  assert.equal(window.document.querySelectorAll("#funnel em").length, 5);
});
