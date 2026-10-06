import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const shared = await readFile(
  new URL("../public/assets/js/shared.js", import.meta.url),
  "utf8",
);

async function loadPage(
  page,
  script,
  response,
  stored = {},
  {
    finePointer = false,
    savedAPI = () => undefined,
    coordinateTabs = true,
  } = {},
) {
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
  if (coordinateTabs)
    window.navigator.locks = { request: async (_name, work) => work() };
  for (const [key, items] of Object.entries(stored))
    window.localStorage.setItem(key, JSON.stringify(items));
  window.matchMedia = (query) => ({
    matches: finePointer && query === "(hover: hover) and (pointer: fine)",
  });
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
  const serverSaved = { merchants: [], posts: [] };
  window.fetch = async (path, options) => {
    requests.push({ path, options });
    const data =
      path === "/api/session"
        ? { session_id: "server-session", user: null }
        : path.startsWith("/api/saved")
          ? (savedAPI(path, options, serverSaved) ??
            savedResponse(path, options, serverSaved))
          : response(path, options);
    return { ok: true, json: async () => data };
  };
  window.Headers = Headers;
  window.eval(
    `${shared.replaceAll("export ", "")}\n${source.replace(/^import[\s\S]*?;\s*/, script === "admin.js" ? "const fa = faNumber;" : "")}`,
  );
  await new Promise((resolve) => setImmediate(resolve));
  return { dom, window, requests, serverSaved };
}

function savedResponse(path, options, state) {
  if (path === "/api/saved") return state;
  if (path === "/api/saved/import") {
    const payload = JSON.parse(options.body);
    for (const ref of payload.merchants || [])
      state.merchants.push({ ...merchant, id: ref.id, key: String(ref.id) });
    for (const ref of payload.posts || []) {
      const post = merchant.posts.find(
        (item) => item.key === ref.key || item.permalink === ref.permalink,
      );
      state.posts.push({
        ...ref,
        key: post.key,
        merchant_id: ref.merchant_id || 1,
        merchant_name: merchant.name,
        permalink: post.permalink,
        media_url: post.media_url,
        image_count: post.media.length,
      });
    }
    return { ...state, skipped_merchants: [], skipped_posts: [] };
  }
  const [, , , kind, id, key] = path.split("/");
  if (kind === "merchants") {
    state.merchants = state.merchants.filter((item) => item.id !== Number(id));
    if (options.method === "PUT")
      state.merchants.unshift({ ...merchant, id: Number(id), key: id });
  } else {
    state.posts = state.posts.filter(
      (item) =>
        item.merchant_id !== Number(id) || item.key !== decodeURIComponent(key),
    );
    if (options.method === "PUT") {
      const post = merchant.posts.find(
        (item) => item.key === decodeURIComponent(key),
      );
      state.posts.unshift({
        key: post.key,
        merchant_id: Number(id),
        merchant_name: merchant.name,
        permalink: post.permalink,
        media_url: post.media_url,
        image_count: post.media.length,
      });
    }
  }
  return state;
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
  category_code: "67010300",
  category_path: [
    { code: "67000000", label: "پوشاک" },
    { code: "67010300", label: "کفش" },
  ],
  categories: [{ code: "67010300", label: "کفش" }],
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

const categoryTree = [
  {
    code: "67000000",
    parent_code: null,
    level: 1,
    label_fa: "پوشاک",
    label_en: "Clothing",
    icon: null,
    count: 1,
    children: [
      {
        code: "67010300",
        parent_code: "67000000",
        level: 2,
        label_fa: "کفش",
        label_en: "Shoes",
        icon: null,
        count: 1,
        children: [],
      },
    ],
  },
  {
    code: "73000000",
    parent_code: null,
    level: 1,
    label_fa: "خانه",
    label_en: "Home",
    icon: null,
    count: 1,
    children: [
      {
        code: "73010300",
        parent_code: "73000000",
        level: 2,
        label_fa: "دکور",
        label_en: "Decor",
        icon: null,
        count: 1,
        children: [],
      },
    ],
  },
  {
    code: "44000000",
    parent_code: null,
    level: 1,
    label_fa: "کتاب",
    label_en: "Books",
    icon: null,
    count: 0,
    children: [],
  },
];

const homeMerchant = {
  ...merchant,
  id: 2,
  name: "فروشگاه خانه",
  handle: "@home_shop",
  category_code: "73010300",
  category_label: "دکور",
  category_path: [
    { code: "73000000", label: "خانه" },
    { code: "73010300", label: "دکور" },
  ],
  categories: [{ code: "73010300", label: "دکور" }],
  posts: merchant.posts.map((post) => ({
    ...post,
    key: `home-${post.key}`,
    media_url: `${post.media_url}-home`,
    media: post.media.map((image) => ({
      media_url: `${image.media_url}-home`,
    })),
  })),
};

const settlePage = () => new Promise((resolve) => setImmediate(resolve));

test("catalog cards keep click tracking, accessible reels and grouped post saves", async (t) => {
  const { dom, window, requests, serverSaved } = await loadPage(
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
  await settlePage();
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
  await settlePage();
  const saved = serverSaved.posts;
  assert.equal(saved[0].key, "post-1");
  assert.equal(saved[0].image_count, 2);
  assert.equal(
    document.querySelector(".post-save").getAttribute("aria-pressed"),
    "true",
  );
  document.querySelector(".post-save").click();
  await settlePage();
  assert.equal(serverSaved.posts.length, 0);
  assert.equal(window.localStorage.getItem("kahoo_saved_posts"), null);
});

test("shop profile facts distinguish observed zero from unavailable data", async (t) => {
  let profile = {
    ...merchant,
    followers_count: 12500,
    following_count: 0,
    former_username_count: 0,
  };
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) => {
    if (path === "/api/categories") return [];
    if (path === "/api/merchants/1") return profile;
    return [merchant];
  });
  t.after(() => dom.window.close());
  const document = window.document;
  await window.openMerchantProfile(1);
  assert.equal(
    document.querySelector("#detail-followers").textContent,
    new Intl.NumberFormat("fa-IR").format(12500),
  );
  assert.equal(document.querySelector("#detail-following").textContent, "۰");
  assert.equal(document.querySelector("#detail-former-names").textContent, "۰");
  document.querySelector("#merchant-dialog").close();
  profile = merchant;
  await window.openMerchantProfile(1);
  for (const field of ["followers", "following", "former-names", "created"])
    assert.equal(
      document.querySelector(`#detail-${field}`).textContent,
      "در دسترس نیست",
    );
});

