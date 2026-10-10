import {
  api,
  escapeHtml,
  faNumber,
  initializeSession,
  isSaved,
  setSaved,
} from "./shared.js";

const treeElement = document.querySelector("#category-tree"),
  shopGrid = document.querySelector("#shop-grid"),
  template = document.querySelector("#shop-card-template"),
  resultTitle = document.querySelector("#result-title"),
  emptyState = document.querySelector("#empty-state"),
  emptySuggestions = document.querySelector("#empty-suggestions"),
  searchForm = document.querySelector("#search-form"),
  searchInput = document.querySelector("#search-input"),
  searchSuggestions = document.querySelector("#search-suggestions"),
  categoryDropdown = document.querySelector("#categories"),
  categoryMenu = document.querySelector("#category-menu-trigger"),
  categoryMenuLabel = document.querySelector("#category-menu-label"),
  categoryPopover = document.querySelector("#category-popover");
let renderingTree = false,
  categoryTree = [],
  shops = [],
  query = "",
  browseMode = "shops";
const expanded = new Set(),
  selectedCategories = new Map();
let reelStops = [];
const loaderMarkup = (label) =>
  `<div class="kahoo-loader catalog-loader" role="status"><span>${label}</span></div>`;

function track(event_type, details = {}) {
  initializeSession()
    .then(() =>
      api("/api/analytics/event", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type,
          query: "",
          category_code: "",
          merchant_id: 0,
          result_count: 0,
          ...details,
        }),
      }),
    )
    .catch(() => {});
}

function collapseBranch(node) {
  expanded.delete(node.code);
  node.children.forEach(collapseBranch);
}
function revealBranch(node, siblings) {
  if (!node.children.length || expanded.has(node.code)) return;
  siblings.filter((sibling) => sibling !== node).forEach(collapseBranch);
  expanded.add(node.code);
  renderTree();
}

function treeToggle(node, siblings) {
  const toggle = document.createElement(
    node.children.length ? "button" : "span",
  );
  toggle.className = `tree-toggle${node.children.length ? "" : " empty"}`;
  if (!node.children.length) {
    toggle.setAttribute("aria-hidden", "true");
    return toggle;
  }
  toggle.type = "button";
  toggle.dataset.branch = node.code;
  toggle.setAttribute("aria-label", `زیرگروه‌های ${node.label_fa}`);
  toggle.setAttribute("aria-expanded", String(expanded.has(node.code)));
  toggle.addEventListener("click", () => {
    if (expanded.has(node.code)) {
      collapseBranch(node);
      renderTree();
    } else revealBranch(node, siblings);
    [...treeElement.querySelectorAll("[data-branch]")]
      .find((button) => button.dataset.branch === node.code)
      ?.focus();
  });
  return toggle;
}

function treeNode(node, siblings) {
  const item = document.createElement("li");
  item.className = `tree-item level-${node.level}`;
  const row = document.createElement("div");
  row.className = `tree-node${selectedCategories.has(node.code) ? " selected" : ""}${expanded.has(node.code) ? " active" : ""}`;
  const toggle = treeToggle(node, siblings);
  const select = document.createElement("button");
  select.className = "tree-select";
  select.dataset.category = node.code;
  select.type = "button";
  select.setAttribute(
    "aria-pressed",
    String(selectedCategories.has(node.code)),
  );
  select.innerHTML = `<span>${escapeHtml(node.label_fa)}</span>`;
  select.title = `GS1 ${node.code}`;
  select.addEventListener("click", () => selectCategory(node));
  row.append(select, toggle);
  item.append(row);
  if (expanded.has(node.code) && node.children.length) {
    const group = document.createElement("ul");
    group.className = "tree-children";
    node.children.forEach((child) =>
      group.append(treeNode(child, node.children)),
    );
    item.append(group);
  }
  return item;
}

function renderTree() {
  const focused = document.activeElement,
    focusKey = focused.dataset.branch ? "branch" : "category",
    focusValue = focused.dataset[focusKey];
  renderingTree = true;
  treeElement.innerHTML = "";
  const list = document.createElement("ul");
  list.className = "tree-column";
  categoryTree.forEach((node) => list.append(treeNode(node, categoryTree)));
  treeElement.append(list);
  categoryMenuLabel.textContent = selectedCategories.size
    ? [...selectedCategories.values()].join("، ")
    : "دسته‌بندی محصولات";
  if (focusValue)
    [...treeElement.querySelectorAll(`[data-${focusKey}]`)]
      .find((button) => button.dataset[focusKey] === focusValue)
      ?.focus();
  renderingTree = false;
}
function openCategoryMenu() {
  categoryPopover.style.setProperty(
    "--category-top",
    `${Math.round(categoryDropdown.getBoundingClientRect().bottom) + 1}px`,
  );
  categoryPopover.hidden = false;
  categoryMenu.setAttribute("aria-expanded", "true");
}
function closeCategoryMenu() {
  if (categoryPopover.contains(document.activeElement)) categoryMenu.focus();
  categoryPopover.hidden = true;
  categoryMenu.setAttribute("aria-expanded", "false");
}
categoryDropdown.addEventListener("focusout", (event) => {
  if (!renderingTree && !categoryDropdown.contains(event.relatedTarget))
    closeCategoryMenu();
});
categoryMenu.addEventListener("click", () => {
  categoryPopover.hidden ? openCategoryMenu() : closeCategoryMenu();
});
document.addEventListener("click", (event) => {
  if (!event.composedPath().includes(categoryDropdown)) closeCategoryMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeCategoryMenu();
});
function configureShopNavigation(article, shop) {
  article.tabIndex = 0;
  article.setAttribute("role", "button");
  article.setAttribute("aria-label", `نمایش اطلاعات ${shop.name}`);
  article.addEventListener("click", (event) => {
    if (!event.target.closest("a,button")) openMerchantProfile(shop.id);
  });
  article.addEventListener("keydown", (event) => {
    if (
      event.target === article &&
      (event.key === "Enter" || event.key === " ")
    ) {
      event.preventDefault();
      openMerchantProfile(shop.id);
    }
  });
}

