import { escapeHtml } from "./shared.js";

const fa = (value) =>
  new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 }).format(
    value || 0,
  );
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

function renderList(container, items, render, emptyText) {
  container.innerHTML = items.length
    ? items.map(render).join("")
    : empty(emptyText);
}
function render(data) {
  const { kpis, catalog, funnel } = data;
  el("kpi-searches").textContent = fa(kpis.searches);
  el("kpi-visitors").textContent = fa(kpis.visitors);
  el("kpi-clicks").textContent = fa(kpis.clicks);
  el("kpi-zero").textContent = `${fa(kpis.zero_rate)}٪`;
  el("kpi-conversion").textContent = `${fa(kpis.search_to_click)}٪`;
  renderChart(data.daily);
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
  renderList(
    el("merchant-list"),
    data.top_merchants,
    (row, index) =>
      `<div class="rank-item"><span class="rank">${fa(index + 1)}</span><div><b>${escapeHtml(row.name)}</b><small>${escapeHtml(row.handle)}</small></div><strong>${fa(row.clicks)} <small>کلیک</small></strong></div>`,
    "هنوز کلیکی ثبت نشده",
  );
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
  el("catalog-merchants").textContent = fa(catalog.merchants);
  el("catalog-categories").textContent = fa(catalog.used_categories);
  el("catalog-posts").textContent = fa(catalog.posts);
  const complete = catalog.merchants
    ? (Math.min(catalog.avatars, catalog.descriptions) / catalog.merchants) *
      100
    : 0;
  el("catalog-profiles").textContent = `${fa(complete)}٪`;
  el("updated-at").textContent =
    `آخرین به‌روزرسانی: ${new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(new Date(data.generated_at))}`;
  el("loading").hidden = true;
  el("dashboard").hidden = false;
}
async function load() {
  el("loading").hidden = false;
  try {
    const response = await fetch(
      `/api/admin/metrics?days=${el("period-select").value}`,
    );
    if (!response.ok) throw new Error();
    render(await response.json());
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
async function responseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || "انجام عملیات ممکن نشد.");
  return data;
}
async function loadManagedMerchants() {
  const query = el("merchant-search").value.trim();
  el("managed-merchant-list").innerHTML = empty("در حال دریافت فروشگاه‌ها…");
  try {
    const data = await responseJson(
      await fetch(
        `/api/admin/merchants?limit=100&q=${encodeURIComponent(query)}`,
      ),
    );
    el("managed-merchant-count").textContent = `${fa(data.total)} فروشگاه`;
    renderList(
      el("managed-merchant-list"),
      data.items,
      (row) =>
        `<article class="managed-row"><span class="managed-avatar">${row.avatar_url ? `<img src="${row.avatar_url}" alt="" loading="lazy" />` : escapeHtml((row.name || "؟").slice(0, 1))}</span><div class="managed-copy"><b>${escapeHtml(row.name)}</b><small>${escapeHtml(row.handle)}</small></div><span class="managed-meta">${fa(row.followers_count)} دنبال‌کننده</span><span class="managed-meta">${fa(row.post_count)} تصویر</span><button class="remove-merchant" type="button" data-id="${row.id}" data-name="${escapeHtml(row.name)}">حذف</button></article>`,
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
    name: el("merchant-name").value.trim() || null,
    description: el("merchant-description").value.trim() || null,
    city: el("merchant-city").value.trim() || "ایران",
  };
  try {
    const result = await responseJson(
      await fetch("/api/admin/merchants", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...adminHeaders() },
        body: JSON.stringify(payload),
      }),
    );
    managerStatus(
      `${result.created ? "فروشگاه افزوده شد" : "فروشگاه به‌روزرسانی شد"}؛ ${fa(result.post_images_saved)} تصویر ذخیره شد.`,
      "success",
    );
    el("merchant-identifier").value = "";
    el("merchant-name").value = "";
    el("merchant-description").value = "";
    await Promise.all([loadManagedMerchants(), load()]);
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
    await responseJson(
      await fetch(`/api/admin/merchants/${button.dataset.id}`, {
        method: "DELETE",
        headers: adminHeaders(),
      }),
    );
    managerStatus(
      "فروشگاه حذف شد و پس از راه‌اندازی مجدد نیز برنمی‌گردد.",
      "success",
    );
    await Promise.all([loadManagedMerchants(), load()]);
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
el("admin-token").value = sessionStorage.getItem("kahoo_admin_token") || "";
el("admin-token").addEventListener("input", () =>
  sessionStorage.setItem("kahoo_admin_token", el("admin-token").value),
);
el("period-select").addEventListener("change", load);
load();
loadManagedMerchants();
