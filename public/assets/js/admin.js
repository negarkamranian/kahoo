import { api, escapeHtml, faNumber as fa } from "./shared.js";

const dateFa = (value) =>
  new Intl.DateTimeFormat("fa-IR", { month: "short", day: "numeric" }).format(
    new Date(`${value}T12:00:00`),
  );
const el = (id) => document.getElementById(id);
el("today-label").textContent = new Intl.DateTimeFormat("fa-IR", {
  weekday: "long",
  day: "numeric",
  month: "long",
}).format(new Date());

function empty(text) {
  return `<div class="empty-data">${text}</div>`;
}
function renderChart(rows) {
  const width = 900,
    height = 230,
    pad = { top: 18, right: 20, bottom: 35, left: 18 },
    innerW = width - pad.right - pad.left,
    innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...rows.flatMap((row) => [row.searches, row.clicks]));
  const point = (value, index) => [
    pad.right +
      (rows.length === 1 ? innerW / 2 : (index * innerW) / (rows.length - 1)),
    pad.top + innerH - (value / max) * innerH,
  ];
  const line = (key) =>
    rows.map((row, index) => point(row[key], index).join(",")).join(" ");
  const every = Math.max(1, Math.ceil(rows.length / 6));
  const labels = rows
    .map((row, index) =>
      index % every === 0 || index === rows.length - 1
        ? `<text x="${point(0, index)[0]}" y="222" text-anchor="middle">${dateFa(row.date)}</text>`
        : "",
    )
    .join("");
  const grids = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (ratio) =>
        `<line x1="${pad.right}" y1="${pad.top + innerH * ratio}" x2="${width - pad.left}" y2="${pad.top + innerH * ratio}"/>`,
    )
    .join("");
  el("trend-chart").innerHTML =
    `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><g class="grid">${grids}</g><polyline class="search-line" points="${line("searches")}"/><polyline class="click-line" points="${line("clicks")}"/>${labels}</svg>`;
}

function renderList(container, items, renderItem, emptyText) {
  container.innerHTML = items.length
    ? items.map(renderItem).join("")
    : empty(emptyText);
}
function renderKpis(kpis) {
  el("kpi-searches").textContent = fa(kpis.searches);
  el("kpi-visitors").textContent = fa(kpis.visitors);
  el("kpi-clicks").textContent = fa(kpis.clicks);
  el("kpi-zero").textContent = `${fa(kpis.zero_rate)}٪`;
  el("kpi-conversion").textContent = `${fa(kpis.search_to_click)}٪`;
}

function renderQueries(data) {
  el("query-rows").innerHTML = data.top_queries.length
    ? data.top_queries
        .map(
          (row) =>
            `<tr><td><b>${escapeHtml(row.query)}</b></td><td>${fa(row.searches)}</td><td>${fa(row.avg_results)}</td><td><span class="${row.zero_results ? "bad" : "good"}">${fa(row.zero_results)}</span></td></tr>`,
        )
        .join("")
    : `<tr><td colspan="4">${empty("هنوز جستجویی ثبت نشده")}</td></tr>`;
  renderList(
    el("missed-list"),
    data.missed_queries,
    (row) =>
      `<div><span>${escapeHtml(row.query)}</span><b>${fa(row.searches)} بار</b></div>`,
    "فعلاً جستجوی بی‌نتیجه‌ای نیست",
  );
}

function renderTopMerchants(data) {
  renderList(
    el("merchant-list"),
    data.top_merchants,
    (row, index) =>
      `<div class="rank-item"><span class="rank">${fa(index + 1)}</span><div><b>${escapeHtml(row.name)}</b><small>${escapeHtml(row.handle)}</small></div><strong>${fa(row.clicks)} <small>کلیک</small></strong></div>`,
    "هنوز کلیکی ثبت نشده",
  );
}

