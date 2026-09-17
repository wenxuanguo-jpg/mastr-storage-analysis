const state = {
  summary: null,
  monthly: null,
  features: null,
  category: "pv",
  worker: null,
  recordsLoaded: false,
  loadingRecords: false,
  filterOptions: null,
  page: 1,
  pageSize: 25,
  sortKey: "registered",
  sortDirection: "desc",
  pageRows: [],
  totalPages: 1,
  resultCount: 0
};

const $ = (selector) => document.querySelector(selector);
const nf = new Intl.NumberFormat("zh-CN");
const count = (value) => nf.format(Number(value || 0));
const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[c]
);

function setStatus(text) { $("#dataStatus").textContent = text; }
function categoryInfo() { return state.summary.categories[state.category]; }

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

function activeFilter() {
  return ["#searchInput", "#stateFilter", "#districtFilter", "#statusFilter", "#technologyFilter"]
    .some((selector) => $(selector).value);
}

function selectedFilters() {
  return {
    search: $("#searchInput").value.trim(),
    state: $("#stateFilter").value,
    district: $("#districtFilter").value,
    status: $("#statusFilter").value,
    technology: $("#technologyFilter").value
  };
}

function fillSelect(select, values, placeholder) {
  const current = select.value;
  select.innerHTML = '<option value="">' + placeholder + "</option>" +
    values.map((value) => '<option value="' + esc(value) + '">' + esc(value) + "</option>").join("");
  if (values.includes(current)) select.value = current;
}

function populateFilters() {
  if (!state.filterOptions) return;
  fillSelect($("#stateFilter"), state.filterOptions.state, "全部州");
  fillSelect($("#districtFilter"), state.filterOptions.district, "全部地区");
  fillSelect($("#statusFilter"), state.filterOptions.status, "全部状态");
  fillSelect($("#technologyFilter"), state.filterOptions.technology, "全部");
  $("#technologyFilterWrap span").textContent = state.category === "pv" ? "发电技术" : "电池技术";
}

function setFilterControls(enabled) {
  ["#searchInput", "#stateFilter", "#districtFilter", "#statusFilter", "#technologyFilter", "#pageSize", "#downloadButton", "#resetButton"]
    .forEach((selector) => { $(selector).disabled = !enabled; });
}

function drawStateBars(entries) {
  const top = entries.slice(0, 8);
  const max = top[0] ? top[0].count : 1;
  $("#stateBars").innerHTML = top.length ? top.map((item) =>
    '<div class="bar-row"><span title="' + esc(item.value) + '">' + esc(item.value) + '</span><span class="bar-track"><i class="bar-fill" style="width:' +
    (item.count / max * 100) + '%"></i></span><span class="bar-value">' + count(item.count) + "</span></div>"
  ).join("") : '<div class="empty-state">暂无区域数据</div>';
}

function drawTrend(points) {
  const canvas = $("#trendChart");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * dpr);
  canvas.height = Math.max(1, rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);
  if (!points.length) return;
  const pad = { top: 18, right: 12, bottom: 34, left: 42 };
  const max = Math.max(...points.map((point) => point.registrations), 1);
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
  ctx.strokeStyle = "#1f7a62";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((point, index) => index ? ctx.lineTo(x(index), y(point.registrations)) : ctx.moveTo(x(index), y(point.registrations)));
  ctx.stroke();
  ctx.fillStyle = "#1f7a62";
  points.forEach((point, index) => { ctx.beginPath(); ctx.arc(x(index), y(point.registrations), 3, 0, Math.PI * 2); ctx.fill(); });
  ctx.fillStyle = "#72817e";
  ctx.textAlign = "center";
  const step = Math.max(1, Math.ceil(points.length / 7));
  points.forEach((point, index) => { if (index % step === 0 || index === points.length - 1) ctx.fillText(point.month, x(index), height - 10); });
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
    return '<article class="feature-card"><h3>' + label + "</h3><p title=\"" + esc(value) + '\">' + esc(value) + "</p><small>" + valueCount + "</small></article>";
  }).join("");
}

