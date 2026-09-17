const state = {
  summary: null,
  monthly: null,
  features: null,
  brands: null,
  filteredBrandStats: null,
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
  resultCount: 0,
  trendPoints: [],
  trendHoverIndex: null,
  trendGeometry: null,
  brandPieSlices: []
};

const $ = (selector) => document.querySelector(selector);
const nf = new Intl.NumberFormat("zh-CN");
const count = (value) => nf.format(Number(value || 0));
const percent = (value) => Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + "%";
const statePalette = ["#16816b", "#e4a22d", "#297fb5", "#c65b68", "#896dc0", "#629b61", "#d1783a", "#4a9398"];
const brandPalette = ["#16816b", "#e4a22d", "#297fb5", "#c65b68", "#896dc0", "#629b61"];
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
  $("#stateBars").innerHTML = top.length ? top.map((item, index) => {
    const description = item.value + " · " + count(item.count) + " 条登记";
    return '<div class="bar-row" tabindex="0" role="listitem" aria-label="' + esc(description) + '" style="--bar-color:' + statePalette[index % statePalette.length] + '">' +
      '<span title="' + esc(item.value) + '">' + esc(item.value) + '</span><span class="bar-track"><i class="bar-fill" style="width:' +
      (item.count / max * 100) + '%"></i></span><span class="bar-value">' + count(item.count) + "</span>" +
      '<span class="bar-tooltip" role="tooltip"><strong>' + esc(item.value) + "</strong><span>" + count(item.count) + " 条登记</span></span></div>";
  }).join("") : '<div class="empty-state">暂无区域数据</div>';
}