test("discovery groups real shop images and preserves category, search and reset flows", async (t) => {
  const shops = [merchant, homeMerchant];
  const saved = [{ ...merchant, key: "1" }];
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => {
      if (path === "/api/categories") return categoryTree;
      if (path.startsWith("/api/merchants?")) {
        const params = new URL(path, "https://kahoo.test").searchParams;
        return shops.filter(
          (shop) =>
            !params.has("category") ||
            shop.category_path.some(
              (category) => category.code === params.get("category"),
            ),
        );
      }
      return [];
    },
    { kahoo_saved_merchants: saved },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  const discovery = document.querySelector("#discovery");
  const quickCategories = [
    ...document.querySelectorAll("#quick-categories button[data-category]"),
  ];
  assert.deepEqual(
    quickCategories.map((button) => button.dataset.category),
    ["67000000", "73000000"],
  );
  assert.equal(discovery.hidden, false);
  const collections = [
    ...document.querySelectorAll("#discovery-grid button[data-category]"),
  ];
  assert.equal(collections.length, 2);
  for (const collection of collections) {
    const category = collection.dataset.category;
    const sources = shops
      .filter((shop) =>
        shop.category_path.some((entry) => entry.code === category),
      )
      .flatMap((shop) => shop.posts.map((post) => post.media_url));
    const images = [...collection.querySelectorAll("img")];
    assert.ok(images.length > 0);
    assert.ok(
      images.every((image) => sources.includes(image.getAttribute("src"))),
      "Collection photography must come from shops in its own category",
    );
  }

  quickCategories[0].click();
  await settlePage();
  assert.equal(discovery.hidden, true);
  assert.equal(
    new URL(requests.at(-1).path, "https://kahoo.test").searchParams.get(
      "category",
    ),
    "67000000",
  );
  assert.equal(document.querySelectorAll("#shop-grid article").length, 1);
  const search = document.querySelector("#search-input");
  search.value = "کفش";
  document
    .querySelector("#search-form")
    .dispatchEvent(new window.Event("submit", { cancelable: true }));
  await settlePage();
  const filtered = new URL(requests.at(-1).path, "https://kahoo.test");
  assert.equal(filtered.searchParams.get("q"), "کفش");
  assert.equal(filtered.searchParams.get("category"), "67000000");
  assert.equal(discovery.hidden, true);

  document.querySelector("#clear-filters").click();
  await settlePage();
  assert.equal(search.value, "");
  assert.equal(
    new URL(requests.at(-1).path, "https://kahoo.test").searchParams.size,
    0,
  );
  assert.equal(discovery.hidden, false);
  assert.equal(document.querySelectorAll("#shop-grid article").length, 2);
  assert.equal(document.querySelector("#clear-filters").hidden, true);

  document
    .querySelector('#discovery-grid button[data-category="73000000"]')
    .click();
  await settlePage();
  assert.equal(
    new URL(requests.at(-1).path, "https://kahoo.test").searchParams.get(
      "category",
    ),
    "73000000",
  );
  assert.equal(discovery.hidden, true);
  assert.equal(window.localStorage.getItem("kahoo_saved_merchants"), null);
});

