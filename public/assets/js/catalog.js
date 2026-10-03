import {
  api,
  escapeHtml,
  faNumber,
  saveItems,
  storedItems,
  STORAGE_KEYS,
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
let categoryTree = [],
  shops = [],
  selectedCategory = null,
  selectedLabel = "",
  query = "";
const expanded = new Set();
let reelStops = [];
const finePointer = matchMedia("(hover: hover) and (pointer: fine)");
const loaderIcon =
  '<svg viewBox="0 0 16 16" shape-rendering="crispEdges"><path d="M5 1h2v2h2V2h2v3h2v5h-2v3H9v2H5v-2H3v-2H1V6h2V3h2zM6 4h4v2H8v5H6zM3 7h3v2H3z"/></svg>';
const loaderMarkup = (label) =>
  `<div class="kahoo-loader catalog-loader" role="status"><div class="kahoo-loader-icons" aria-hidden="true">${loaderIcon.repeat(3)}</div><span>${label}</span></div>`;
const sessionId =
  localStorage.getItem(STORAGE_KEYS.session) || crypto.randomUUID();
localStorage.setItem(STORAGE_KEYS.session, sessionId);

function track(event_type, details = {}) {
  api("/api/analytics/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type, ...details }),
  }).catch(() => {});
}

function collapseBranch(node) {
  expanded.delete(node.code);
  node.children.forEach(collapseBranch);
}
let branchOpenTimer;
function revealBranch(node, siblings) {
  if (!node.children.length || expanded.has(node.code)) return;
  siblings.filter((sibling) => sibling !== node).forEach(collapseBranch);
  expanded.add(node.code);
  renderTree();
}
function queueBranch(node, siblings) {
  clearTimeout(branchOpenTimer);
  if (node.children.length && !expanded.has(node.code))
    branchOpenTimer = setTimeout(() => revealBranch(node, siblings), 260);
}
function treeNode(node, siblings) {
  const item = document.createElement("li");
  item.className = `tree-item level-${node.level}`;
  item.setAttribute("role", "treeitem");
  item.setAttribute("aria-selected", node.code === selectedCategory);
  const row = document.createElement("div");
  row.className = `tree-node${node.code === selectedCategory ? " selected" : ""}${expanded.has(node.code) ? " active" : ""}`;
  const toggle = document.createElement("span");
  toggle.className = `tree-toggle${node.children.length ? "" : " empty"}${expanded.has(node.code) ? " expanded" : ""}`;
  toggle.setAttribute("aria-hidden", "true");
  const select = document.createElement("button");
  select.className = "tree-select";
  select.type = "button";
  select.innerHTML = `<span>${escapeHtml(node.label_fa)}</span>`;
  select.title = `GS1 ${node.code}`;
  select.addEventListener("click", (event) => {
    if (
      !finePointer.matches &&
      node.children.length &&
      !expanded.has(node.code)
    ) {
      event.preventDefault();
      revealBranch(node, siblings);
      return;
    }
    selectedCategory = node.code;
    selectedLabel = node.label_fa;
    renderTree();
    closeCategoryMenu();
    loadShops();
  });
  row.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse") queueBranch(node, siblings);
  });
  row.append(select, toggle);
  item.append(row);
  return item;
}

function renderTree() {
  treeElement.innerHTML = "";
  let siblings = categoryTree,
    depth = 0;
  while (siblings.length) {
    const column = document.createElement("ul");
    column.className = "tree-column";
    column.dataset.depth = depth;
    column.setAttribute("role", "group");
    siblings.forEach((node) => column.append(treeNode(node, siblings)));
    treeElement.append(column);
    const branch = siblings.find((node) => expanded.has(node.code));
    if (!branch) break;
    siblings = branch.children;
    depth += 1;
  }
  categoryPopover.style.setProperty(
    "--category-columns",
    treeElement.childElementCount,
  );
  categoryMenuLabel.textContent = selectedCategory
    ? selectedLabel
    : "دسته‌بندی‌ها";
}
function openCategoryMenu() {
  categoryPopover.hidden = false;
  categoryMenu.setAttribute("aria-expanded", "true");
}
function closeCategoryMenu() {
  clearTimeout(branchOpenTimer);
  categoryPopover.hidden = true;
  categoryMenu.setAttribute("aria-expanded", "false");
}
let categoryOpenTimer, categoryCloseTimer;
categoryDropdown.addEventListener("pointerenter", (event) => {
  if (event.pointerType === "mouse") {
    clearTimeout(categoryCloseTimer);
    if (categoryPopover.hidden)
      categoryOpenTimer = setTimeout(openCategoryMenu, 220);
  }
});
categoryDropdown.addEventListener("pointerleave", (event) => {
  if (event.pointerType === "mouse") {
    clearTimeout(categoryOpenTimer);
    categoryCloseTimer = setTimeout(closeCategoryMenu, 260);
  }
});
treeElement.addEventListener("pointerleave", () =>
  clearTimeout(branchOpenTimer),
);
categoryDropdown.addEventListener("focusin", () => {
  clearTimeout(categoryOpenTimer);
  clearTimeout(categoryCloseTimer);
  openCategoryMenu();
});
categoryDropdown.addEventListener("focusout", (event) => {
  if (!categoryDropdown.contains(event.relatedTarget)) closeCategoryMenu();
});
categoryMenu.addEventListener("click", (event) => {
  if (finePointer.matches && event.detail > 0) return;
  categoryPopover.hidden ? openCategoryMenu() : closeCategoryMenu();
});
document.addEventListener("click", (event) => {
  if (!event.target.closest("#categories")) closeCategoryMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeCategoryMenu();
});
function configureShopNavigation(article, shop, index) {
  article.style.animationDelay = `${index * 35}ms`;
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
}

