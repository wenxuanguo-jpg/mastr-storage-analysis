let category = "";
let records = [];
const BRAND_DEFINITIONS = [
  { brand: "Zendure", keywords: ["zendure"] },
  { brand: "Anker", keywords: ["anker"] },
  { brand: "EcoFlow", keywords: ["ecoflow"] },
  { brand: "Marstek", keywords: ["marstek"] },
  { brand: "Growatt", keywords: ["growatt"] },
  { brand: "Jackery", keywords: ["jackery"] }
];

function recordDate(raw) {
  const value = String(raw || "");
  let match = value.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (match) return match[1] + "-" + String(match[2]).padStart(2, "0") + "-" + String(match[3]).padStart(2, "0");
  match = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})/);
  return match ? match[3] + "-" + String(match[2]).padStart(2, "0") + "-" + String(match[1]).padStart(2, "0") : value;
}

function technologyKey() { return category === "pv" ? "solarTech" : "storageTech"; }

function matches(row, filters) {
  const search = String(filters.search || "").toLocaleLowerCase();
  const haystack = [row.id, row.name, row.state, row.district, row.municipality, row.town, row.zip]
    .join(" ").toLocaleLowerCase();
  return (!search || haystack.includes(search)) &&
    (!filters.state || row.state === filters.state) &&
    (!filters.district || row.district === filters.district) &&
    (!filters.status || row.status === filters.status) &&
    (!filters.technology || row[technologyKey()] === filters.technology);
}

function compareRows(leftRow, rightRow, sortKey, sortDirection) {
  let left = sortKey === "registered" ? recordDate(leftRow.registered) : (leftRow[sortKey] || "");
  let right = sortKey === "registered" ? recordDate(rightRow.registered) : (rightRow[sortKey] || "");
  if (sortKey === "power") {
    left = parseFloat(String(left).replace(",", ".")) || 0;
    right = parseFloat(String(right).replace(",", ".")) || 0;
  } else {
    left = String(left).toLocaleLowerCase();
    right = String(right).toLocaleLowerCase();
  }
  const result = left < right ? -1 : left > right ? 1 : 0;
  return sortDirection === "asc" ? result : -result;
}

function filterOptions() {
  const unique = (key) => [...new Set(records.map((row) => row[key]).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "de"));
  return {
    state: unique("state"),
    district: unique("district"),
    status: unique("status"),
    technology: unique(technologyKey())
  };
}

function groupedTrend(rows, mode) {
  const groups = new Map();
  rows.forEach((row) => {
    const date = recordDate(row.registered);
    const month = mode === "annual" ? date.slice(0, 4) : date.slice(0, 7);
    if (month.length >= 4) groups.set(month, (groups.get(month) || 0) + 1);
  });
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))
    .map(([month, registrations]) => ({ month, registrations }));
}

function groupedStates(rows) {
  const counts = new Map();
  rows.forEach((row) => {
    const value = row.state || "未提供";
    counts.set(value, (counts.get(value) || 0) + 1);
  });
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
    .map(([value, count]) => ({ value, count }));
}

function brandKeywordSummary(rows) {
  const counts = new Map(BRAND_DEFINITIONS.map((item) => [item.brand, 0]));
  let anySelectedBrandRecords = 0;
  let multipleKeywordRecords = 0;
  rows.forEach((row) => {
    const name = String(row.name || "").toLocaleLowerCase();
    const matched = BRAND_DEFINITIONS.filter((item) => item.keywords.some((keyword) => name.includes(keyword)));
    matched.forEach((item) => counts.set(item.brand, counts.get(item.brand) + 1));
    if (matched.length) anySelectedBrandRecords++;
    if (matched.length > 1) multipleKeywordRecords++;
  });
  return {
    field: "Anzeige-Name der Einheit",
    matching_rule: "case-insensitive substring",
    total_records: rows.length,
    any_selected_brand_records: anySelectedBrandRecords,
    other_records: rows.length - anySelectedBrandRecords,
    selected_brand_share_pct: rows.length ? anySelectedBrandRecords / rows.length * 100 : 0,
    multiple_keyword_records: multipleKeywordRecords,
    brands: BRAND_DEFINITIONS.map((item) => ({
      brand: item.brand,
      keywords: item.keywords,
      registrations: counts.get(item.brand)
    }))
  };
}

function query(message) {
  const filtered = records.filter((row) => matches(row, message.filters));
  filtered.sort((left, right) => compareRows(left, right, message.sortKey, message.sortDirection));
  const totalPages = Math.max(1, Math.ceil(filtered.length / message.pageSize));
  const page = Math.min(message.page, totalPages);
  const start = (page - 1) * message.pageSize;
  postMessage({
    type: "result",
    category,
    total: filtered.length,
    totalPages,
    page,
    rows: filtered.slice(start, start + message.pageSize),
    trend: groupedTrend(filtered, message.trendMode),
    states: groupedStates(filtered),
    brandStats: category === "storage" ? brandKeywordSummary(filtered) : null
  });
}

async function load(message) {
  category = message.category;
  records = [];
  const response = await fetch(message.path);
  if (!response.ok) throw new Error(message.path + ": HTTP " + response.status);
  if (!self.DecompressionStream) throw new Error("当前浏览器不支持 gzip 解压");
  const reader = response.body.pipeThrough(new DecompressionStream("gzip")).getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastReported = 0;
  const addLines = (text) => {
    buffer += text;
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    lines.forEach((line) => { if (line) records.push(JSON.parse(line)); });
    if (records.length - lastReported >= 25000) {
      lastReported = records.length;
      postMessage({ type: "progress", category, count: records.length });
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    addLines(decoder.decode(value, { stream: true }));
  }
  addLines(decoder.decode());
  if (buffer.trim()) records.push(JSON.parse(buffer));
  postMessage({ type: "ready", category, count: records.length, options: filterOptions() });
}

function download(message) {
  const filtered = records.filter((row) => matches(row, message.filters));
  filtered.sort((left, right) => compareRows(left, right, message.sortKey, message.sortDirection));
  const headers = ["登记日期", "MaStR编号", "名称", "州", "Landkreis", "Gemeinde", "Ort", "功率", "技术/能源", "运行状态"];
  const rows = [headers].concat(filtered.map((row) => [
    row.registered, row.id, row.name, row.state, row.district, row.municipality, row.town, row.power,
    category === "pv" ? row.solarTech : row.storageTech, row.status
  ]));
  const csv = rows.map((line) => line.map((value) => '"' + String(value || "").replace(/"/g, '""') + '"').join(",")).join("\n");
  postMessage({
    type: "download",
    category,
    filename: "mastr_" + (category === "pv" ? "balcony_pv" : "balcony_storage") + "_filtered.csv",
    blob: new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" })
  });
}

self.addEventListener("message", async (event) => {
  try {
    const message = event.data;
    if (message.type === "load") await load(message);
    if (message.type === "query") query(message);
    if (message.type === "download") download(message);
  } catch (error) {
    postMessage({ type: "error", category: event.data.category || category, error: error.message || String(error) });
  }
});
