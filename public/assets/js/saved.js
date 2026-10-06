import {
  faNumber,
  initializeSession,
  refreshSaved,
  savedItems,
  savedMigrationWarning,
  setSaved,
} from "./shared.js";

const merchantRoot = document.querySelector("#saved-merchants"),
  postRoot = document.querySelector("#saved-posts"),
  merchantCount = document.querySelector("#merchant-count"),
  postCount = document.querySelector("#post-count");
const status = document.createElement("p");
status.className = "saved-status";
status.setAttribute("role", "status");
document.querySelector(".saved-index").before(status);

function showStatus(message, retry = false) {
  status.replaceChildren(message);
  if (retry) status.append(actionButton("تلاش دوباره", () => loadSaved(true)));
}

async function removeSaved(kind, item, event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await setSaved(kind, item, false);
    render();
    showStatus(savedMigrationWarning(), Boolean(savedMigrationWarning()));
  } catch {
    showStatus("حذف انجام نشد. دوباره تلاش کن.");
    button.disabled = false;
  }
}
function emptyMessage(label) {
  const node = document.createElement("div");
  node.className = "empty-state compact";
  node.append("هنوز ", label, " ذخیره نکرده‌ای. ");
  const link = document.createElement("a");
  link.href = "/";
  link.textContent = "رفتن به فروشگاه‌ها";
  node.append(link);
  return node;
}
function actionButton(label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "remove-button";
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}
function savedMerchantCard(item) {
  const card = document.createElement("article"),
    avatar = document.createElement("span"),
    image = document.createElement("img"),
    actions = document.createElement("div"),
    open = document.createElement("a");
  card.className = "saved-merchant";
  avatar.className = "saved-avatar";
  setSavedAvatar(image, item);
  avatar.append(image);
  const copy = savedMerchantCopy(item);
  actions.className = "card-actions";
  open.className = "open-link";
  open.href = item.instagram_url;
  open.target = "_blank";
  open.rel = "noreferrer";
  open.textContent = "دیدن در اینستاگرام";
  const remove = actionButton("حذف", (event) =>
    removeSaved("merchants", item, event),
  );
  remove.setAttribute("aria-label", `حذف ${item.name} از ذخیره‌شده‌ها`);
  actions.append(open, remove);
  card.append(avatar, copy, actions);
  return card;
}

function savedPostCard(item) {
  const card = document.createElement("article"),
    link = document.createElement("a"),
    image = document.createElement("img"),
    caption = document.createElement("div"),
    label = document.createElement("span");
  card.className = "saved-post";
  link.href = item.permalink;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.setAttribute(
    "aria-label",
    `دیدن پست ${item.merchant_name} در اینستاگرام`,
  );
  image.src = item.media_url;
  image.loading = "lazy";
  image.alt = `پست ${item.merchant_name}`;
  label.textContent =
    item.image_count > 1
      ? `${item.merchant_name} · مجموعه ${faNumber(item.image_count)} تصویر`
      : item.merchant_name;
  link.append(image);
  caption.className = "post-caption";
  const remove = actionButton("حذف", (event) =>
    removeSaved("posts", item, event),
  );
  remove.setAttribute(
    "aria-label",
    `حذف پست ${item.merchant_name} از ذخیره‌شده‌ها`,
  );
  caption.append(label, remove);
  card.append(link, caption);
  return card;
}

function setSavedAvatar(image, item) {
  image.hidden = !item.avatar_url;
  if (item.avatar_url) {
    image.src = item.avatar_url;
    image.alt = `تصویر ${item.name}`;
    image.loading = "lazy";
  }
  image.onerror = () => {
    image.hidden = true;
  };
}

function savedMerchantCopy(item) {
  const copy = document.createElement("div");
  const name = document.createElement("b");
  const handle = document.createElement("small");
  const description = document.createElement("p");
  name.textContent = item.name;
  handle.textContent = item.handle;
  description.textContent = item.description;
  copy.className = "merchant-copy";
  copy.append(name, handle, description);
  return copy;
}

function render() {
  const merchants = savedItems("merchants");
  const posts = savedItems("posts");
  merchantRoot.replaceChildren(...merchants.map(savedMerchantCard));
  postRoot.replaceChildren(...posts.map(savedPostCard));
  merchantCount.textContent = faNumber(merchants.length);
  postCount.textContent = faNumber(posts.length);
  if (!merchants.length) merchantRoot.append(emptyMessage("فروشگاهی"));
  if (!posts.length) postRoot.append(emptyMessage("پستی"));
}
async function loadSaved(retry = false) {
  showStatus("در حال دریافت ذخیره‌شده‌ها…");
  try {
    if (retry) await refreshSaved();
    else await initializeSession();
    render();
    showStatus(savedMigrationWarning(), Boolean(savedMigrationWarning()));
  } catch {
    showStatus("ذخیره‌شده‌ها دریافت نشدند.", true);
  }
}
loadSaved();