test("discovery omits empty categories and does not invent shop imagery", async (t) => {
  for (const shops of [[], [{ ...merchant, posts: [] }]]) {
    await t.test(
      shops.length ? "shop without posts" : "empty catalog",
      async (t) => {
        const { dom, window } = await loadPage(
          "index.html",
          "catalog.js",
          (path) => (path === "/api/categories" ? categoryTree : shops),
        );
        t.after(() => dom.window.close());
        const document = window.document;
        assert.equal(document.querySelector("#discovery").hidden, true);
        assert.equal(
          document.querySelectorAll("#discovery-grid img").length,
          0,
        );
        assert.equal(
          document.querySelector(
            '#quick-categories button[data-category="44000000"]',
          ),
          null,
        );
        assert.equal(
          document.querySelectorAll("#shop-grid .kahoo-loader").length,
          0,
        );
        if (shops.length) {
          const preview = document.querySelector(".post-grid.no-posts");
          assert.ok(preview.textContent.trim());
          assert.equal(preview.querySelector("img"), null);
          assert.equal(document.querySelector("#empty-state").hidden, true);
        } else {
          assert.equal(document.querySelector("#empty-state").hidden, false);
        }
      },
    );
  }
});

test("quick category navigation stays bounded and touch menu opens after focus", async (t) => {
  const categories = [
    categoryTree[2],
    ...Array.from({ length: 8 }, (_, index) => ({
      ...categoryTree[0],
      code: `category-${index}`,
      label_fa: `دسته ${index}`,
      children: [],
    })),
  ];
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) =>
    path === "/api/categories" ? categories : [],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  assert.equal(
    document.querySelectorAll("#quick-categories button[data-category]").length,
    6,
  );
  assert.equal(
    document.querySelector(
      '#quick-categories button[data-category="44000000"]',
    ),
    null,
  );
  const trigger = document.querySelector("#category-menu-trigger");
  const popover = document.querySelector("#category-popover");
  trigger.focus();
  trigger.click();
  assert.equal(popover.hidden, false);
  assert.equal(trigger.getAttribute("aria-expanded"), "true");
  document.dispatchEvent(
    new window.KeyboardEvent("keydown", { key: "Escape" }),
  );
  assert.equal(popover.hidden, true);
  assert.equal(trigger.getAttribute("aria-expanded"), "false");
});

test("touch category expansion keeps the menu open and preserves the focused parent", async (t) => {
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) =>
    path === "/api/categories" ? categoryTree : [merchant],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  document.querySelector("#category-menu-trigger").click();
  const parent = document.querySelector(
    '.tree-select[data-category="67000000"]',
  );
  parent.focus();
  parent.click();
  assert.equal(document.querySelector("#category-popover").hidden, false);
  assert.equal(document.querySelectorAll(".tree-column").length, 2);
  assert.equal(document.activeElement.dataset.category, "67000000");
  const child = document.querySelector(
    '.tree-select[data-category="67010300"]',
  );
  child.focus();
  child.click();
  await settlePage();
  assert.equal(document.querySelector("#category-popover").hidden, true);
  assert.equal(document.activeElement.id, "category-menu-trigger");
  assert.equal(document.querySelector("#result-title").textContent, "کفش");
});