function configureShopVisit(card, shop) {
  const visitLink = card.querySelector(".visit-link");
  visitLink.href = shop.instagram_url;
  visitLink.target = "_blank";
  visitLink.addEventListener("click", () =>
    track("merchant_click", {
      merchant_id: shop.id,
      query,
      category_code: selectedCategory,
    }),
  );
}

function shopCard(shop, index) {
  const card = template.content.cloneNode(true);
  configureShopNavigation(card.querySelector("article"), shop, index);
  appendShopAvatar(card.querySelector(".shop-avatar"), shop);
  populateShopCard(card, shop);
  configureShopVisit(card, shop);
  reelStops.push(createPostReel(card.querySelector(".post-grid"), shop, index));
  return card;
}

function renderShops() {
  reelStops.forEach((stop) => stop());
  reelStops = [];
  shopGrid.innerHTML = "";
  emptyState.hidden = shops.length > 0;
  shops.forEach((shop, index) => shopGrid.append(shopCard(shop, index)));
  resultTitle.textContent = query
    ? `نتایج «${searchInput.value.trim()}»`
    : selectedLabel || "فروشگاه‌ها";
}

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
  button.textContent = compact
    ? saved
      ? "♥"
      : "♡"
    : saved
      ? "ذخیره شده"
      : "ذخیره";
}
function toggleSaved(key, item, button, compact = false) {
  const items = storedItems(key),
    index = items.findIndex((saved) => saved.key === item.key);
  if (index >= 0) items.splice(index, 1);
  else items.unshift(item);
  saveItems(key, items);
  paintSave(button, index < 0, compact);
}
function merchantCategorySummary(merchant) {
  const categoryLabels = merchant.categories.map((category) => category.label),
    categorySummary = categoryLabels.length
      ? categoryLabels.slice(0, 3).join("، ") +
        (categoryLabels.length > 3
          ? ` +${faNumber(categoryLabels.length - 3)} دسته`
          : "")
      : merchant.category_label;
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
  document.querySelector("#detail-meta").textContent =
    `${merchantCategorySummary(merchant)} · ${merchant.city}`;
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
  paintSave(
    merchantSave,
    storedItems(STORAGE_KEYS.merchants).some(
      (item) => item.key === merchantItem.key,
    ),
  );
  merchantSave.onclick = () =>
    toggleSaved(STORAGE_KEYS.merchants, merchantItem, merchantSave);
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
  paintSave(
    save,
    storedItems(STORAGE_KEYS.posts).some((saved) => saved.key === item.key),
    true,
  );
  save.addEventListener("click", () =>
    toggleSaved(STORAGE_KEYS.posts, item, save, true),
  );
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
}

async function openMerchantProfile(merchantId) {
  merchantDialogLoading.innerHTML = loaderMarkup("در حال دریافت فروشگاه");
  merchantDialogLoading.hidden = false;
  merchantDialogContent.hidden = true;
  merchantDialog.showModal();
  try {
    const merchant = await api(`/api/merchants/${merchantId}`);
    renderMerchantAvatar(merchant);
    renderMerchantDetails(merchant);
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
  if (selectedCategory) params.set("category", selectedCategory);
  if (query) params.set("q", query);
  emptyState.hidden = true;
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
  } finally {
    clearTimeout(loadingTimer);
  }
}
async function bootstrap() {
  try {
    categoryTree = await api("/api/categories");
    renderTree();
    await loadShops();
  } catch (error) {
    resultTitle.textContent = "اتصال به پایگاه داده برقرار نشد";
    console.error(error);
  }
}

document.querySelector("#reset-category").addEventListener("click", () => {
  selectedCategory = null;
  selectedLabel = "";
  renderTree();
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
document.querySelectorAll("[data-open-connect]").forEach((button) =>
  button.addEventListener("click", () => {
    showConnectState(imported ? "done" : "start");
    connectDialog.showModal();
  }),
);
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
if (localStorage.getItem(STORAGE_KEYS.user)) {
  loginTrigger.textContent = "حساب من";
  loginTrigger.classList.add("logged-in");
}
loginTrigger.addEventListener("click", () => {
  if (loginTrigger.classList.contains("logged-in")) {
    location.href = "/saved.html";
    return;
  }
  track("login_started");
  loginDialog.showModal();
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
  const response = await api("/api/login/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone: loginPhone }),
  });
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
  const response = await api("/api/login/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      phone: loginPhone,
      code,
      challenge_id: challengeId,
    }),
  });
  track("login_completed");
  localStorage.setItem(
    STORAGE_KEYS.user,
    JSON.stringify({ display_name: response.user.display_name }),
  );
  loginDialog.close();
  location.href = "/saved.html";
});

bootstrap();