function appendShopAvatar(avatar, shop) {
  if (shop.avatar_url) {
    const avatarImage = document.createElement("img");
    avatarImage.src = shop.avatar_url;
    avatarImage.alt = `تصویر پروفایل ${shop.name}`;
    avatarImage.loading = "lazy";
    avatarImage.addEventListener("error", () => avatarImage.remove(), {
      once: true,
    });
    avatar.append(avatarImage);
  }
}

function populateShopCard(card, shop) {
  card.querySelector("h3").textContent = shop.name;
  card.querySelector(".shop-copy p").textContent = shop.handle;
  card.querySelector(".shop-description").textContent = shop.description;
  const reason = card.querySelector(".match-reason");
  if (query && shop.match_reason) {
    reason.textContent = shop.match_reason;
    reason.hidden = false;
  }
  card.querySelector(".location").textContent = shop.city;
  card.querySelector(".shop-category").textContent =
    shop.category_label || categoryLabel(shop.category_code);
  populateShopStats(card, shop);
}

const compactNumber = new Intl.NumberFormat("fa-IR", {
  notation: "compact",
  maximumFractionDigits: 1,
});
function populateShopStats(card, shop) {
  const stats = card.querySelector(".shop-social-stats");
  stats.hidden = shop.followers_count == null && shop.following_count == null;
  [
    [".shop-activity", shop.followers_count, "دنبال‌کننده"],
    [".shop-following", shop.following_count, "دنبال‌شونده"],
  ].forEach(([selector, count, label]) => {
    if (count == null) return;
    const badge = card.querySelector(selector);
    badge.textContent = `${compactNumber.format(count)} ${label}`;
    badge.title = `${faNumber(count)} ${label}`;
    badge.setAttribute("aria-label", badge.title);
    badge.hidden = false;
  });
}

function configureShopVisit(card, shop) {
  const visitLink = card.querySelector(".visit-link");
  visitLink.href = shop.instagram_url;
  visitLink.target = "_blank";
  visitLink.addEventListener("click", () =>
    track("merchant_click", {
      merchant_id: shop.id,
      query,
      category_code: [...selectedCategories.keys()][0] || "",
    }),
  );
}

function shopCard(shop, index) {
  const card = template.content.cloneNode(true);
  configureShopNavigation(card.querySelector("article"), shop);
  appendShopAvatar(card.querySelector(".shop-avatar"), shop);
  populateShopCard(card, shop);
  configureShopVisit(card, shop);
  reelStops.push(createPostReel(card.querySelector(".post-grid"), shop, index));
  return card;
}

function productEntries() {
  const entries = shops.flatMap((shop) =>
    shop.posts.map((post, index) => ({ shop, post, index })),
  );
  // Alternate shops by post position so browsing does not form shop blocks.
  return entries.sort((a, b) => a.index - b.index);
}

function productLink(shop, post, index) {
  const link = document.createElement("a");
  link.href = post.permalink;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.setAttribute(
    "aria-label",
    `دیدن پست محصول ${index + 1} از ${shop.name} در اینستاگرام`,
  );
  const image = document.createElement("img");
  image.src = post.media_url;
  image.alt = `پست ${index + 1} · ${shop.category_label || shop.name}`;
  image.loading = "lazy";
  link.append(image);
  if (post.media.length > 1) {
    const badge = document.createElement("span");
    badge.className = "collection-count";
    badge.textContent = `▣ ${faNumber(post.media.length)}`;
    link.append(badge);
  }
  return link;
}

function productCard({ shop, post, index }) {
  const card = document.createElement("article");
  card.className = "product-card";
  card.dataset.merchant = shop.id;
  card.dataset.post = post.key;
  const image = productLink(shop, post, index);
  image.className = "product-image";
  image.addEventListener("click", () =>
    track("merchant_click", { merchant_id: shop.id, query }),
  );
  const copy = document.createElement("div");
  copy.className = "product-copy";
  const label = document.createElement("p");
  label.textContent = shop.category_label || categoryLabel(shop.category_code);
  const source = document.createElement("button");
  source.type = "button";
  source.textContent = shop.name;
  source.setAttribute("aria-label", `نمایش فروشگاه ${shop.name}`);
  source.addEventListener("click", () => openMerchantProfile(shop.id));
  copy.append(label, source);
  card.append(image, postSaveButton(shop, post), copy);
  return card;
}