function renderFunnel(funnel) {
  const stages = [
      { label: "بازدیدکننده", value: funnel.visitors },
      { label: "جستجو", value: funnel.searched },
      { label: "ورود به فروشگاه", value: funnel.clicked },
      { label: "شروع اتصال فروشگاه", value: funnel.oauth_started },
      { label: "اتصال کامل", value: funnel.oauth_completed },
    ],
    base = Math.max(1, stages[0].value);
  el("funnel").innerHTML = stages
    .map(
      (stage) =>
        `<div><div><span>${stage.label}</span><b>${fa(stage.value)}</b></div><i><em style="width:${Math.max((stage.value / base) * 100, stage.value ? 3 : 0)}%"></em></i></div>`,
    )
    .join("");
}

function renderCatalog(catalog) {
  el("catalog-merchants").textContent = fa(catalog.merchants);
  el("catalog-categories").textContent = fa(catalog.used_categories);
  el("catalog-posts").textContent = fa(catalog.posts);
  const complete = catalog.merchants
    ? (Math.min(catalog.avatars, catalog.descriptions) / catalog.merchants) *
      100
    : 0;
  el("catalog-profiles").textContent = `${fa(complete)}٪`;
}

function render(data) {
  renderKpis(data.kpis);
  renderChart(data.daily);
  renderQueries(data);
  renderTopMerchants(data);
  renderFunnel(data.funnel);
  renderCatalog(data.catalog);
  el("updated-at").textContent =
    `آخرین به‌روزرسانی: ${new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(new Date(data.generated_at))}`;
  el("loading").hidden = true;
  el("dashboard").hidden = false;
}
async function load() {
  el("loading").hidden = false;
  try {
    render(await api(`/api/admin/metrics?days=${el("period-select").value}`));
  } catch {
    el("loading").textContent =
      "دریافت آمار ممکن نشد. سرور را دوباره بررسی کنید.";
  }
}
const adminHeaders = () => {
  const token = el("admin-token").value.trim();
  return token ? { "X-Kahoo-Admin-Token": token } : {};
};
function managerStatus(message, type = "") {
  const node = el("manager-status");
  node.textContent = message;
  node.className = `manager-status ${type}`.trim();
}
async function loadManagedMerchants() {
  const query = el("merchant-search").value.trim();
  el("managed-merchant-list").innerHTML = empty("در حال دریافت فروشگاه‌ها…");
  try {
    const data = await api(
      `/api/admin/merchants?limit=100&q=${encodeURIComponent(query)}`,
    );
    el("managed-merchant-count").textContent = `${fa(data.total)} فروشگاه`;
    renderList(
      el("managed-merchant-list"),
      data.items,
      (row) =>
        `<article class="managed-row"><span class="managed-avatar">${row.avatar_url ? `<img src="${row.avatar_url}" alt="" loading="lazy" />` : ""}</span><div class="managed-copy"><b>${escapeHtml(row.name)}</b><small>${escapeHtml(row.handle)}</small></div><span class="managed-meta">${fa(row.followers_count)} دنبال‌کننده</span><span class="managed-meta">${fa(row.post_count)} تصویر</span><button class="remove-merchant" type="button" data-id="${row.id}" data-name="${escapeHtml(row.name)}">حذف</button></article>`,
      "فروشگاهی پیدا نشد",
    );
  } catch (error) {
    el("managed-merchant-list").innerHTML = empty(escapeHtml(error.message));
  }
}
el("merchant-add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = el("merchant-submit");
  button.disabled = true;
  managerStatus("در حال دریافت پروفایل، تصویر و پست‌های فروشگاه…");
  const payload = {
    identifier: el("merchant-identifier").value,
    category_code: el("merchant-category").value || null,
    city: el("merchant-city").value,
  };
  try {
    const result = await api("/api/admin/merchants", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify(payload),
    });
    managerStatus(
      `${result.created ? "فروشگاه افزوده شد" : "فروشگاه به‌روزرسانی شد"}؛ ${fa(result.post_images_saved)} تصویر ذخیره شد.`,
      "success",
    );
    el("merchant-identifier").value = "";
    await Promise.all([loadManagedMerchants(), load(), loadProducts()]);
  } catch (error) {
    managerStatus(error.message, "error");
  } finally {
    button.disabled = false;
  }
});
el("managed-merchant-list").addEventListener("click", async (event) => {
  const button = event.target.closest(".remove-merchant");
  if (!button) return;
  if (
    !confirm(
      `فروشگاه «${button.dataset.name}» و همه پست‌های ذخیره‌شده آن حذف شود؟`,
    )
  )
    return;
  button.disabled = true;
  managerStatus("در حال حذف فروشگاه…");
  try {
    await api(`/api/admin/merchants/${button.dataset.id}`, {
      method: "DELETE",
      headers: adminHeaders(),
    });
    managerStatus(
      "فروشگاه حذف شد و پس از راه‌اندازی مجدد نیز برنمی‌گردد.",
      "success",
    );
    await Promise.all([loadManagedMerchants(), load(), loadProducts()]);
  } catch (error) {
    managerStatus(error.message, "error");
    button.disabled = false;
  }
});
let merchantSearchTimer;
el("merchant-search").addEventListener("input", () => {
  clearTimeout(merchantSearchTimer);
  merchantSearchTimer = setTimeout(loadManagedMerchants, 250);
});
el("merchant-refresh").addEventListener("click", loadManagedMerchants);
el("period-select").addEventListener("change", load);
load();
loadManagedMerchants();

