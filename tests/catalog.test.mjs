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
    browseMode = "shops",
    savedAPI = () => undefined,
    sessionUser = null,
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
        ? { session_id: "server-session", user: sessionUser }
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
  if (script === "catalog.js" && browseMode === "products")
    window.document.querySelector('[data-browse-mode="products"]').click();
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

test("shop recommendations validate a handle, import it, and open the saved shop", async () => {
  const { window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => {
      if (path === "/api/categories") return categoryTree;
      if (path === "/api/merchants/recommend")
        return {
          created: true,
          merchant_id: 1,
          name: merchant.name,
          handle: merchant.handle,
        };
      if (path === "/api/merchants/1") return merchant;
      return [merchant];
    },
  );
  const doc = window.document;
  doc.querySelector("[data-open-recommend]").click();
  assert.equal(doc.querySelector("#recommend-dialog").open, true);
  const input = doc.querySelector("#recommend-handle");
  const submit = () =>
    doc
      .querySelector("#recommend-form")
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      );
  input.value = "bad/id";
  submit();
  assert.match(
    doc.querySelector("#recommend-status").textContent,
    /آیدی معتبر/,
  );
  assert.equal(
    requests.filter((request) => request.path === "/api/merchants/recommend")
      .length,
    0,
  );
  input.value = " Shop ";
  submit();
  assert.equal(doc.querySelector(".recommend-submit").disabled, true);
  await new Promise((resolve) => setImmediate(resolve));
  const request = requests.find(
    (request) => request.path === "/api/merchants/recommend",
  );
  assert.deepEqual(JSON.parse(request.options.body), { identifier: "@shop" });
  assert.equal(request.options.headers.get("X-Kahoo-Saved"), "1");
  assert.equal(doc.querySelector("#recommend-done").hidden, false);
  assert.equal(doc.querySelector(".recommend-submit").disabled, false);
  doc.querySelector("#recommend-view").click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(doc.querySelector("#recommend-dialog").open, false);
  assert.equal(doc.querySelector("#merchant-dialog").open, true);
  window.close();
});

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