function renderShops() {
  reelStops.forEach((stop) => stop());
  reelStops = [];
  const products = browseMode === "products",
    entries = products ? productEntries() : shops;
  shopGrid.classList.toggle("product-grid", products);
  shopGrid.replaceChildren(
    ...entries.map((entry, index) =>
      products ? productCard(entry) : shopCard(entry, index),
    ),
  );
  emptyState.hidden = entries.length > 0;
  emptyState.querySelector("h3").textContent = products
    ? "محصولی پیدا نشد"
    : "فروشگاهی پیدا نشد";
  resultTitle.textContent = query
    ? `نتایج «${query}»`
    : [...selectedCategories.values()].join("، ") ||
      (products ? "محصولات برای کشف کردن" : "همه فروشگاه‌ها");
  const count = document.querySelector("#result-count");
  count.hidden = !products;
  count.textContent = products ? `${faNumber(entries.length)} پست محصول` : "";
  document
    .querySelectorAll("[data-browse-mode]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.browseMode === browseMode),
      ),
    );
  renderDiscovery();
}

document.querySelectorAll("[data-browse-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    browseMode = button.dataset.browseMode;
    renderShops();
  });
});

function selectCategory(node) {
  if (selectedCategories.has(node.code)) selectedCategories.delete(node.code);
  else selectedCategories.set(node.code, node.label_fa);
  renderTree();
  renderQuickCategories();
  loadShops();
}

function browseCategories() {
  return categoryTree.filter((node) => node.count > 0);
}

const browseCategoryLabels = Object.freeze({
  "هنر، صنایع دستی و خیاطی": "هنر و دست‌سازها",
  "زیبایی و بهداشت شخصی": "زیبایی و بهداشت",
  "خانه، مبلمان و دکور": "خانه و دکور",
  "آشپزخانه و پذیرایی": "آشپزخانه",
  "لوازم‌التحریر و اداری": "لوازم‌التحریر",
  "اکسسوری شخصی": "اکسسوری",
});

function browseCategoryLabel(node) {
  return browseCategoryLabels[node.label_fa] || node.label_fa;
}

function renderQuickCategories() {
  const navigation = document.querySelector("#quick-categories");
  navigation.replaceChildren();
  if (!selectedCategories.size) {
    const all = document.createElement("button");
    all.type = "button";
    all.textContent = "همه";
    all.classList.add("active");
    all.setAttribute("aria-pressed", "true");
    all.addEventListener("click", () =>
      document.querySelector("#reset-category").click(),
    );
    navigation.append(all);
  }
  const categories = selectedCategories.size
    ? [...selectedCategories].map(([code, label_fa]) => ({ code, label_fa }))
    : browseCategories();
  categories.forEach((node) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.category = node.code;
    button.classList.toggle("active", selectedCategories.has(node.code));
    button.setAttribute(
      "aria-pressed",
      String(selectedCategories.has(node.code)),
    );
    button.innerHTML = `<span>${escapeHtml(selectedCategories.size ? node.label_fa : browseCategoryLabel(node))}</span>`;
    button.addEventListener("click", () => selectCategory(node));
    navigation.append(button);
  });
  navigation.hidden = !navigation.childElementCount;
}

function categoryContains(node, code) {
  return (
    node.code === code ||
    node.children.some((child) => categoryContains(child, code))
  );
}

function categoryLabel(code, nodes = categoryTree) {
  for (const node of nodes) {
    if (node.code === code) return node.label_fa;
    const label = categoryLabel(code, node.children);
    if (label) return label;
  }
  return "";
}

function shopInCategory(shop, node) {
  return (
    categoryContains(node, shop.category_code) ||
    (shop.category_path || []).some(
      (category) => category.code === node.code,
    ) ||
    (shop.categories || []).some((category) =>
      categoryContains(node, category.code),
    )
  );
}

function discoveryCollection(node, merchants) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "discovery-collection";
  button.dataset.category = node.code;
  button.setAttribute("aria-label", `دیدن فروشگاه‌های ${node.label_fa}`);
  const copy = document.createElement("span");
  copy.className = "collection-copy";
  copy.innerHTML = `<span class="eyebrow">در این دسته بگرد</span><span class="collection-title">${escapeHtml(browseCategoryLabel(node))}</span><span class="collection-action">دیدن فروشگاه‌ها</span>`;
  const photos = document.createElement("span");
  photos.className = "collection-photos";
  const candidates = merchants
    .map((shop) => ({ shop, post: shop.posts[0] }))
    .concat(
      merchants.flatMap((shop) =>
        shop.posts.slice(1).map((post) => ({ shop, post })),
      ),
    );
  const images = [
    ...new Map(candidates.map((item) => [item.post.media_url, item])).values(),
  ];
  images.slice(0, 2).forEach(({ shop, post }) => {
    const image = document.createElement("img");
    image.src = post.media_url;
    image.alt = `از پست‌های ${shop.name}`;
    image.loading = "lazy";
    photos.append(image);
  });
  button.append(copy, photos);
  button.addEventListener("click", () => selectCategory(node));
  return button;
}