async function loadCategoryOptions() {
  try {
    const tree = await api("/api/categories");
    const select = el("merchant-category");
    function append(nodes, parents = []) {
      for (const node of nodes) {
        const labels = [...parents, node.label_fa];
        const option = document.createElement("option");
        option.value = node.code;
        option.textContent = `${labels.join(" / ")} (${node.code})`;
        select.append(option);
        append(node.children, labels);
      }
    }
    append(tree);
  } catch (error) {
    managerStatus(error.message, "error");
  }
}
loadCategoryOptions();

const productStatusLabels = {
  pending: "در صف",
  processing: "در حال پردازش",
  ready: "آماده",
  failed: "ناموفق",
  not_product: "غیرمحصولی",
};
const productReviewLabels = {
  pending: "بررسی‌نشده",
  approved: "تأییدشده",
  rejected: "ردشده",
};
const productSourceLabels = {
  caption: "کپشن",
  image: "تصویر",
  both: "کپشن و تصویر",
  unknown: "نامشخص",
};
const confidenceLabel = (value) => `${fa(Math.round(value * 100))}٪`;
let productOffset = 0,
  productRequest = 0,
  productSearchTimer;
const productImageURLs = new Set();
function clearProductImages() {
  productImageURLs.forEach((url) => URL.revokeObjectURL(url));
  productImageURLs.clear();
}
window.addEventListener("pagehide", clearProductImages);

function productAttributes(attributes) {
  if (!attributes.length)
    return empty("ویژگی‌ای برای این دسته تعریف نشده است.");
  return `<div class="product-attributes-wrap"><table class="product-attributes"><thead><tr><th>ویژگی</th><th>مقدار</th><th>اطمینان مدل</th><th>منبع و شاهد</th></tr></thead><tbody>${attributes
    .map((attribute) => {
      const value = attribute.values.join("، ") || attribute.value;
      return `<tr><td>${escapeHtml(attribute.name)}<small>${escapeHtml(attribute.handle)}</small></td><td class="${value ? "" : "product-unknown"}">${escapeHtml(value || "نامشخص")}</td><td>${value ? confidenceLabel(attribute.confidence) : "—"}</td><td>${productSourceLabels[attribute.source]}${attribute.evidence ? `<br>${escapeHtml(attribute.evidence)}` : ""}</td></tr>`;
    })
    .join("")}</tbody></table></div>`;
}

