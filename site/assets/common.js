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

/* 排序类条形图的顺序色阶：数值越高颜色越深（单色渐变，避免彩虹色干扰排序阅读）。 */
const SEQ_RAMP = ["#f7ddc4", "#e8a45c", "#d97706", "#a34a05"];

function markActiveNav() {
  const page = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("nav a").forEach((a) => {
    const href = a.getAttribute("href");
    if (href === page) a.classList.add("active");
  });
}

document.addEventListener("DOMContentLoaded", markActiveNav);
