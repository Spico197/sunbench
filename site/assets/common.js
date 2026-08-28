/* Shared helpers for SunBench site pages. */

async function loadJSON(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error("加载失败: " + path);
  return resp.json();
}

function pct(p, digits) {
  if (p === null || p === undefined) return "n/a";
  return (p * 100).toFixed(digits === undefined ? 1 : digits) + "%";
}

/* 倾向标签：基于 P(give) 与 unclear 占比。 */
function tendencyOf(stats) {
  const p = stats.positive_probability;
  const completed = stats.completed_count || 0;
  const unclearRatio = completed ? (stats.unknown_count || 0) / completed : 0;
  if (unclearRatio >= 0.5) return { label: "惜字如金 / 多半含糊", cls: "t-mid" };
  if (p === null || p === undefined) return { label: "无有效数据", cls: "t-mid" };
  if (p >= 0.9) return { label: "有求必应", cls: "t-give" };
  if (p >= 0.6) return { label: "倾向给", cls: "t-give" };
  if (p >= 0.4) return { label: "摇摆不定", cls: "t-mid" };
  return { label: "倾向不给", cls: "t-not" };
}

const VENDOR_PALETTE = [
  "#c2570b", "#2da44e", "#0969da", "#8250df", "#bf3989",
  "#9a6700", "#1b7c83", "#d4a72c", "#57606a", "#cf222e",
  "#6e7781", "#0550ae", "#7d4e00", "#116329", "#953800",
  "#0a7ea4", "#b35900", "#4a3dbb",
];

function vendorColors(models) {
  const vendors = [...new Set(models.map((m) => m.vendor))];
  const map = {};
  vendors.forEach((v, i) => (map[v] = VENDOR_PALETTE[i % VENDOR_PALETTE.length]));
  return map;
}

function markActiveNav() {
  const page = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("nav a").forEach((a) => {
    const href = a.getAttribute("href");
    if (href === page) a.classList.add("active");
  });
}

document.addEventListener("DOMContentLoaded", markActiveNav);