function updateMetrics() {
  const info = categoryInfo();
  $("#metricCount").textContent = count(info.matching_records);
  $("#metricRange").textContent = formatDate(info.first_registration_date) + " – " + formatDate(info.last_registration_date);
  const points = state.monthly[state.category] || [];
  const peak = points.reduce((best, item) => item.registrations > best.registrations ? item : best, points[0] || { month: "--", registrations: 0 });
  $("#metricPeak").textContent = peak.month;
  $("#metricPeakNote").textContent = count(peak.registrations) + " 条登记";
  $("#metricLoaded").textContent = state.recordsLoaded ? count(state.resultCount) + " 条明细已载入" : "完整明细按需加载";
  $("#insightText").innerHTML = (state.summary.insights[state.category] || []).map((item) =>
    esc(item).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
  ).join(" ");
  $("#scopeText").textContent = state.category === "pv"
    ? "阳台光伏 = 登记日期 > 2023-01-01 且 Art der Solaranlage 精确等于 Steckerfertige Solaranlage (sog. Balkonkraftwerk)。"
    : "阳台储能 = 登记日期 > 2023-01-01、Nettonennleistung der Einheit = 0.8 kW、Energieträger = Speicher。官方 CSV 的 0,8 已按数值 0.8 处理。";
  if (!state.recordsLoaded) {
    drawTrend(points);
    drawStateBars((state.features[state.category].state || []).slice(0, 8));
    drawFeatures();
  }
}

function renderTable() {
  const body = $("#recordBody");
  if (!state.recordsLoaded) {
    body.innerHTML = "";
    $("#emptyState").classList.remove("hidden");
    $("#emptyState").textContent = state.loadingRecords ? "正在后台读取和索引明细..." : "点击加载当前类别明细后可筛选完整原表";
    $("#resultCount").textContent = state.loadingRecords ? "正在准备明细" : "完整明细按需加载";
    $("#pageLabel").textContent = "第 -- 页";
    $("#prevPage").disabled = true;
    $("#nextPage").disabled = true;
    return;
  }
  body.innerHTML = state.pageRows.map((row) => {
    const tech = state.category === "pv" ? row.solarTech : row.storageTech;
    return "<tr><td>" + esc(formatDate(row.registered)) + "</td>" +
      '<td><strong title="' + esc(row.name) + '">' + esc(row.name || "未提供名称") + "</strong><small>" + esc(row.id) + "</small></td>" +
      "<td>" + esc(row.state || "--") + "</td><td>" + esc(row.district || "--") + "<small>" + esc(row.town || row.municipality || "") + "</small></td>" +
      "<td>" + esc(row.power || "--") + " kW</td><td><span class=\"tag\">" + esc(tech || row.energy || "--") + '</span><span class="tag status">' + esc(row.status || "--") + "</span></td></tr>";
  }).join("");
  $("#emptyState").classList.toggle("hidden", state.pageRows.length > 0);
  $("#resultCount").textContent = count(state.resultCount) + " 条符合当前条件";
  $("#pageLabel").textContent = "第 " + state.page + " / " + state.totalPages + " 页";
  $("#prevPage").disabled = state.page <= 1;
  $("#nextPage").disabled = state.page >= state.totalPages;
}

function queryRecords() {
  if (!state.worker || !state.recordsLoaded) return;
  state.worker.postMessage({ type: "query", category: state.category, filters: selectedFilters(), page: state.page, pageSize: state.pageSize, sortKey: state.sortKey, sortDirection: state.sortDirection, trendMode: $("#trendMode").value });
}

function applyFilters() {
  state.page = 1;
  $("#metricFilter").textContent = activeFilter() ? "已筛选" : "全量";
  queryRecords();
}

function handleWorkerMessage(event) {
  const message = event.data;
  if (message.category !== state.category) return;
  if (message.type === "progress") {
    $("#resultCount").textContent = "已读取 " + count(message.count) + " 条明细";
  } else if (message.type === "ready") {
    state.loadingRecords = false;
    state.recordsLoaded = true;
    state.filterOptions = message.options;
    setFilterControls(true);
    $("#loadRecordsButton").disabled = true;
    $("#loadRecordsButton").textContent = "明细已载入";
    setStatus("数据已更新");
    populateFilters();
    updateMetrics();
    queryRecords();
  } else if (message.type === "result") {
    state.page = message.page;
    state.pageRows = message.rows;
    state.resultCount = message.total;
    state.totalPages = message.totalPages;
    drawTrend(message.trend);
    drawStateBars(message.states);
    drawFeatures();
    renderTable();
  } else if (message.type === "download") {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(message.blob);
    link.download = message.filename;
    link.click();
    URL.revokeObjectURL(link.href);
  } else if (message.type === "error") {
    state.loadingRecords = false;
    setStatus("明细加载失败");
    $("#emptyState").classList.remove("hidden");
    $("#emptyState").textContent = "明细加载失败：" + message.error;
  }
}

