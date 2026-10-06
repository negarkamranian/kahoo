const numberFormatter = new Intl.NumberFormat("fa-IR", {
  maximumFractionDigits: 1,
});

export const STORAGE_KEYS = Object.freeze({
  merchants: "kahoo_saved_merchants",
  posts: "kahoo_saved_posts",
  session: "kahoo_session",
  user: "kahoo_user",
});

let session = null,
  initialization = null,
  collections = { merchants: [], posts: [] },
  mutationQueue = Promise.resolve(),
  migrationWarning = "";

const canCoordinateTabs = Boolean(globalThis.navigator?.locks);

export const faNumber = (value) => numberFormatter.format(value);

export async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (session) headers.set("X-Kahoo-Session", session.session_id);
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers,
  });
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

export function savedItems(kind) {
  return collections[kind];
}

export function isSaved(kind, item) {
  return savedItems(kind).some((saved) =>
    kind === "merchants"
      ? saved.id === item.id
      : saved.merchant_id === item.merchant_id && saved.key === item.key,
  );
}

function updateCollections(result) {
  collections = { merchants: result.merchants, posts: result.posts };
}

function legacyReference(kind, item) {
  if (!item || typeof item !== "object") return null;
  if (kind === "merchants")
    return Number.isInteger(item.id) && item.id > 0 ? { id: item.id } : null;
  return legacyPostReference(item);
}

function legacyPostReference(item) {
  if (Number.isInteger(item.merchant_id) && item.merchant_id > 0 && item.key)
    return { merchant_id: item.merchant_id, key: String(item.key) };
  return typeof item.permalink === "string" && item.permalink
    ? { permalink: item.permalink }
    : null;
}

function referenceKey(reference) {
  return JSON.stringify(reference);
}

function retainUnconfirmed(kind, confirmed) {
  if (!canCoordinateTabs) return storedItems(STORAGE_KEYS[kind]).length;
  const key = STORAGE_KEYS[kind];
  const remaining = storedItems(key).filter(
    (item) => !confirmed.has(referenceKey(legacyReference(kind, item))),
  );
  writeLegacyItems(key, remaining);
  return remaining.length;
}

function writeLegacyItems(key, items) {
  if (items.length) localStorage.setItem(key, JSON.stringify(items));
  else localStorage.removeItem(key);
}

function legacyMatches(kind, legacy, item) {
  const reference = legacyReference(kind, legacy);
  if (!reference) return false;
  if (kind === "merchants") return reference.id === item.id;
  if (reference.permalink) return reference.permalink === item.permalink;
  return (
    reference.merchant_id === item.merchant_id && reference.key === item.key
  );
}

function removeLegacySaved(kind, item) {
  const key = STORAGE_KEYS[kind];
  try {
    writeLegacyItems(
      key,
      storedItems(key).filter((legacy) => !legacyMatches(kind, legacy, item)),
    );
  } catch {
    migrationWarning = legacyWarning();
  }
}

async function importLegacyCollection(kind) {
  const references = storedItems(STORAGE_KEYS[kind])
    .map((item) => legacyReference(kind, item))
    .filter(Boolean);
  for (let start = 0; start < references.length; start += 200) {
    const batch = references.slice(start, start + 200);
    const result = await api("/api/saved/import", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Kahoo-Saved": "1" },
      body: JSON.stringify({ [kind]: batch }),
    });
    updateCollections(result);
    const skipped = new Set(
      result[`skipped_${kind}`].map((item) =>
        referenceKey(legacyReference(kind, item)),
      ),
    );
    const confirmed = new Set(
      batch.map(referenceKey).filter((key) => !skipped.has(key)),
    );
    retainUnconfirmed(kind, confirmed);
  }
  return storedItems(STORAGE_KEYS[kind]).length;
}

async function migrateBrowserSaves() {
  migrationWarning = "";
  for (const kind of ["merchants", "posts"]) {
    try {
      if (await importLegacyCollection(kind))
        migrationWarning = legacyWarning();
    } catch {
      migrationWarning = legacyWarning();
    }
  }
}

function legacyWarning() {
  return "بعضی ذخیره‌های قبلی هنوز در این مرورگر نگه داشته شده‌اند. دوباره تلاش کن.";
}

async function loadSession() {
  session = await api("/api/session");
  updateCollections(await api("/api/saved"));
  await migrateBrowserSaves();
  try {
    localStorage.removeItem(STORAGE_KEYS.user);
    localStorage.removeItem(STORAGE_KEYS.session);
  } catch {
    /* Browser storage may be unavailable; the server session still works. */
  }
  return session;
}

export function initializeSession() {
  if (!initialization)
    initialization = coordinatedSession().catch((error) => {
      initialization = null;
      throw error;
    });
  return initialization;
}

function coordinatedSession(work = loadSession) {
  return canCoordinateTabs
    ? navigator.locks.request("kahoo-account-bootstrap", work)
    : work();
}

export function savedMigrationWarning() {
  return migrationWarning;
}

export async function refreshSaved() {
  await initializeSession();
  return enqueueSaved(() =>
    coordinatedSession(async () => {
      updateCollections(await api("/api/saved"));
      await migrateBrowserSaves();
    }),
  );
}

function enqueueSaved(work) {
  const mutation = mutationQueue.catch(() => {}).then(work);
  mutationQueue = mutation;
  return mutation;
}

export async function setSaved(kind, item, saved) {
  await initializeSession();
  const suffix =
    kind === "merchants"
      ? `merchants/${item.id}`
      : `posts/${item.merchant_id}/${encodeURIComponent(item.key)}`;
  return enqueueSaved(() =>
    coordinatedSession(async () => {
      updateCollections(
        await api(`/api/saved/${suffix}`, {
          method: saved ? "PUT" : "DELETE",
          headers: { "X-Kahoo-Saved": "1" },
        }),
      );
      if (!saved) removeLegacySaved(kind, item);
    }),
  );
}