test("desktop category branches keep focus and allow choosing a child without selecting its parent", async (t) => {
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => (path === "/api/categories" ? categoryTree : [merchant]),
    {},
    { finePointer: true },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  const trigger = document.querySelector("#category-menu-trigger");
  const popover = document.querySelector("#category-popover");
  trigger.focus();
  trigger.click();
  const branch = document.querySelector('[data-branch="67000000"]');
  assert.equal(branch.tagName, "BUTTON");
  assert.ok(branch.getAttribute("aria-label"));
  branch.focus();
  branch.click();
  const expanded = document.querySelector('[data-branch="67000000"]');
  assert.equal(expanded.getAttribute("aria-expanded"), "true");
  assert.equal(document.activeElement, expanded);
  assert.equal(
    requests.filter((request) => request.path.startsWith("/api/merchants?"))
      .length,
    1,
  );
  document.dispatchEvent(
    new window.KeyboardEvent("keydown", { key: "Escape" }),
  );
  assert.equal(popover.hidden, true);
  assert.equal(document.activeElement, trigger);

  trigger.click();
  const child = [...document.querySelectorAll("#category-tree button")].find(
    (button) => button.textContent === "کفش",
  );
  assert.ok(child);
  child.focus();
  child.click();
  await settlePage();
  assert.equal(
    new URL(requests.at(-1).path, "https://kahoo.test").searchParams.get(
      "category",
    ),
    "67010300",
  );
  assert.equal(popover.hidden, true);
  assert.equal(document.activeElement, trigger);
});

test("a failed catalog request leaves a retry that restores browsing", async (t) => {
  let failed = true;
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => {
      if (path === "/api/categories") return categoryTree;
      if (path.startsWith("/api/merchants?")) {
        if (failed) throw new Error("Catalog unavailable");
        return [merchant];
      }
      return [];
    },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  assert.equal(document.querySelectorAll("#shop-grid .kahoo-loader").length, 0);
  assert.equal(document.querySelector("#empty-state").hidden, false);
  assert.equal(document.querySelector("#discovery").hidden, true);
  const retry = document.querySelector("#retry-shops");
  assert.ok(retry);
  failed = false;
  retry.click();
  await settlePage();
  assert.equal(
    requests.filter((request) => request.path.startsWith("/api/merchants?"))
      .length,
    2,
  );
  assert.equal(document.querySelectorAll("#shop-grid article").length, 1);
  assert.equal(document.querySelector("#empty-state").hidden, true);
  assert.equal(document.querySelector("#discovery").hidden, false);
});

test("saved page presents empty collections", async (t) => {
  const { dom, window } = await loadPage("saved.html", "saved.js", () => ({}));
  t.after(() => dom.window.close());
  assert.equal(
    window.document.querySelectorAll(".empty-state.compact").length,
    2,
  );
});

test("saved cards import browser records and delete only the selected database item", async (t) => {
  const { dom, window, serverSaved } = await loadPage(
    "saved.html",
    "saved.js",
    () => ({}),
    {
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
    },
  );
  t.after(() => dom.window.close());
  assert.equal(window.document.querySelectorAll(".saved-merchant").length, 1);
  assert.equal(window.document.querySelectorAll(".saved-post").length, 2);
  window.document.querySelector(".saved-post .remove-button").click();
  await settlePage();
  assert.equal(window.document.querySelectorAll(".saved-post").length, 1);
  assert.equal(serverSaved.posts[0].key, "post-2");
  window.document.querySelector(".saved-merchant .remove-button").click();
  await settlePage();
  assert.equal(serverSaved.merchants.length, 0);
  assert.equal(window.localStorage.getItem("kahoo_saved_merchants"), null);
});

