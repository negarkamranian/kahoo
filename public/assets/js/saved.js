import { faNumber, saveItems, storedItems, STORAGE_KEYS } from "./shared.js";

const merchantRoot = document.querySelector("#saved-merchants"),
  postRoot = document.querySelector("#saved-posts"),
  postCount = document.querySelector("#post-count");
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
    image = document.createElement("img"),
    actions = document.createElement("div"),
    open = document.createElement("a");
  card.className = "saved-merchant";
  setSavedAvatar(image, item);
  const copy = savedMerchantCopy(item);
  actions.className = "card-actions";
  open.className = "open-link";
  open.href = item.instagram_url;
  open.target = "_blank";
  open.rel = "noreferrer";
  open.textContent = "دیدن در اینستاگرام";
  actions.append(
    open,
    actionButton("حذف", () => {
      saveItems(
        STORAGE_KEYS.merchants,
        storedItems(STORAGE_KEYS.merchants).filter(
          (saved) => saved.key !== item.key,
        ),
      );
      render();
    }),
  );
  card.append(image, copy, actions);
  return card;
}

function savedPostCard(item) {
  const card = document.createElement("article"),
    link = document.createElement("a"),
    image = document.createElement("img"),
    label = document.createElement("span");
  card.className = "saved-post";
  link.href = item.permalink;
  link.target = "_blank";
  link.rel = "noreferrer";
  image.src = item.media_url;
  image.alt = `پست ${item.merchant_name}`;
  label.textContent =
    item.image_count > 1
      ? `${item.merchant_name} · مجموعه ${faNumber(item.image_count)} تصویر`
      : item.merchant_name;
  link.append(image);
  card.append(
    link,
    actionButton("حذف", () => {
      saveItems(
        STORAGE_KEYS.posts,
        storedItems(STORAGE_KEYS.posts).filter(
          (saved) => saved.key !== item.key,
        ),
      );
      render();
    }),
    label,
  );
  return card;
}

function setSavedAvatar(image, item) {
  image.hidden = !item.avatar_url;
  if (item.avatar_url) {
    image.src = item.avatar_url;
    image.alt = `تصویر ${item.name}`;
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
  const merchants = storedItems(STORAGE_KEYS.merchants);
  const posts = storedItems(STORAGE_KEYS.posts);
  merchantRoot.replaceChildren(...merchants.map(savedMerchantCard));
  postRoot.replaceChildren(...posts.map(savedPostCard));
  postCount.textContent = faNumber(posts.length);
  if (!merchants.length) merchantRoot.append(emptyMessage("فروشگاهی"));
  if (!posts.length) postRoot.append(emptyMessage("پستی"));
}
render();