function productResultMarkup(result) {
  if (!result) return "";
  return `<h3>${result.category_name ? `نوع محصول: <span dir="ltr">${escapeHtml(result.category_name)}</span>` : "پست غیرمحصولی"}</h3><p>اطمینان مدل: ${confidenceLabel(result.confidence)} · کد: ${escapeHtml(result.category_code || "—")}</p><p>${escapeHtml(result.evidence)}</p><p>${escapeHtml(result.description)}</p>${result.warnings.map((warning) => `<p class="product-warning">${escapeHtml(warning)}</p>`).join("")}<h3>ویژگی‌ها</h3>${productAttributes(result.attributes)}`;
}

function productReviewActions(product) {
  const completed = ["ready", "not_product"].includes(product.status);
  return `<p class="product-provenance">مدل: ${escapeHtml(product.model || "—")} · نسخه طبقه‌بندی: ${escapeHtml(product.taxonomy_version || "—")} · تلاش‌ها: ${fa(product.attempts)}${product.processed_at ? ` · ${new Date(product.processed_at).toLocaleString("fa-IR")}` : ""}</p>
      <div class="product-assessment"><label>یادداشت ارزیابی<textarea rows="2" maxlength="3000">${escapeHtml(product.review_note)}</textarea></label>
        <button type="button" data-product-action="approved" ${completed ? "" : "disabled"}>تأیید نتیجه</button>
        <button type="button" data-product-action="rejected" ${completed ? "" : "disabled"}>رد نتیجه</button>
        <button type="button" data-product-action="retry" ${product.status === "processing" ? "disabled" : ""}>پردازش دوباره</button>
        <button type="button" data-product-action="history">سابقه پردازش</button>
      </div><div class="product-history" aria-live="polite"></div>`;
}

function productReviewCard(product) {
  const result = product.result;
  return `<details class="product-review-card" data-product="${product.id}">
    <summary><b>${escapeHtml(result?.title || `پست ${product.collection_key}`)}</b><small>${escapeHtml(product.merchant_name)} · ${escapeHtml(product.merchant_handle)}</small><span class="product-status-badge ${product.status}">${productStatusLabels[product.status]}</span><span class="product-status-badge">${productReviewLabels[product.review_status]}</span></summary>
    <div class="product-review-body">
      <div class="product-evidence-images">${product.images.map((image) => `<figure><img data-media-url="${escapeHtml(image.media_url)}" alt="تصویر ${fa(image.position)} محصول" loading="lazy"><figcaption>تصویر ${fa(image.position)}</figcaption></figure>`).join("")}</div>
      <h3>کپشن اصلی</h3><div class="product-source-caption">${escapeHtml(product.caption || "بدون کپشن")}</div>
      <a href="${escapeHtml(product.permalink)}" target="_blank" rel="noreferrer">دیدن پست اینستاگرام ↗</a>
      ${productResultMarkup(result)}
      ${product.error ? `<p class="manager-status error">${escapeHtml(product.error)}</p>` : ""}
      ${productReviewActions(product)}
    </div></details>`;
}