function drawTrend(points) {
  state.trendPoints = points;
  if (state.trendHoverIndex != null && state.trendHoverIndex >= points.length) state.trendHoverIndex = null;
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
  state.trendGeometry = { width, height, pad, max };
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
  points.forEach((point, index) => {
    ctx.beginPath();
    ctx.arc(x(index), y(point.registrations), index === state.trendHoverIndex ? 5 : 3, 0, Math.PI * 2);
    ctx.fill();
  });
  if (state.trendHoverIndex != null) {
    const point = points[state.trendHoverIndex];
    ctx.beginPath();
    ctx.arc(x(state.trendHoverIndex), y(point.registrations), 7, 0, Math.PI * 2);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.fillStyle = "#72817e";
  ctx.textAlign = "center";
  const step = Math.max(1, Math.ceil(points.length / 7));
  points.forEach((point, index) => { if (index % step === 0 || index === points.length - 1) ctx.fillText(point.month, x(index), height - 10); });
}

function clearTrendHover() {
  const wasVisible = state.trendHoverIndex != null;
  state.trendHoverIndex = null;
  $("#trendTooltip").classList.remove("visible");
  if (wasVisible && state.trendPoints.length) drawTrend(state.trendPoints);
}

function updateTrendTooltip(event) {
  const canvas = $("#trendChart");
  const geometry = state.trendGeometry;
  if (!geometry || !state.trendPoints.length) return;
  const rect = canvas.getBoundingClientRect();
  const localX = event.clientX - rect.left;
  const plotWidth = geometry.width - geometry.pad.left - geometry.pad.right;
  if (localX < geometry.pad.left - 12 || localX > geometry.width - geometry.pad.right + 12) {
    clearTrendHover();
    return;
  }
  const index = Math.max(0, Math.min(state.trendPoints.length - 1,
    Math.round((localX - geometry.pad.left) / plotWidth * (state.trendPoints.length - 1))));
  if (index !== state.trendHoverIndex) {
    state.trendHoverIndex = index;
    drawTrend(state.trendPoints);
  }
  const point = state.trendPoints[index];
  const pointY = geometry.pad.top + (geometry.height - geometry.pad.top - geometry.pad.bottom) * (1 - point.registrations / geometry.max);
  const tooltip = $("#trendTooltip");
  const chartWrap = canvas.parentElement;
  const tooltipX = Math.max(74, Math.min(chartWrap.clientWidth - 74, canvas.offsetLeft + geometry.pad.left + plotWidth *
    (state.trendPoints.length === 1 ? .5 : index / (state.trendPoints.length - 1))));
  tooltip.innerHTML = "<strong>" + esc(point.month) + "</strong><span>" + count(point.registrations) + " 条登记</span>";
  tooltip.style.left = tooltipX + "px";
  tooltip.style.top = Math.max(30, canvas.offsetTop + pointY) + "px";
  tooltip.classList.add("visible");
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

function brandStatsForView() {
  return state.recordsLoaded && state.filteredBrandStats ? state.filteredBrandStats : state.brands;
}

function clearBrandPieTooltip() {
  $("#brandPieTooltip").classList.remove("visible");
}

function drawBrandBars(brandStats) {
  const brands = brandStats.brands || [];
  const max = Math.max(...brands.map((item) => Number(item.registrations || 0)), 1);
  $("#brandBars").innerHTML = brands.map((item, index) => {
    const share = Number(brandStats.total_records) ? Number(item.registrations || 0) / Number(brandStats.total_records) * 100 : 0;
    const description = item.brand + " · " + count(item.registrations) + " 条登记，占阳台储能 " + percent(share);
    return '<div class="brand-bar-row" tabindex="0" role="listitem" aria-label="' + esc(description) + '" style="--brand-color:' + brandPalette[index % brandPalette.length] + '">' +
      '<span class="brand-bar-label">' + esc(item.brand) + '</span><span class="brand-bar-track"><i class="brand-bar-fill" style="width:' +
      (Number(item.registrations || 0) / max * 100) + '%"></i></span><span class="brand-bar-value">' + count(item.registrations) + "</span>" +
      '<span class="brand-bar-tooltip" role="tooltip"><strong>' + esc(item.brand) + "</strong><span>" + count(item.registrations) + " 条登记 · " + percent(share) + "</span></span></div>";
  }).join("");
}

function drawBrandPie(brandStats) {
  const canvas = $("#brandPie");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = rect.width;
  const height = rect.height;
  canvas.width = Math.max(1, width * dpr);
  canvas.height = Math.max(1, height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  const total = Number(brandStats.total_records || 0);
  const branded = Number(brandStats.any_selected_brand_records || 0);
  const entries = [
    { label: "六品牌关键词命中", value: branded, color: "#16816b" },
    { label: "其他阳台储能登记", value: Math.max(0, total - branded), color: "#dce7e2" }
  ];
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.max(18, Math.min(width, height) / 2 - 20);
  const innerRadius = radius * .58;
  let start = 0;
  state.brandPieSlices = [];
  entries.forEach((item) => {
    const angle = total ? item.value / total * Math.PI * 2 : 0;
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.fillStyle = item.color;
    ctx.arc(centerX, centerY, radius, start - Math.PI / 2, start + angle - Math.PI / 2);
    ctx.closePath();
    ctx.fill();
    state.brandPieSlices.push({ ...item, start, end: start + angle, centerX, centerY, radius, innerRadius });
    start += angle;
  });
  ctx.beginPath();
  ctx.fillStyle = "#ffffff";
  ctx.arc(centerX, centerY, innerRadius, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#17242a";
  ctx.font = "700 21px system-ui";
  ctx.textAlign = "center";
  ctx.fillText(percent(brandStats.selected_brand_share_pct), centerX, centerY - 2);
  ctx.fillStyle = "#6d7a7e";
  ctx.font = "11px system-ui";
  ctx.fillText("六品牌合计", centerX, centerY + 17);
  $("#brandPieLegend").innerHTML = entries.map((item) =>
    '<span><i style="background:' + item.color + '"></i>' + esc(item.label) + " · " + count(item.value) + " 条</span>"
  ).join("");
}

function updateBrandPieTooltip(event) {
  const canvas = $("#brandPie");
  const rect = canvas.getBoundingClientRect();
  const first = state.brandPieSlices[0];
  if (!first) return;
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const distance = Math.hypot(x - first.centerX, y - first.centerY);
  if (distance < first.innerRadius || distance > first.radius) {
    clearBrandPieTooltip();
    return;
  }
  const angle = (Math.atan2(y - first.centerY, x - first.centerX) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2);
  const slice = state.brandPieSlices.find((item) => angle >= item.start && angle <= item.end) || state.brandPieSlices.at(-1);
  const tooltip = $("#brandPieTooltip");
  const total = Number(brandStatsForView().total_records || 0);
  tooltip.innerHTML = "<strong>" + esc(slice.label) + "</strong><span>" + count(slice.value) + " 条 · " + percent(total ? slice.value / total * 100 : 0) + "</span>";
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
  tooltip.classList.add("visible");
}

function renderBrandPanel() {
  const panel = $("#brandPanel");
  const visible = state.category === "storage";
  panel.classList.toggle("hidden", !visible);
  clearBrandPieTooltip();
  if (!visible) return;
  const brandStats = brandStatsForView();
  if (!brandStats) {
    $("#brandBars").innerHTML = '<div class="empty-state">品牌统计正在加载</div>';
    $("#brandPieLegend").innerHTML = "";
    return;
  }
  const filtered = state.recordsLoaded && state.filteredBrandStats && activeFilter();
  $("#brandPanelNote").textContent = filtered ? "随当前原表筛选更新" : "阳台储能原表全量";
  $("#brandBarCaption").textContent = count(brandStats.total_records) + " 条原表记录";
  $("#brandShareCaption").textContent = percent(brandStats.selected_brand_share_pct) + " 的登记命中六品牌";
  drawBrandBars(brandStats);
  drawBrandPie(brandStats);
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
  renderBrandPanel();
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
    state.filteredBrandStats = message.brandStats;
    drawTrend(message.trend);
    drawStateBars(message.states);
    drawFeatures();
    renderBrandPanel();
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
  state.trendHoverIndex = null;
  $("#trendTooltip").classList.remove("visible");
  state.recordsLoaded = false;
  state.loadingRecords = false;
  state.filterOptions = null;
  state.filteredBrandStats = null;
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
    const [summary, monthly, features, brands] = await Promise.all([
      fetch("data/summary.json").then((response) => response.json()),
      fetch("data/monthly.json").then((response) => response.json()),
      fetch("data/features.json").then((response) => response.json()),
      fetch("data/brands.json").then((response) => response.ok ? response.json() : null)
    ]);
    state.summary = summary;
    state.monthly = monthly;
    state.features = features;
    state.brands = brands;
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
$("#trendChart").addEventListener("pointermove", updateTrendTooltip);
$("#trendChart").addEventListener("pointerleave", clearTrendHover);
$("#trendChart").addEventListener("blur", clearTrendHover);
$("#brandPie").addEventListener("pointermove", updateBrandPieTooltip);
$("#brandPie").addEventListener("pointerleave", clearBrandPieTooltip);
$("#brandPie").addEventListener("blur", clearBrandPieTooltip);
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