function renderDiscovery() {
  const filtered = Boolean(query || selectedCategories.size),
    section = document.querySelector("#discovery"),
    grid = document.querySelector("#discovery-grid");
  document.querySelector(".catalog").classList.toggle("is-filtered", filtered);
  document.querySelector("#browse-intro").hidden = filtered;
  document.querySelector("#clear-filters").hidden = !filtered;
  renderQuickCategories();
  grid.replaceChildren();
  if (!filtered && browseMode === "shops") {
    browseCategories().forEach((node) => {
      const merchants = shops.filter(
        (shop) => shopInCategory(shop, node) && shop.posts.length,
      );
      if (merchants.length && grid.childElementCount < 2)
        grid.append(discoveryCollection(node, merchants));
    });
  }
  section.hidden = !grid.childElementCount;
}

function resetFilters() {
  selectedCategories.clear();
  query = "";
  searchInput.value = "";
  clearTimeout(searchTimer);
  clearTimeout(suggestionTimer);
  suggestionRequest += 1;
  suggestionItems = [];
  closeSuggestions();
  renderTree();
  renderQuickCategories();
  closeCategoryMenu();
  loadShops();
}

document
  .querySelector("#clear-filters")
  .addEventListener("click", resetFilters);

const REEL_VISIBLE_POSTS = 3;
const REEL_ANIMATION_MS = 900;
const REEL_RESET_MS = 920;
const REEL_INTERVAL_MS = 5600;
const REEL_STAGGER_MS = 350;

function reelPost(shop, post, position) {
  const postIndex = position % shop.posts.length;
  const button = document.createElement("button");
  button.className = "post";
  button.type = "button";
  button.setAttribute(
    "aria-label",
    `نمایش فروشگاه ${shop.name} و جزئیات پست ${postIndex + 1}`,
  );
  button.addEventListener("click", () => openMerchantProfile(shop.id));
  const image = document.createElement("img");
  image.src = post.media_url;
  image.alt = `تصویر شاخص پست ${postIndex + 1} فروشگاه ${shop.name}`;
  image.loading = "lazy";
  button.append(image);
  return button;
}

class PostReel {
  constructor(posts, shop, index) {
    this.posts = posts;
    this.length = shop.posts.length;
    posts.style.setProperty(
      "--reel-visible",
      Math.min(REEL_VISIBLE_POSTS, this.length),
    );
    this.interval = REEL_INTERVAL_MS + index * REEL_STAGGER_MS;
    this.position = 0;
    this.timer = null;
    this.resetTimer = null;
    this.track = document.createElement("div");
    this.track.className = "post-reel-track";
    posts.setAttribute("aria-label", `آخرین پست‌های ${shop.name}`);
    posts.append(this.track);
    const items =
      this.length > REEL_VISIBLE_POSTS
        ? [...shop.posts, ...shop.posts.slice(0, REEL_VISIBLE_POSTS)]
        : shop.posts;
    items.forEach((post, position) =>
      this.track.append(reelPost(shop, post, position)),
    );
  }

  updateAccess() {
    [...this.track.children].forEach((item, position) => {
      const visible =
        position >= this.position &&
        position < this.position + REEL_VISIBLE_POSTS;
      item.tabIndex = visible ? 0 : -1;
      item.setAttribute("aria-hidden", String(!visible));
    });
  }

  move(animate = true) {
    if (!this.track.childElementCount) return;
    this.track.style.transition = animate
      ? `transform ${REEL_ANIMATION_MS}ms cubic-bezier(.4,0,.2,1)`
      : "none";
    const step =
      this.track.firstElementChild.getBoundingClientRect().width +
      parseFloat(getComputedStyle(this.track).columnGap);
    this.track.style.transform = `translate3d(${-this.position * step}px,0,0)`;
    this.updateAccess();
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
  }

  canStart() {
    return (
      this.length > REEL_VISIBLE_POSTS &&
      !matchMedia("(prefers-reduced-motion: reduce)").matches &&
      !this.timer &&
      !this.posts.matches(":hover") &&
      !this.posts.matches(":focus-within")
    );
  }

  start() {
    if (this.canStart())
      this.timer = setInterval(() => this.advance(), this.interval);
  }

  advance() {
    this.position += 1;
    this.move();
    if (this.position === this.length) {
      clearTimeout(this.resetTimer);
      this.resetTimer = setTimeout(() => {
        this.position = 0;
        this.move(false);
      }, REEL_RESET_MS);
    }
  }