test("failed legacy import preserves browser records and retry imports canonical references", async (t) => {
  let failed = true;
  const legacy = [{ id: 1, key: "1", name: "untrusted browser name" }];
  const { dom, window, requests } = await loadPage(
    "saved.html",
    "saved.js",
    () => ({}),
    { kahoo_saved_merchants: legacy, kahoo_user: { display_name: "old demo" } },
    {
      savedAPI: (path) => {
        if (failed && path === "/api/saved/import") throw new Error("offline");
      },
    },
  );
  t.after(() => dom.window.close());
  assert.equal(
    window.localStorage.getItem("kahoo_saved_merchants"),
    JSON.stringify(legacy),
  );
  assert.equal(window.localStorage.getItem("kahoo_user"), null);
  assert.ok(window.document.querySelector(".saved-status .remove-button"));
  failed = false;
  window.document.querySelector(".saved-status .remove-button").click();
  await settlePage();
  assert.equal(window.localStorage.getItem("kahoo_saved_merchants"), null);
  assert.equal(
    window.document.querySelector(".merchant-copy b").textContent,
    merchant.name,
  );
  const imports = requests.filter(
    (request) => request.path === "/api/saved/import",
  );
  assert.deepEqual(JSON.parse(imports.at(-1).options.body), {
    merchants: [{ id: 1 }],
  });
});

test("partial import retains deleted references including legacy permalink-only posts", async (t) => {
  const missingPost = {
    key: "removed",
    permalink: "https://instagram.com/p/removed/",
  };
  const { dom, window } = await loadPage(
    "saved.html",
    "saved.js",
    () => ({}),
    {
      kahoo_saved_merchants: [{ id: 1 }, { id: 99 }],
      kahoo_saved_posts: [missingPost],
    },
    {
      savedAPI: (path, options, state) => {
        if (path !== "/api/saved/import") return;
        const payload = JSON.parse(options.body);
        if (payload.merchants) state.merchants.push({ ...merchant, key: "1" });
        return {
          ...state,
          skipped_merchants: [{ id: 99 }],
          skipped_posts: [
            { merchant_id: null, key: null, permalink: missingPost.permalink },
          ],
        };
      },
    },
  );
  t.after(() => dom.window.close());
  assert.deepEqual(
    JSON.parse(window.localStorage.getItem("kahoo_saved_merchants")),
    [{ id: 99 }],
  );
  assert.deepEqual(
    JSON.parse(window.localStorage.getItem("kahoo_saved_posts")),
    [missingPost],
  );
  assert.equal(window.document.querySelectorAll(".saved-merchant").length, 1);
  assert.ok(window.document.querySelector(".saved-status .remove-button"));
});

test("browsers without cross-tab locks keep legacy copies after server import", async (t) => {
  const legacy = [{ id: 1 }];
  const { dom, window, serverSaved } = await loadPage(
    "saved.html",
    "saved.js",
    () => ({}),
    { kahoo_saved_merchants: legacy },
    { coordinateTabs: false },
  );
  t.after(() => dom.window.close());
  assert.equal(serverSaved.merchants.length, 1);
  assert.equal(
    window.localStorage.getItem("kahoo_saved_merchants"),
    JSON.stringify(legacy),
  );
  assert.equal(window.document.querySelectorAll(".saved-merchant").length, 1);
  window.document.querySelector(".saved-merchant .remove-button").click();
  await settlePage();
  assert.equal(window.localStorage.getItem("kahoo_saved_merchants"), null);
  await window.refreshSaved();
  assert.equal(serverSaved.merchants.length, 0);
});

test("post save state uses merchant and collection together and failed writes can retry", async (t) => {
  let failed = true;
  const { dom, window, serverSaved } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => (path === "/api/merchants/1" ? merchant : []),
    {
      kahoo_saved_posts: [{ merchant_id: 2, key: "post-1" }],
    },
    {
      savedAPI: (path, options) => {
        if (failed && options.method === "PUT") throw new Error("offline");
      },
    },
  );
  t.after(() => dom.window.close());
  await window.openMerchantProfile(1);
  const button = window.document.querySelector(".post-save");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  button.click();
  await settlePage();
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(button.disabled, false);
  assert.match(
    window.document.querySelector("#save-status").textContent,
    /دوباره/,
  );
  failed = false;
  button.click();
  await settlePage();
  assert.equal(button.getAttribute("aria-pressed"), "true");
  assert.equal(serverSaved.posts.length, 2);
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