async function loadProductEvidence(card) {
  const request = productRequest;
  await Promise.all(
    [...card.querySelectorAll("img[data-media-url]")].map(async (image) => {
      const mediaURL = image.dataset.mediaUrl;
      delete image.dataset.mediaUrl;
      try {
        const response = await fetch(mediaURL, {
          headers: adminHeaders(),
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error("تصویر دریافت نشد");
        const blob = await response.blob();
        if (request !== productRequest || !image.isConnected) return;
        const url = URL.createObjectURL(blob);
        productImageURLs.add(url);
        image.src = url;
      } catch {
        if (request === productRequest) image.alt = "تصویر دریافت نشد";
      }
    }),
  );
}

function renderProductPage(data) {
  el("product-total").textContent = `${fa(data.total)} پست`;
  el("product-pipeline-status").textContent = data.configured
    ? "پست‌های جدید به‌صورت خودکار پردازش می‌شوند. اطمینان مدل تخمینی است؛ مقادیر نامشخص نیاز به بررسی دارند."
    : "مدل بینایی تنظیم نشده است؛ محصولات در صف می‌مانند. آدرس API و نام مدل را در تنظیمات سرور وارد کنید.";
  renderList(
    el("product-review-list"),
    data.items,
    productReviewCard,
    "محصولی برای این فیلتر پیدا نشد.",
  );
  el("product-prev").disabled = productOffset === 0;
  el("product-next").disabled = productOffset + data.items.length >= data.total;
  el("product-page-label").textContent = data.total
    ? `${fa(productOffset + 1)}–${fa(productOffset + data.items.length)} از ${fa(data.total)}`
    : "";
  el("product-review-list")
    .querySelectorAll("details")
    .forEach((card) =>
      card.addEventListener("toggle", () => {
        if (card.open) loadProductEvidence(card);
      }),
    );
}

async function loadProducts() {
  const request = ++productRequest,
    params = new URLSearchParams({
      limit: "20",
      offset: String(productOffset),
      q: el("product-search").value.trim(),
    });
  const status = el("product-status").value,
    review = el("product-review-status").value;
  if (status) params.set("status", status);
  if (review) params.set("review", review);
  el("product-review-list").innerHTML = empty("در حال دریافت محصولات…");
  el("product-prev").disabled = true;
  el("product-next").disabled = true;
  clearProductImages();
  try {
    const data = await api(`/api/admin/products?${params}`, {
      headers: adminHeaders(),
    });
    if (request !== productRequest) return;
    renderProductPage(data);
  } catch (error) {
    if (request === productRequest)
      el("product-review-list").innerHTML = empty(escapeHtml(error.message));
  }
}

async function loadProductHistory(card, baseURL) {
  const history = await api(`${baseURL}/history`, { headers: adminHeaders() });
  card.querySelector(".product-history").innerHTML = history.length
    ? history
        .map(
          (run) =>
            `<p>${escapeHtml(run.model)} · ${escapeHtml(productStatusLabels[run.status] || run.status)} · ${new Date(run.created_at).toLocaleString("fa-IR")}${run.error ? ` · ${escapeHtml(run.error)}` : ""}</p>`,
        )
        .join("")
    : "سابقه‌ای وجود ندارد.";
}

el("product-review-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-product-action]");
  if (!button) return;
  const card = button.closest("[data-product]"),
    action = button.dataset.productAction,
    baseURL = `/api/admin/products/${card.dataset.product}`;
  button.disabled = true;
  try {
    if (action === "history") {
      await loadProductHistory(card, baseURL);
    } else {
      await api(`${baseURL}/${action === "retry" ? "retry" : "review"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...adminHeaders() },
        ...(action === "retry"
          ? {}
          : {
              body: JSON.stringify({
                status: action,
                note: card.querySelector("textarea").value,
              }),
            }),
      });
      el("product-action-status").textContent =
        action === "retry" ? "محصول به صف پردازش برگشت." : "ارزیابی ذخیره شد.";
      await loadProducts();
    }
  } catch (error) {
    el("product-action-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

function resetProductPage() {
  productOffset = 0;
  loadProducts();
}
el("product-status").addEventListener("change", resetProductPage);
el("product-review-status").addEventListener("change", resetProductPage);
el("admin-token").addEventListener("change", resetProductPage);
el("product-search").addEventListener("input", () => {
  clearTimeout(productSearchTimer);
  productSearchTimer = setTimeout(resetProductPage, 250);
});
el("product-refresh").addEventListener("click", loadProducts);
el("product-prev").addEventListener("click", () => {
  productOffset = Math.max(0, productOffset - 20);
  loadProducts();
});
el("product-next").addEventListener("click", () => {
  productOffset += 20;
  loadProducts();
});
el("product-enqueue").addEventListener("click", async () => {
  el("product-enqueue").disabled = true;
  try {
    const result = await api("/api/admin/products/enqueue", {
      method: "POST",
      headers: adminHeaders(),
    });
    el("product-action-status").textContent =
      `${fa(result.collections)} پست بررسی شد؛ پست‌های جدید به صف اضافه شدند.`;
    resetProductPage();
  } catch (error) {
    el("product-action-status").textContent = error.message;
  } finally {
    el("product-enqueue").disabled = false;
  }
});
loadProducts();
