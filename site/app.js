const state = {
  summary: null,
  monthly: null,
  features: null,
  category: "pv",
  records: [],
  filtered: [],
  page: 1,
  pageSize: 25,
  sortKey: "registered",
  sortDirection: "desc"
};

const $ = (selector) => document.querySelector(selector);
const nf = new Intl.NumberFormat("zh-CN");
const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[c]
);
const count = (value) => nf.format(Number(value || 0));

function setStatus(text) {
  $("#dataStatus").textContent = text;
}

function categoryInfo() {
  return state.summary.categories[state.category];
}

function recordDate(raw) {
  const value = String(raw || "");
  let match = value.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (match) return match[1] + "-" + String(match[2]).padStart(2, "0") + "-" + String(match[3]).padStart(2, "0");
  match = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
  return match ? match[3] + "-" + String(match[2]).padStart(2, "0") + "-" + String(match[1]).padStart(2, "0") : value;
}

function formatDate(raw) {
  const value = recordDate(raw);
  return value.match(/^\d{4}-\d{2}-\d{2}$/) ? value.slice(8, 10) + "." + value.slice(5, 7) + "." + value.slice(0, 4) : (raw || "--");
}

async function fetchGzipJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(path + ": HTTP " + response.status);
  if (!window.DecompressionStream) throw new Error("当前浏览器不支持 gzip 解压");
  const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
  const text = await new Response(stream).text();
  return text.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

async function loadCategoryRecords(category) {
  setStatus("正在加载明细");
  try {
    state.records = await fetchGzipJson("data/records_" + category + ".ndjson.gz");
    populateFilters();
    applyFilters();
    $("#metricLoaded").textContent = count(state.records.length) + " 条明细已载入";
    setStatus("数据已更新");
  } catch (error) {
    setStatus("明细加载失败");
    $("#emptyState").classList.remove("hidden");
    $("#emptyState").textContent = "明细加载失败，请检查浏览器是否支持 gzip 解压。";
    console.error(error);
  }
}

function fillSelect(select, values, placeholder) {
  const current = select.value;
  select.innerHTML = '<option value="">' + placeholder + "</option>" +
    values.map((value) => '<option value="' + esc(value) + '">' + esc(value) + "</option>").join("");
  if (values.includes(current)) select.value = current;
}

function populateFilters() {
  const unique = (key) => [...new Set(state.records.map((row) => row[key]).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "de"));
  fillSelect($("#stateFilter"), unique("state"), "全部州");
  fillSelect($("#districtFilter"), unique("district"), "全部地区");
  fillSelect($("#statusFilter"), unique("status"), "全部状态");
  const technologyKey = state.category === "pv" ? "solarTech" : "storageTech";
  fillSelect($("#technologyFilter"), unique(technologyKey), "全部");
  $("#technologyFilterWrap span").textContent = state.category === "pv" ? "发电技术" : "电池技术";
}

function activeFilter() {
  return ["#searchInput", "#stateFilter", "#districtFilter", "#statusFilter", "#technologyFilter"]
    .some((selector) => $(selector).value);
}

function applyFilters() {
  const query = $("#searchInput").value.trim().toLocaleLowerCase();
  const selections = {
    state: $("#stateFilter").value,
    district: $("#districtFilter").value,
    status: $("#statusFilter").value,
    technology: $("#technologyFilter").value
  };
  const technologyKey = state.category === "pv" ? "solarTech" : "storageTech";
  state.filtered = state.records.filter((row) => {
    const haystack = [row.id, row.name, row.state, row.district, row.municipality, row.town, row.zip]
      .join(" ").toLocaleLowerCase();
    return (!query || haystack.includes(query)) &&
      (!selections.state || row.state === selections.state) &&
      (!selections.district || row.district === selections.district) &&
      (!selections.status || row.status === selections.status) &&
      (!selections.technology || row[technologyKey] === selections.technology);
  });
  state.page = 1;
  $("#metricFilter").textContent = activeFilter() ? "已筛选" : "全量";
  $("#resultCount").textContent = count(state.filtered.length) + " / " + count(state.records.length) + " 条记录";
  drawStateBars(state.filtered);
  drawTrend(state.filtered);
  drawFeatures();
  renderTable();
}

function sortedRows() {
  return [...state.filtered].sort((a, b) => {
    let left = state.sortKey === "registered" ? recordDate(a.registered) : (a[state.sortKey] || "");
    let right = state.sortKey === "registered" ? recordDate(b.registered) : (b[state.sortKey] || "");
    if (state.sortKey === "power") {
      left = parseFloat(String(left).replace(",", ".")) || 0;
      right = parseFloat(String(right).replace(",", ".")) || 0;
    } else {
      left = String(left).toLocaleLowerCase();
      right = String(right).toLocaleLowerCase();
    }
    const result = left < right ? -1 : left > right ? 1 : 0;
    return state.sortDirection === "asc" ? result : -result;
  });
}

