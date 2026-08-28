/* Model detail page */
(async function () {
  const modelsData = await loadJSON("data/models.json");
  const models = modelsData.models;
  const picker = document.getElementById("picker");
  picker.innerHTML = models
    .map((m) => `<option value="${m.name}">${m.name}（${m.vendor}）</option>`)
    .join("");

  const params = new URLSearchParams(location.search);
  let current = params.get("m") || models[0].name;
  if (!models.some((m) => m.name === current)) current = models[0].name;
  picker.value = current;
  picker.addEventListener("change", () => {
    history.replaceState(null, "", "?m=" + encodeURIComponent(picker.value));
    render(picker.value);
  });

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function avg(nums) {
    const xs = nums.filter((x) => typeof x === "number");
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  }

  function analysisBlock(title, obj, fields) {
    if (!obj) return "";
    const rows = fields
      .filter(([k]) => obj[k] !== undefined && obj[k] !== null && obj[k] !== "")
      .map(([k, label]) => {
        const v = obj[k];
        const body = Array.isArray(v)
          ? `<ul>${v.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
          : esc(v);
        return `<dt>${label}</dt><dd>${body}</dd>`;
      })
      .join("");
    return rows ? `<h3>${title}</h3><dl class="analysis">${rows}</dl>` : "";
  }

  async function render(name) {
    const m = models.find((x) => x.name === name);
    const data = await loadJSON("data/samples/" + encodeURIComponent(name) + ".json");
    const samples = data.samples;

    const t = tendencyOf(m.stats);
    const avgTokens = avg(samples.map((s) => s.usage && s.usage.total_tokens));
    const avgCost = avg(samples.map((s) => s.usage && s.usage.cost));
    const avgDur = avg(samples.map((s) => s.duration_seconds));

    const targetStats = m.per_target
      .map(
        (pt) =>
          `<div class="stat"><div class="num">${pct(pt.positive_probability)}</div>` +
          `<div class="label">对象是"${pt.text}"时 P(给)</div></div>`
      )
      .join("");

    const a = m.analysis || {};
    const analysisHtml =
      analysisBlock("回复风格", a.style, [
        ["summary", "总体"],
        ["directness", "直接程度"],
        ["instruction_following", "指令遵循"],
        ["tone", "语气"],
        ["consistency", "一致性"],
        ["patterns", "典型模式"],
      ]) +
      analysisBlock("决策内容", a.content, [
        ["decision_tendency", "决策倾向"],
        ["target_differences", "对象差异"],
        ["rationale_patterns", "理由模式"],
        ["risk_attitude", "风险态度"],
        ["answer_quality", "回答质量"],
      ]) +
      analysisBlock("可见思考过程", a.reasoning, [
        ["availability", "可见性"],
        ["summary", "概述"],
        ["depth_and_structure", "深度与结构"],
        ["recurring_factors", "反复出现的因素"],
        ["strengths", "优点"],
        ["limitations", "不足"],
        ["answer_alignment", "思考与回答的一致性"],
      ]);

    const samplesHtml = samples
      .map((s) => {
        const opt = s.normalized_option || "error";
        const optLabel = { give: "给", not_give: "不给", unclear: "含糊" }[opt] || "失败";
        const reasoning = s.reasoning_content
          ? `<details class="reasoning"><summary>可见思考过程</summary><div class="body">${esc(
              s.reasoning_content
            )}</div></details>`
          : `<div class="meta">（无可见思考过程）</div>`;
        return `
        <div class="sample">
          <div class="prompt">${esc(s.prompt)}</div>
          <div class="answer">${esc(s.content ?? "（无输出）")}</div>
          <span class="badge ${esc(opt)}">${optLabel}</span>
          <span class="meta">Judge：${esc(s.judge_reason ?? "—")}</span>
          <div class="meta">tokens ${s.usage?.total_tokens ?? "?"} · 花费 $${(s.usage?.cost ?? 0).toFixed(4)} · 耗时 ${(s.duration_seconds ?? 0).toFixed(1)}s · 第 ${s.repeat_index} 次</div>
          ${reasoning}
        </div>`;
      })
      .join("");

    document.getElementById("content").innerHTML = `
      <div class="panel">
        <div class="head" style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
          <h2 style="border:none;padding:0;margin:0">${esc(m.name)}</h2>
          <span class="vendor-tag">${esc(m.vendor)} · ${esc(m.id || "")}</span>
        </div>
        <div class="stat-row">
          <div class="stat"><div class="num ${t.cls}">${pct(m.stats.positive_probability)}</div><div class="label">P(给) · ${t.label}</div></div>
          ${targetStats}
          <div class="stat"><div class="num">${m.stats.valid_count}/${m.stats.planned_count}</div><div class="label">有效判定</div></div>
          <div class="stat"><div class="num">${avgTokens ? Math.round(avgTokens) : "?"}</div><div class="label">平均 tokens</div></div>
          <div class="stat"><div class="num">$${avgCost ? avgCost.toFixed(4) : "?"}</div><div class="label">平均单次花费</div></div>
          <div class="stat"><div class="num">${avgDur ? avgDur.toFixed(1) + "s" : "?"}</div><div class="label">平均耗时</div></div>
        </div>
      </div>
      ${analysisHtml ? `<div class="panel">${analysisHtml}<p class="note">以上特点由分析模型 deepseek-v4-flash 基于本模型的全部回答与可见思考过程归纳生成。</p></div>` : ""}
      <h2>全部回答（${samples.length} 条）</h2>
      ${samplesHtml}
    `;
  }

  await render(current);
})().catch((e) => {
  document.getElementById("content").innerHTML =
    `<div class="panel">数据加载失败：${e.message}。请确认通过 HTTP 服务访问，而不是直接打开文件。</div>`;
});