  mount() {
    this.move(false);
    this.start();
    this.posts.addEventListener("mouseenter", () => this.stop());
    this.posts.addEventListener("mouseleave", () => this.start());
    this.posts.addEventListener("focusin", () => this.stop());
    this.posts.addEventListener("focusout", () => this.start());
    const observer = new ResizeObserver(() => this.move(false));
    observer.observe(this.posts);
    return () => {
      this.stop();
      clearTimeout(this.resetTimer);
      observer.disconnect();
    };
  }
}

function createPostReel(posts, shop, index) {
  if (!shop.posts.length) {
    posts.classList.add("no-posts");
    posts.innerHTML =
      "<span>تصویری از پست‌ها در دسترس نیست</span><small>دیدن اطلاعات فروشگاه</small>";
    return () => {};
  }
  return new PostReel(posts, shop, index).mount();
}

const merchantDialog = document.querySelector("#merchant-dialog"),
  merchantDialogLoading = document.querySelector("#merchant-dialog-loading"),
  merchantDialogContent = document.querySelector("#merchant-dialog-content");
function paintSave(button, saved, compact = false) {
  button.classList.toggle("saved", saved);
  button.setAttribute("aria-pressed", String(saved));
  if (button.classList.contains("merchant-save")) {
    const label = saved ? "حذف فروشگاه از ذخیره‌ها" : "ذخیره فروشگاه";
    button.setAttribute("aria-label", label);
    button.title = label;
    return;
  }
  if (compact) {
    button.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg>';
  } else {
    button.textContent = saved ? "ذخیره شده" : "ذخیره";
  }
}
function saveStatus(message) {
  document.querySelector("#catalog-save-status").textContent = message;
  let status = document.querySelector("#save-status");
  if (!status) {
    status = document.createElement("p");
    status.id = "save-status";
    status.setAttribute("role", "status");
    document.querySelector("#detail-posts").before(status);
  }
  status.textContent = message;
}
async function toggleSaved(kind, item, button, compact = false) {
  button.disabled = true;
  saveStatus("");
  try {
    await initializeSession();
    await setSaved(kind, item, !isSaved(kind, item));
    paintSave(button, isSaved(kind, item), compact);
  } catch {
    saveStatus("ذخیره‌ها به‌روز نشدند. دوباره تلاش کن.");
  } finally {
    button.disabled = false;
  }
}
function merchantCategorySummary(merchant) {
  const categoryLabels = (merchant.categories || []).map(
      (category) => category.label,
    ),
    categorySummary = categoryLabels.length
      ? categoryLabels.slice(0, 3).join("، ") +
        (categoryLabels.length > 3
          ? ` +${faNumber(categoryLabels.length - 3)} دسته`
          : "")
      : merchant.category_label || categoryLabel(merchant.category_code);
  return categorySummary;
}

function renderMerchantAvatar(merchant) {
  const avatar = document.querySelector("#detail-avatar");
  avatar.hidden = !merchant.avatar_url;
  if (merchant.avatar_url) {
    avatar.src = merchant.avatar_url;
    avatar.alt = `تصویر پروفایل ${merchant.name}`;
  } else {
    avatar.removeAttribute("src");
  }
  avatar.onerror = () => {
    avatar.hidden = true;
  };
}

function renderMerchantDetails(merchant) {
  document.querySelector("#detail-name").textContent = merchant.name;
  document.querySelector("#detail-handle").textContent = merchant.handle;
  document.querySelector("#detail-meta").textContent = [
    merchantCategorySummary(merchant),
    merchant.city,
  ]
    .filter(Boolean)
    .join(" · ");
  document.querySelector("#detail-bio").textContent =
    merchant.biography || "بیوی اینستاگرام در دسترس نیست";
  const instagram = document.querySelector("#detail-instagram");
  instagram.href = merchant.instagram_url;
  instagram.onclick = () =>
    track("merchant_click", { merchant_id: merchant.id });
  document.querySelector("#detail-sync").textContent =
    merchant.metrics_updated_at
      ? `به‌روزرسانی ${new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium" }).format(new Date(merchant.metrics_updated_at))}`
      : "اطلاعات محدود";
}

function renderMerchantFacts(merchant) {
  const fields = [
    ["followers", merchant.followers_count],
    ["following", merchant.following_count],
    ["former-names", merchant.former_username_count],
  ];
  fields.forEach(([name, value]) => {
    document.querySelector(`#detail-${name}`).textContent =
      value == null ? "در دسترس نیست" : faNumber(value);
  });
  document.querySelector("#detail-created").textContent =
    merchant.account_created_at
      ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium" }).format(
          new Date(merchant.account_created_at),
        )
      : "در دسترس نیست";
  document.querySelector(".merchant-facts").open = false;
}

function configureMerchantSave(merchant) {
  const merchantSave = document.querySelector("#detail-save"),
    merchantItem = {
      key: String(merchant.id),
      id: merchant.id,
      name: merchant.name,
      handle: merchant.handle,
      description: merchant.description,
      avatar_url: merchant.avatar_url,
      instagram_url: merchant.instagram_url,
      city: merchant.city,
    };
  paintSave(merchantSave, isSaved("merchants", merchantItem));
  merchantSave.onclick = () =>
    toggleSaved("merchants", merchantItem, merchantSave);
}