function renderTable() {
  const rows = sortedRows();
  const totalPages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const start = (state.page - 1) * state.pageSize;
  const pageRows = rows.slice(start, start + state.pageSize);
  $("#recordBody").innerHTML = pageRows.map((row) => {
    const tech = state.category === "pv" ? row.solarTech : row.storageTech;
    return "<tr><td>" + esc(formatDate(row.registered)) + "</td>" +
      '<td><strong title="' + esc(row.name) + '">' + esc(row.name || "未提供名称") + "</strong><small>" + esc(row.id) + "</small></td>" +
      "<td>" + esc(row.state || "--") + "</td>" +
      "<td>" + esc(row.district || "--") + "<small>" + esc(row.town || row.municipality || "") + "</small></td>" +
      "<td>" + esc(row.power || "--") + " kW</td>" +
      '<td><span class="tag">' + esc(tech || row.energy || "--") + '</span><span class="tag status">' + esc(row.status || "--") + "</span></td></tr>";
  }).join("");
  $("#emptyState").classList.toggle("hidden", pageRows.length > 0);
  $("#pageLabel").textContent = "第 " + state.page + " / " + totalPages + " 页";
  $("#prevPage").disabled = state.page <= 1;
  $("#nextPage").disabled = state.page >= totalPages;
}

function drawStateBars(rows) {
  const counts = {};
  rows.forEach((row) => {
    const key = row.state || "未提供";
    counts[key] = (counts[key] || 0) + 1;
  });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = top[0] ? top[0][1] : 1;
  $("#stateBars").innerHTML = top.length ? top.map(([name, value]) =>
    '<div class="bar-row"><span title="' + esc(name) + '">' + esc(name) + '</span><span class="bar-track"><i class="bar-fill" style="width:' +
    (value / max * 100) + '%"></i></span><span class="bar-value">' + count(value) + "</span></div>"
  ).join("") : '<div class="empty-state">暂无区域数据</div>';
}

function drawTrend(rows) {
  const mode = $("#trendMode").value;
  const groups = {};
  rows.forEach((row) => {
    const value = recordDate(row.registered);
    const key = mode === "annual" ? value.slice(0, 4) : value.slice(0, 7);
    if (key.length >= 4) groups[key] = (groups[key] || 0) + 1;
  });
  const points = Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
  drawChart(points);
  if (points.length) {
    const peak = points.reduce((best, item) => item[1] > best[1] ? item : best, points[0]);
    $("#trendCaption").textContent = (mode === "annual" ? "年度" : "月度") + "峰值 " + peak[0] + " · " + count(peak[1]) + " 条";
  } else $("#trendCaption").textContent = "暂无趋势数据";
}

function drawFeatures() {
  const source = state.features[state.category] || {};
  const labels = state.category === "pv"
    ? { solar_tech: "发电技术", storage_tech: "储能技术", name: "名称关键词", status: "运行状态" }
    : { storage_tech: "电池技术", capacity: "可用容量", status: "运行状态", state: "登记州" };
  $("#featureGrid").innerHTML = Object.entries(labels).map(([key, label]) => {
    const top = (source[key] || [])[0];
    const value = top ? top.value : "暂无数据";
    const valueCount = top ? count(top.count) + " 条" : "--";
    return '<article class="feature-card"><h3>' + label + '</h3><p title="' + esc(value) + '">' +
      esc(value) + '</p><small>' + valueCount + '</small></article>';
  }).join("");
}

