import { api, escapeHtml, faNumber as fa, STORAGE_KEYS } from "./shared.js";

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
    await api(`/api/admin/merchants/${button.dataset.id}`, {
      method: "DELETE",
      headers: adminHeaders(),
    });
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
el("admin-token").value = sessionStorage.getItem(STORAGE_KEYS.adminToken) || "";
el("admin-token").addEventListener("input", () =>
  sessionStorage.setItem(STORAGE_KEYS.adminToken, el("admin-token").value),
);
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