function postImages(merchant, media, index) {
  return media.map((item, mediaIndex) => {
    const image = document.createElement("img");
    image.src = item.media_url;
    image.alt = `تصویر ${mediaIndex + 1} از پست ${index + 1} ${merchant.name}`;
    image.loading = "lazy";
    return image;
  });
}

function collectionThumbnails(images) {
  const thumbnails = document.createElement("span"),
    thumbnailCount = images.length,
    rows = Math.min(3, Math.max(1, Math.round(Math.sqrt(thumbnailCount / 2)))),
    columns = Math.ceil(thumbnailCount / rows);
  thumbnails.className = "collection-thumbnails";
  thumbnails.style.setProperty("--thumbnail-rows", rows);
  thumbnails.style.setProperty("--thumbnail-columns", columns);
  thumbnails.append(...images);
  return thumbnails;
}

function postPreview(merchant, post, index) {
  const preview = document.createElement("span");
  preview.className = `collection-preview count-${Math.min(post.media.length, 4)}`;
  const images = postImages(merchant, post.media, index);
  preview.append(images[0]);
  if (images.length > 1) preview.append(collectionThumbnails(images.slice(1)));
  return preview;
}

function savedPostItem(merchant, post) {
  return {
    key: post.key,
    merchant_id: merchant.id,
    merchant_name: merchant.name,
    permalink: post.permalink,
    media_url: post.media[0].media_url,
    image_count: post.media.length,
  };
}

function postLink(merchant, post, index) {
  const media = post.media;
  const link = document.createElement("a");
  link.href = post.permalink;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.setAttribute(
    "aria-label",
    `پست ${index + 1} از ${merchant.name}${media.length > 1 ? `، مجموعه ${media.length} تصویر` : ""}`,
  );
  link.append(postPreview(merchant, post, index));
  if (media.length > 1) {
    const badge = document.createElement("span");
    badge.className = "collection-count";
    badge.textContent = `▣ ${faNumber(media.length)}`;
    link.append(badge);
  }
  return link;
}

function postSaveButton(merchant, post) {
  const save = document.createElement("button");
  const item = savedPostItem(merchant, post);
  save.type = "button";
  save.className = "post-save";
  save.setAttribute("aria-label", "ذخیره پست");
  paintSave(save, isSaved("posts", item), true);
  save.addEventListener("click", () => toggleSaved("posts", item, save, true));
  return save;
}

function postTile(merchant, post, index) {
  const tile = document.createElement("div");
  tile.className = `saved-post-tile${post.media.length > 1 ? " collection-tile" : ""}`;
  tile.append(postLink(merchant, post, index), postSaveButton(merchant, post));
  return tile;
}

function renderMerchantPosts(merchant) {
  const posts = document.querySelector("#detail-posts");
  posts.replaceChildren(
    ...merchant.posts.map((post, index) => postTile(merchant, post, index)),
  );
  if (!merchant.posts.length) {
    const message = document.createElement("p");
    message.className = "profile-empty";
    message.textContent =
      "پستی در دسترس نیست. پست‌های فروشگاه را در اینستاگرام ببین.";
    posts.append(message);
  }
}

async function openMerchantProfile(merchantId) {
  merchantDialogLoading.innerHTML = loaderMarkup("در حال دریافت فروشگاه");
  merchantDialogLoading.hidden = false;
  merchantDialogContent.hidden = true;
  merchantDialog.showModal();
  try {
    const [merchant] = await Promise.all([
      api(`/api/merchants/${merchantId}`),
      initializeSession().catch(() => null),
    ]);
    saveStatus("");
    renderMerchantAvatar(merchant);
    renderMerchantDetails(merchant);
    renderMerchantFacts(merchant);
    configureMerchantSave(merchant);
    renderMerchantPosts(merchant);
    merchantDialogLoading.hidden = true;
    merchantDialogContent.hidden = false;
  } catch {
    merchantDialogLoading.textContent = "اطلاعات فروشگاه دریافت نشد";
  }
}
document
  .querySelector(".merchant-dialog-close")
  .addEventListener("click", () => merchantDialog.close());