function loadCategoryRecords() {
  if (state.loadingRecords || state.recordsLoaded) return;
  state.loadingRecords = true;
  setStatus("正在读取明细");
  setFilterControls(false);
  $("#loadRecordsButton").disabled = true;
  $("#loadRecordsButton").textContent = "正在加载明细";
  renderTable();
  state.worker = new Worker("records-worker.js");
  state.worker.addEventListener("message", handleWorkerMessage);
  state.worker.addEventListener("error", (event) => handleWorkerMessage({ data: { type: "error", category: state.category, error: event.message || "Worker unavailable" } }));
  state.worker.postMessage({ type: "load", category: state.category, path: "data/records_" + state.category + ".ndjson.gz" });
}

function resetRecordView() {
  state.recordsLoaded = false;
  state.loadingRecords = false;
  state.filterOptions = null;
  state.page = 1;
  state.pageRows = [];
  state.resultCount = 0;
  state.totalPages = 1;
  ["#searchInput", "#stateFilter", "#districtFilter", "#statusFilter", "#technologyFilter"].forEach((selector) => { $(selector).value = ""; });
  setFilterControls(false);
  $("#loadRecordsButton").disabled = false;
  $("#loadRecordsButton").textContent = "加载" + (state.category === "pv" ? "阳台光伏" : "阳台储能") + "明细";
}

function switchCategory(category) {
  if (state.worker) state.worker.terminate();
  state.worker = null;
  state.category = category;
  document.querySelectorAll(".category-button").forEach((button) => button.classList.toggle("active", button.dataset.category === category));
  resetRecordView();
  updateMetrics();
  renderTable();
}

function downloadCurrentCsv() {
  if (!state.worker || !state.recordsLoaded) return;
  state.worker.postMessage({ type: "download", category: state.category, filters: selectedFilters(), sortKey: state.sortKey, sortDirection: state.sortDirection });
}

async function init() {
  try {
    const [summary, monthly, features] = await Promise.all([
      fetch("data/summary.json").then((response) => response.json()),
      fetch("data/monthly.json").then((response) => response.json()),
      fetch("data/features.json").then((response) => response.json())
    ]);
    state.summary = summary;
    state.monthly = monthly;
    state.features = features;
    $("#exportName").textContent = state.summary.source_export;
    $("#generatedAt").textContent = "生成于 " + state.summary.generated_at_utc;
    $("#pvSwitchCount").textContent = count(state.summary.categories.pv.matching_records) + " 条";
    $("#storageSwitchCount").textContent = count(state.summary.categories.storage.matching_records) + " 条";
    resetRecordView();
    updateMetrics();
    renderTable();
    setStatus("汇总数据已更新");
  } catch (error) {
    setStatus("汇总数据加载失败");
    $("#insightText").textContent = "无法读取在线看板数据。";
    console.error(error);
  }
}

document.querySelectorAll(".category-button").forEach((button) => button.addEventListener("click", () => switchCategory(button.dataset.category)));
["#searchInput", "#stateFilter", "#districtFilter", "#statusFilter", "#technologyFilter"].forEach((selector) => $(selector).addEventListener("input", applyFilters));
$("#trendMode").addEventListener("change", () => state.recordsLoaded ? queryRecords() : updateMetrics());
$("#pageSize").addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; queryRecords(); });
$("#prevPage").addEventListener("click", () => { state.page--; queryRecords(); });
$("#nextPage").addEventListener("click", () => { state.page++; queryRecords(); });
$("#loadRecordsButton").addEventListener("click", loadCategoryRecords);
$("#resetButton").addEventListener("click", () => {
  ["#searchInput", "#stateFilter", "#districtFilter", "#statusFilter", "#technologyFilter"].forEach((selector) => { $(selector).value = ""; });
  applyFilters();
});
$("#downloadButton").addEventListener("click", downloadCurrentCsv);
document.querySelectorAll("th[data-sort]").forEach((header) => header.addEventListener("click", () => {
  const key = header.dataset.sort;
  if (state.sortKey === key) state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  else { state.sortKey = key; state.sortDirection = "asc"; }
  queryRecords();
}));
window.addEventListener("resize", () => { if (state.summary) updateMetrics(); });
init();