function drawChart(points) {
  const canvas = $("#trendChart");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * dpr);
  canvas.height = Math.max(1, rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const width = rect.width, height = rect.height;
  ctx.clearRect(0, 0, width, height);
  if (!points.length) return;
  const pad = { top: 18, right: 12, bottom: 34, left: 42 };
  const max = Math.max(...points.map((point) => point[1]), 1);
  ctx.strokeStyle = "#e6eeeb";
  ctx.fillStyle = "#72817e";
  ctx.font = "10px system-ui";
  ctx.textAlign = "right";
  for (let i = 0; i <= 3; i++) {
    const y = pad.top + (height - pad.top - pad.bottom) * i / 3;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(count(Math.round(max * (1 - i / 3))), pad.left - 8, y + 3);
  }
  const x = (index) => pad.left + (width - pad.left - pad.right) * (points.length === 1 ? .5 : index / (points.length - 1));
  const y = (value) => pad.top + (height - pad.top - pad.bottom) * (1 - value / max);
  ctx.strokeStyle = "#1f7a62"; ctx.lineWidth = 2.5; ctx.beginPath();
  points.forEach((point, index) => index ? ctx.lineTo(x(index), y(point[1])) : ctx.moveTo(x(index), y(point[1])));
  ctx.stroke();
  ctx.fillStyle = "#1f7a62";
  points.forEach((point, index) => { ctx.beginPath(); ctx.arc(x(index), y(point[1]), 3, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = "#72817e"; ctx.textAlign = "center";
  const step = Math.max(1, Math.ceil(points.length / 7));
  points.forEach((point, index) => { if (index % step === 0 || index === points.length - 1) ctx.fillText(point[0], x(index), height - 10); });
}

function updateMetrics() {
  const info = categoryInfo();
  $("#metricCount").textContent = count(info.matching_records);
  $("#metricRange").textContent = formatDate(info.first_registration_date) + " – " + formatDate(info.last_registration_date);
  const points = state.monthly[state.category] || [];
  const peak = points.reduce((best, item) => item.registrations > best.registrations ? item : best, points[0] || { month: "--", registrations: 0 });
  $("#metricPeak").textContent = peak.month;
  $("#metricPeakNote").textContent = count(peak.registrations) + " 条登记";
  $("#insightText").innerHTML = (state.summary.insights[state.category] || []).map((item) =>
    esc(item).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
  ).join(" ");
  $("#scopeText").textContent = state.category === "pv"
    ? "阳台光伏 = 登记日期 > 2023-01-01 且 Art der Solaranlage 精确等于 Steckerfertige Solaranlage (sog. Balkonkraftwerk)。"
    : "阳台储能 = 登记日期 > 2023-01-01、Nettonennleistung der Einheit = 0.8 kW、Energieträger = Speicher。官方 CSV 的 0,8 已按数值 0.8 处理。";
}

function switchCategory(category) {
  state.category = category;
  state.records = [];
  state.filtered = [];
  document.querySelectorAll(".category-button").forEach((button) =>
    button.classList.toggle("active", button.dataset.category === category)
  );
  updateMetrics();
  populateFilters();
  renderTable();
  loadCategoryRecords(category);
}

function downloadCurrentCsv() {
  const headers = ["登记日期", "MaStR编号", "名称", "州", "Landkreis", "Gemeinde", "Ort", "功率", "技术/能源", "运行状态"];
  const rows = [headers].concat(state.filtered.map((row) => [
    row.registered, row.id, row.name, row.state, row.district, row.municipality, row.town, row.power,
    state.category === "pv" ? row.solarTech : row.storageTech, row.status
  ]));
  const text = rows.map((line) => line.map((value) => '"' + String(value || "").replace(/"/g, '""') + '"').join(",")).join("\n");
  const blob = new Blob(["\ufeff" + text], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "mastr_" + (state.category === "pv" ? "balcony_pv" : "balcony_storage") + "_filtered.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}

async function init() {
  try {
    const results = await Promise.all([
      fetch("data/summary.json").then((response) => response.json()),
      fetch("data/monthly.json").then((response) => response.json())
    ]);
    state.summary = results[0];
    state.monthly = results[1];
    state.features = await fetch("data/features.json").then((response) => response.json());
    $("#exportName").textContent = state.summary.source_export;
    $("#generatedAt").textContent = "生成于 " + state.summary.generated_at_utc;
    $("#pvSwitchCount").textContent = count(state.summary.categories.pv.matching_records) + " 条";
    $("#storageSwitchCount").textContent = count(state.summary.categories.storage.matching_records) + " 条";
    updateMetrics();
    await loadCategoryRecords("pv");
  } catch (error) {
    setStatus("汇总数据加载失败");
    $("#insightText").textContent = "无法读取在线看板数据。";
    console.error(error);
  }
}

document.querySelectorAll(".category-button").forEach((button) =>
  button.addEventListener("click", () => switchCategory(button.dataset.category))
);
["searchInput", "stateFilter", "districtFilter", "statusFilter", "technologyFilter"].forEach((selector) =>
  $(selector).addEventListener("input", applyFilters)
);
$("#trendMode").addEventListener("change", () => drawTrend(state.filtered));
$("#pageSize").addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; renderTable(); });
$("#prevPage").addEventListener("click", () => { state.page--; renderTable(); });
$("#nextPage").addEventListener("click", () => { state.page++; renderTable(); });
$("#resetButton").addEventListener("click", () => {
  ["searchInput", "stateFilter", "districtFilter", "statusFilter", "technologyFilter"].forEach((selector) => { $(selector).value = ""; });
  applyFilters();
});
$("#downloadButton").addEventListener("click", downloadCurrentCsv);
document.querySelectorAll("th[data-sort]").forEach((header) => header.addEventListener("click", () => {
  const key = header.dataset.sort;
  if (state.sortKey === key) state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  else { state.sortKey = key; state.sortDirection = "asc"; }
  renderTable();
}));
window.addEventListener("resize", () => drawTrend(state.filtered));
init();