merchantDialog.addEventListener("click", (event) => {
  if (event.target === merchantDialog) merchantDialog.close();
});
let shopRequest = 0;
async function loadEmptySuggestions() {
  emptySuggestions.innerHTML = "";
  if (!query) return;
  try {
    const suggestions = await api(
      `/api/search/suggestions?q=${encodeURIComponent(query)}`,
    );
    suggestions.slice(0, 4).forEach((item) => {
      if (item.value === query) return;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.value;
      button.addEventListener("click", () => applySuggestion(item.value));
      emptySuggestions.append(button);
    });
  } catch {
    // Suggestions are optional; keep the current search results available.
  }
}
async function loadShops() {
  const request = ++shopRequest,
    params = new URLSearchParams();
  selectedCategories.forEach((_label, code) => params.append("category", code));
  if (query) params.set("q", query);
  emptyState.hidden = true;
  emptyState.querySelector("h3").textContent = "فروشگاهی پیدا نشد";
  emptyState.querySelector("p").textContent =
    "نام محصول یا عبارت دیگری را امتحان کن.";
  const loadingTimer = setTimeout(() => {
    if (request === shopRequest)
      shopGrid.innerHTML = loaderMarkup("در حال دریافت فروشگاه‌ها");
  }, 120);
  try {
    const nextShops = await api(`/api/merchants?${params}`);
    if (request !== shopRequest) return;
    shops = nextShops;
    renderShops();
    if (!shops.length) loadEmptySuggestions();
  } catch (error) {
    if (request === shopRequest) showCatalogError(error);
  } finally {
    clearTimeout(loadingTimer);
  }
}
function showCatalogError(error) {
  reelStops.forEach((stop) => stop());
  reelStops = [];
  shopGrid.replaceChildren();
  document.querySelector("#discovery").hidden = true;
  document.querySelector("#result-count").textContent = "";
  resultTitle.textContent = "فروشگاه‌ها دریافت نشد";
  emptyState.hidden = false;
  emptyState.querySelector("h3").textContent = "اتصال برقرار نشد";
  emptyState.querySelector("p").textContent = "دوباره تلاش کن.";
  const retry = document.createElement("button");
  retry.type = "button";
  retry.id = "retry-shops";
  retry.textContent = "تلاش دوباره";
  retry.addEventListener("click", bootstrap);
  emptySuggestions.replaceChildren(retry);
  console.error(error);
}

async function bootstrap() {
  try {
    categoryTree = await api("/api/categories");
    renderTree();
    await loadShops();
  } catch (error) {
    showCatalogError(error);
  }
}

document.querySelector("#reset-category").addEventListener("click", () => {
  selectedCategories.clear();
  renderTree();
  renderQuickCategories();
  closeCategoryMenu();
  loadShops();
});
let suggestionItems = [],
  suggestionIndex = -1,
  suggestionRequest = 0;
function closeSuggestions() {
  searchSuggestions.hidden = true;
  searchInput.setAttribute("aria-expanded", "false");
  suggestionIndex = -1;
}
function paintSuggestionActive() {
  [...searchSuggestions.children].forEach((button, index) => {
    button.classList.toggle("active", index === suggestionIndex);
    button.setAttribute("aria-selected", String(index === suggestionIndex));
  });
}
function applySuggestion(value) {
  searchInput.value = value;
  query = value;
  closeSuggestions();
  loadShops();
  searchInput.focus();
}
async function loadSuggestions() {
  const value = searchInput.value.trim(),
    request = ++suggestionRequest;
  if (value.length < 2) {
    closeSuggestions();
    return;
  }
  try {
    const items = await api(
      `/api/search/suggestions?q=${encodeURIComponent(value)}`,
    );
    if (request !== suggestionRequest) return;
    suggestionItems = items;
    searchSuggestions.innerHTML = "";
    items.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.dataset.index = index;
      button.innerHTML = `<span>${escapeHtml(item.label)}</span><small>${item.type === "merchant" ? "فروشگاه" : item.type === "category" ? "دسته‌بندی" : "جستجو"}</small>`;
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => applySuggestion(item.value));
      searchSuggestions.append(button);
    });
    searchSuggestions.hidden = !items.length;
    searchInput.setAttribute("aria-expanded", String(Boolean(items.length)));
  } catch {
    closeSuggestions();
  }
}
searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (suggestionIndex >= 0 && suggestionItems[suggestionIndex]) {
    applySuggestion(suggestionItems[suggestionIndex].value);
    return;
  }
  query = searchInput.value.trim();
  closeSuggestions();
  loadShops();
});
let searchTimer, suggestionTimer;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  clearTimeout(suggestionTimer);
  query = searchInput.value.trim();
  suggestionTimer = setTimeout(loadSuggestions, 100);
  searchTimer = setTimeout(loadShops, 400);
});
searchInput.addEventListener("keydown", (event) => {
  if (searchSuggestions.hidden) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    suggestionIndex = (suggestionIndex + 1) % suggestionItems.length;
    paintSuggestionActive();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    suggestionIndex =
      (suggestionIndex - 1 + suggestionItems.length) % suggestionItems.length;
    paintSuggestionActive();
  } else if (event.key === "Escape") closeSuggestions();
});
searchInput.addEventListener("focus", () => {
  if (suggestionItems.length && searchInput.value.trim().length >= 2) {
    searchSuggestions.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest("#search-form")) closeSuggestions();
});

const connectDialog = document.querySelector("#connect-dialog"),
  connectButton = document.querySelector("#instagram-connect"),
  importStatus = document.querySelector("#import-status"),
  connectStates = [...document.querySelectorAll("[data-connect-state]")];