test("quick category navigation exposes all populated categories and opens by click", async (t) => {
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
    8,
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

test("touch category expansion uses a separate button and preserves focus", async (t) => {
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) =>
    path === "/api/categories" ? categoryTree : [merchant],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  document.querySelector("#category-menu-trigger").click();
  const parent = document.querySelector('[data-branch="67000000"]');
  parent.focus();
  parent.click();
  assert.equal(document.querySelector("#category-popover").hidden, false);
  assert.equal(document.querySelectorAll(".tree-children").length, 1);
  assert.equal(document.activeElement.dataset.branch, "67000000");
  const child = document.querySelector(
    '.tree-select[data-category="67010300"]',
  );
  child.focus();
  child.click();
  await settlePage();
  assert.equal(document.querySelector("#category-popover").hidden, false);
  assert.equal(document.activeElement.dataset.category, "67010300");
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
  assert.equal(popover.hidden, false);
  assert.equal(document.activeElement.dataset.category, "67010300");
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

test("admin product assessment shows evidence and unknowns, saves notes and retries extraction", async (t) => {
  const product = {
    id: 42,
    collection_key: "carousel-1",
    merchant_name: "فروشگاه",
    merchant_handle: "@shop",
    caption: "<script>unsafe()</script> کفش آبی",
    permalink: "https://instagram.com/p/abc/",
    images: [],
    status: "ready",
    review_status: "pending",
    review_note: "",
    model: "vision-model",
    taxonomy_version: "2026-08",
    attempts: 1,
    processed_at: "2026-10-10T10:00:00Z",
    error: null,
    result: {
      title: "<img src=x onerror=unsafe()> کفش",
      category_code: "aa-1",
      category_name: "Apparel > Shoes",
      confidence: 0.9,
      evidence: "کپشن: کفش آبی",
      description: "کفش آبی",
      warnings: [],
      attributes: [
        {
          name: "Color",
          handle: "color",
          value: null,
          values: ["Blue"],
          confidence: 0.8,
          source: "image",
          evidence: "رنگ آبی در تصویر ۲",
        },
        {
          name: "Material",
          handle: "material",
          value: null,
          values: [],
          confidence: 0,
          source: "unknown",
          evidence: null,
        },
      ],
    },
  };
  const { dom, window, requests } = await loadPage(
    "admin.html",
    "admin.js",
    (path, options) => {
      if (path.startsWith("/api/admin/products?"))
        return { configured: true, total: 1, items: [product] };
      if (path.endsWith("/review")) {
        const review = JSON.parse(options.body);
        product.review_status = review.status;
        product.review_note = review.note;
        return product;
      }
      if (path.endsWith("/retry")) {
        product.status = "pending";
        product.result = null;
        return product;
      }
      if (path.startsWith("/api/admin/merchants"))
        return { total: 0, items: [] };
      return [];
    },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  assert.equal(document.querySelectorAll(".product-review-card").length, 1);
  assert.equal(
    document.querySelectorAll(
      ".product-review-card script, .product-review-card img",
    ).length,
    0,
  );
  assert.match(
    document.querySelector(".product-source-caption").textContent,
    /<script>/,
  );
  assert.match(
    document.querySelector(".product-attributes").textContent,
    /Blue/,
  );
  assert.match(
    document.querySelector(".product-attributes").textContent,
    /نامشخص/,
  );
  assert.match(
    document.querySelector(".product-provenance").textContent,
    /vision-model/,
  );
  document.querySelector("#admin-token").value = "admin-secret";
  document.querySelector(".product-assessment textarea").value = "رنگ درست است";
  document.querySelector('[data-product-action="approved"]').click();
  await settlePage();
  const review = requests.find((request) => request.path.endsWith("/review"));
  assert.deepEqual(JSON.parse(review.options.body), {
    status: "approved",
    note: "رنگ درست است",
  });
  assert.equal(
    review.options.headers.get("X-Kahoo-Admin-Token"),
    "admin-secret",
  );
  assert.match(
    document.querySelector(".product-review-card summary").textContent,
    /تأییدشده/,
  );
  document.querySelector('[data-product-action="retry"]').click();
  await settlePage();
  assert.match(
    document.querySelector(".product-review-card summary").textContent,
    /در صف/,
  );
  assert.equal(
    document.querySelector('[data-product-action="approved"]').disabled,
    true,
  );
  document.querySelector("#product-status").value = "pending";
  document
    .querySelector("#product-status")
    .dispatchEvent(new window.Event("change"));
  await settlePage();
  assert.ok(
    requests.some((request) => request.path.includes("status=pending")),
  );
});

test("product browsing alternates shops, saves directly and retains filters across views", async (t) => {
  const { dom, window, requests, serverSaved } = await loadPage(
    "index.html",
    "catalog.js",
    (path) => {
      if (path === "/api/categories") return categoryTree;
      if (path.includes("category=67000000")) return [merchant];
      return [merchant, homeMerchant];
    },
    {},
    { browseMode: "products" },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  const products = [...document.querySelectorAll(".product-card")];
  assert.equal(products.length, 8);
  assert.deepEqual(
    products.map((card) => card.dataset.merchant),
    ["1", "2", "1", "2", "1", "2", "1", "2"],
  );
  assert.equal(
    products[0].querySelector("a").href,
    merchant.posts[0].permalink,
  );
  products[0].querySelector(".post-save").click();
  await settlePage();
  assert.equal(serverSaved.posts[0].key, "post-1");
  assert.equal(serverSaved.posts[0].merchant_id, 1);
  assert.equal(
    products[0].querySelector(".post-save").getAttribute("aria-pressed"),
    "true",
  );
  document
    .querySelector('#quick-categories [data-category="67000000"]')
    .click();
  await settlePage();
  const requestCount = requests.length;
  document.querySelector('[data-browse-mode="shops"]').click();
  assert.equal(document.querySelectorAll(".shop-card").length, 1);
  assert.equal(document.querySelector("#result-title").textContent, "پوشاک");
  document.querySelector('[data-browse-mode="products"]').click();
  assert.equal(requests.length, requestCount);
  assert.equal(document.querySelectorAll(".product-card").length, 4);
});

test("product feed handles shops without posts and a parent category selects on the first tap", async (t) => {
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) =>
      path === "/api/categories" ? categoryTree : [{ ...merchant, posts: [] }],
    {},
    { browseMode: "products", finePointer: true },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  assert.equal(document.querySelector("#empty-state").hidden, false);
  document.querySelector("#category-menu-trigger").click();
  document.querySelector('.tree-select[data-category="67000000"]').click();
  await settlePage();
  assert.equal(document.querySelector("#category-popover").hidden, false);
  assert.ok(
    requests.some(
      (request) => request.path === "/api/merchants?category=67000000",
    ),
  );
  document.querySelector('[data-browse-mode="shops"]').click();
  assert.equal(document.querySelectorAll(".shop-card").length, 1);
  assert.equal(document.querySelector("#empty-state").hidden, true);
});

test("shops are the default and shop totals and the old subtitle are omitted", async (t) => {
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) =>
    path === "/api/categories" ? categoryTree : [merchant, homeMerchant],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  assert.equal(document.querySelectorAll(".shop-card").length, 2);
  assert.equal(document.querySelectorAll(".product-card").length, 0);
  assert.equal(
    document
      .querySelector('[data-browse-mode="shops"]')
      .getAttribute("aria-pressed"),
    "true",
  );
  assert.equal(document.querySelector("#result-count").hidden, true);
  assert.equal(document.querySelector("#result-count").textContent, "");
  assert.equal(document.querySelector("#result-context"), null);
  assert.equal(document.querySelector(".collection-total"), null);
  assert.equal(document.querySelector("#quick-categories small"), null);
  assert.equal(
    document
      .querySelector(".header-actions [data-open-connect]")
      .textContent.trim(),
    "برای فروشگاه‌ها",
  );
  assert.equal(document.querySelector(".browse-nav [data-open-connect]"), null);
  assert.equal(
    document
      .querySelector("#browse-heading")
      .textContent.replace(/\s+/g, " ")
      .trim(),
    "کاهو، کشف چیزهای دوست‌داشتنی",
  );
  document.querySelector('[data-browse-mode="products"]').click();
  assert.equal(document.querySelector("#result-count").hidden, false);
  document.querySelector('[data-browse-mode="shops"]').click();
  assert.equal(document.querySelector("#result-count").hidden, true);
});

test("guest bookmark navigation opens login from the header and footer", async (t) => {
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    () => [],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  for (const link of document.querySelectorAll('a[href="/saved.html"]')) {
    const event = new window.MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(event);
    assert.equal(event.defaultPrevented, true);
    await settlePage();
    assert.equal(document.querySelector("#login-dialog").open, true);
    assert.equal(document.activeElement.id, "phone-input");
    assert.equal(window.location.pathname, "/");
    document.querySelector("#login-dialog").close();
  }
  assert.equal(
    requests.filter(
      (request) =>
        request.path === "/api/analytics/event" &&
        JSON.parse(request.options.body).event_type === "login_started",
    ).length,
    2,
  );
});

test("signed-in bookmark navigation follows the saved page link", async (t) => {
  const { dom, window } = await loadPage(
    "index.html",
    "catalog.js",
    () => [],
    {},
    {
      sessionUser: { id: 1, phone: "09121234567" },
    },
  );
  t.after(() => dom.window.close());
  const document = window.document;
  const link = document.querySelector(".saved-link");
  let intercepted;
  link.addEventListener("click", (event) => {
    intercepted = event.defaultPrevented;
    event.preventDefault(); // Avoid jsdom navigation after checking the app handler.
  });
  link.click();
  await settlePage();
  assert.equal(intercepted, false);
  assert.equal(link.pathname, "/saved.html");
  assert.equal(document.querySelector("#login-dialog").open, false);
  assert.equal(document.querySelector("#login-trigger").textContent, "حساب من");
});

test("category filters select multiple branches, toggle independently and clear together", async (t) => {
  const { dom, window, requests } = await loadPage(
    "index.html",
    "catalog.js",
    (path) =>
      path === "/api/categories" ? categoryTree : [merchant, homeMerchant],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  document.querySelector("#category-menu-trigger").click();
  const select = (code) =>
    document.querySelector(`.tree-select[data-category="${code}"]`);
  select("67000000").focus();
  select("67000000").click();
  await settlePage();
  select("73000000").focus();
  select("73000000").click();
  await settlePage();
  const lastCategories = () =>
    new URL(requests.at(-1).path, "https://kahoo.test").searchParams.getAll(
      "category",
    );
  assert.deepEqual(lastCategories(), ["67000000", "73000000"]);
  assert.equal(select("67000000").getAttribute("aria-pressed"), "true");
  assert.equal(select("73000000").getAttribute("aria-pressed"), "true");
  assert.equal(document.querySelector("#category-popover").hidden, false);
  select("67000000").click();
  await settlePage();
  assert.deepEqual(lastCategories(), ["73000000"]);
  assert.equal(select("67000000").getAttribute("aria-pressed"), "false");
  document.querySelector("#reset-category").click();
  await settlePage();
  assert.deepEqual(lastCategories(), []);
});

test("quick categories show selected subcategories and restore suggestions when cleared", async (t) => {
  const categories = [
    ...categoryTree,
    {
      code: "50000000",
      level: 1,
      label_fa: "مصالح ساختمان",
      count: 0,
      children: [],
    },
  ];
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) =>
    path === "/api/categories" ? categories : [merchant, homeMerchant],
  );
  t.after(() => dom.window.close());
  const document = window.document;
  const chips = () => [
    ...document.querySelectorAll("#quick-categories [data-category]"),
  ];
  const codes = () => chips().map((button) => button.dataset.category);
  assert.deepEqual(codes(), ["67000000", "73000000"]);
  document.querySelector('#category-tree [data-branch="67000000"]').click();
  document.querySelector('.tree-select[data-category="67010300"]').click();
  assert.deepEqual(codes(), ["67010300"]);
  await settlePage();
  document.querySelector('#category-tree [data-branch="73000000"]').click();
  document.querySelector('.tree-select[data-category="73010300"]').click();
  await settlePage();
  assert.deepEqual(codes(), ["67010300", "73010300"]);
  assert.deepEqual(
    chips().map((button) => button.textContent),
    ["کفش", "دکور"],
  );
  assert.ok(
    chips().every((button) => button.getAttribute("aria-pressed") === "true"),
  );
  document.querySelector('.tree-select[data-category="50000000"]').click();
  await settlePage();
  assert.deepEqual(codes(), ["67010300", "73010300", "50000000"]);
  assert.deepEqual(
    [...document.querySelectorAll("#quick-categories button")].map(
      (button) => button.textContent,
    ),
    ["کفش", "دکور", "مصالح ساختمان"],
  );
  chips()[2].click();
  await settlePage();
  chips()[0].click();
  await settlePage();
  assert.deepEqual(codes(), ["73010300"]);
  chips()[0].click();
  await settlePage();
  assert.deepEqual(codes(), ["67000000", "73000000"]);
  chips()[0].click();
  await settlePage();
  assert.deepEqual(codes(), ["67000000"]);
  document.querySelector("#reset-category").click();
  assert.deepEqual(codes(), ["67000000", "73000000"]);
  await settlePage();
});

test("follower badge belongs to shop identity and preserves missing and zero counts", async (t) => {
  const { dom, window } = await loadPage("index.html", "catalog.js", (path) =>
    path === "/api/categories"
      ? categoryTree
      : [
          { ...merchant, followers_count: 1234567, following_count: 1234 },
          { ...merchant, id: 2, followers_count: 0, following_count: 0 },
          { ...merchant, id: 3, followers_count: null, following_count: null },
        ],
  );
  t.after(() => dom.window.close());
  const badges = [
    ...window.document.querySelectorAll(".shop-info .shop-activity"),
  ];
  assert.equal(badges.length, 3);
  assert.ok(badges[0].textContent.includes("دنبال‌کننده"));
  assert.equal(badges[0].title, "۱٬۲۳۴٬۵۶۷ دنبال‌کننده");
  const following = [...window.document.querySelectorAll(".shop-following")];
  assert.equal(following[0].title, "۱٬۲۳۴ دنبال‌شونده");
  assert.equal(following[0].hidden, false);
  assert.equal(following[1].textContent, "۰ دنبال‌شونده");
  assert.equal(following[2].hidden, true);
  assert.equal(badges[0].hidden, false);
  assert.equal(badges[1].hidden, false);
  assert.equal(badges[2].hidden, true);
  assert.equal(
    window.document.querySelectorAll(".shop-card > .shop-activity").length,
    0,
  );
});
