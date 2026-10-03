const numberFormatter = new Intl.NumberFormat("fa-IR", {
  maximumFractionDigits: 1,
});

export const STORAGE_KEYS = Object.freeze({
  merchants: "kahoo_saved_merchants",
  posts: "kahoo_saved_posts",
  session: "kahoo_session",
  user: "kahoo_user",
  adminToken: "kahoo_admin_token",
});

export const faNumber = (value) => numberFormatter.format(value);

export async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  const session = localStorage.getItem(STORAGE_KEYS.session);
  if (session) headers.set("X-Kahoo-Session", session);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    if (response.headers.get("Content-Type")?.includes("application/json")) {
      const error = await response.json();
      throw new Error(error.message ?? error.error ?? `API ${response.status}`);
    }
    throw new Error(`API ${response.status}`);
  }
  return response.json();
}

export function escapeHtml(value) {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

export function storedItems(key) {
  const stored = localStorage.getItem(key);
  if (stored === null) return [];
  const items = JSON.parse(stored);
  if (!Array.isArray(items))
    throw new TypeError(`Invalid saved collection: ${key}`);
  return items;
}

export function saveItems(key, items) {
  localStorage.setItem(key, JSON.stringify(items));
}