let imported = false;
function showConnectState(name) {
  connectStates.forEach((state) => {
    state.hidden = state.dataset.connectState !== name;
  });
}
function openConnectDialog() {
  showConnectState(imported ? "done" : "start");
  if (!connectDialog.open) connectDialog.showModal();
}
document
  .querySelectorAll("[data-open-connect]")
  .forEach((button) => button.addEventListener("click", openConnectDialog));
function followListingLink() {
  if (location.hash === "#connect") openConnectDialog();
}
window.addEventListener("hashchange", followListingLink);
followListingLink();
document
  .querySelector("#connect-dialog .dialog-close")
  .addEventListener("click", () => connectDialog.close());
connectDialog.addEventListener("click", (event) => {
  if (event.target === connectDialog) connectDialog.close();
});
connectButton.addEventListener("click", async () => {
  track("oauth_started");
  showConnectState("loading");
  for (const [index, step] of [
    "دریافت پروفایل",
    "دریافت آخرین پست‌ها",
    "تشخیص دسته‌بندی",
  ].entries()) {
    setTimeout(() => {
      importStatus.textContent = step;
    }, index * 550);
  }
  try {
    await new Promise((resolve) => setTimeout(resolve, 1700));
    await api("/api/merchants/import-demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    track("oauth_completed");
    imported = true;
    categoryTree = await api("/api/categories");
    await loadShops();
    renderTree();
    showConnectState("done");
  } catch {
    showConnectState("start");
  }
});
document.querySelector(".done-button").addEventListener("click", () => {
  connectDialog.close();
  document.querySelector("#shops").scrollIntoView({ behavior: "smooth" });
});

const loginDialog = document.querySelector("#login-dialog"),
  loginTrigger = document.querySelector("#login-trigger"),
  phoneForm = document.querySelector("#phone-form"),
  otpForm = document.querySelector("#otp-form"),
  phoneInput = document.querySelector("#phone-input"),
  otpInput = document.querySelector("#otp-input");
let loginPhone = "",
  challengeId = "";
const latinDigits = (value) =>
  value.replace(/[۰-۹]/g, (digit) => "۰۱۲۳۴۵۶۷۸۹".indexOf(digit));
initializeSession()
  .then(({ user }) => {
    if (!user) return;
    loginTrigger.textContent = "حساب من";
    loginTrigger.classList.add("logged-in");
  })
  .catch(() => {});
loginTrigger.addEventListener("click", () => {
  if (loginTrigger.classList.contains("logged-in")) {
    location.href = "/saved.html";
    return;
  }
  openLogin();
});
function openLogin() {
  track("login_started");
  if (!loginDialog.open) loginDialog.showModal();
  phoneInput.focus();
}

document.querySelectorAll('a[href="/saved.html"]').forEach((link) => {
  link.addEventListener("click", async (event) => {
    if (loginTrigger.classList.contains("logged-in")) return;
    event.preventDefault();
    try {
      const { user } = await initializeSession();
      if (user) {
        location.href = link.href;
        return;
      }
    } catch {
      // Keep the sign-in entry available if session bootstrap needs a retry.
    }
    openLogin();
  });
});

document
  .querySelector(".login-close")
  .addEventListener("click", () => loginDialog.close());
loginDialog.addEventListener("click", (event) => {
  if (event.target === loginDialog) loginDialog.close();
});
phoneForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginPhone = latinDigits(phoneInput.value.trim());
  if (!/^09\d{9}$/.test(loginPhone)) {
    document.querySelector("#phone-error").textContent =
      "شماره موبایل را درست وارد کن";
    return;
  }
  const response = await submitLogin(phoneForm, "request", {
    phone: loginPhone,
  });
  if (!response) return;
  challengeId = response.challenge_id;
  document.querySelector("#phone-error").textContent = "";
  document.querySelector("#phone-preview").textContent =
    phoneInput.value.trim();
  phoneForm.hidden = true;
  otpForm.hidden = false;
  otpInput.focus();
});
document.querySelector(".back-button").addEventListener("click", () => {
  otpForm.hidden = true;
  phoneForm.hidden = false;
  phoneInput.focus();
});
otpForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const code = latinDigits(otpInput.value.trim());
  if (!/^\d{5}$/.test(code)) {
    document.querySelector("#otp-error").textContent = "کد باید ۵ رقم باشد";
    return;
  }
  const response = await submitLogin(otpForm, "verify", {
    phone: loginPhone,
    code,
    challenge_id: challengeId,
  });
  if (!response) return;
  track("login_completed");
  loginDialog.close();
  location.href = "/saved.html";
});

async function submitLogin(form, step, payload) {
  const button = form.querySelector('[type="submit"]');
  const error = document.querySelector(
    step === "request" ? "#phone-error" : "#otp-error",
  );
  button.disabled = true;
  error.textContent = "";
  try {
    await initializeSession();
    return await api(`/api/login/${step}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Kahoo-Saved": "1" },
      body: JSON.stringify(payload),
    });
  } catch {
    error.textContent = "ورود انجام نشد. کمی بعد دوباره تلاش کن.";
    return null;
  } finally {
    button.disabled = false;
  }
}

bootstrap();
