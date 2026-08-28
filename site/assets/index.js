/* Leaderboard page */
(async function () {
  const [summary, modelsData] = await Promise.all([
    loadJSON("data/summary.json"),
    loadJSON("data/models.json"),
  ]);
  const models = modelsData.models;
  const sorted = [...models].sort(
    (a, b) => (b.stats.positive_probability ?? -1) - (a.stats.positive_probability ?? -1)
  );

  // Overall stats
  const o = summary.overall;
  document.getElementById("overall-stats").innerHTML = [
    [models.length, "被测模型"],
    [o.completed_count, "完成任务"],
    [pct(o.positive_probability), "总体 P(给)"],
    [o.option_counts.give + " / " + o.option_counts.not_give + " / " + o.option_counts.unclear, "给 / 不给 / 含糊"],
  ]
    .map(
      ([num, label]) =>
        `<div class="stat"><div class="num">${num}</div><div class="label">${label}</div></div>`
    )
    .join("");

  // Leaderboard bar chart
  const lb = echarts.init(document.getElementById("leaderboard"));
  lb.setOption({
    grid: { left: 10, right: 60, top: 10, bottom: 10, containLabel: true },
    xAxis: { type: "value", max: 1, axisLabel: { formatter: (v) => v * 100 + "%" } },
    // 按 P(给) 取色：0 → 浅，1 → 深
    visualMap: { show: false, type: "continuous", min: 0, max: 1, dimension: 0, inRange: { color: SEQ_RAMP } },
    yAxis: {
      type: "category",
      inverse: true,
      data: sorted.map((m) => m.name),
      axisLabel: { fontSize: 12 },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const m = sorted[params[0].dataIndex];
        const c = m.stats.option_counts;
        return `${m.name}（${m.vendor}）<br/>P(给) = ${pct(m.stats.positive_probability)}<br/>` +
          `给 ${c.give || 0} · 不给 ${c.not_give || 0} · 含糊 ${c.unclear || 0}<br/>` +
          `有效 ${m.stats.valid_count}/${m.stats.planned_count}`;
      },
    },
    series: [
      {
        type: "bar",
        data: sorted.map((m) => m.stats.positive_probability),
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        barWidth: 16,
        label: {
          show: true,
          position: "right",
          formatter: (p) => pct(p.value, 0),
          fontSize: 11,
          color: "#6a737d",
        },
      },
    ],
  });

  // Option distribution stacked bar
  const dist = echarts.init(document.getElementById("distribution"));
  dist.setOption({
    grid: { left: 10, right: 20, top: 40, bottom: 10, containLabel: true },
    legend: { top: 0 },
    xAxis: { type: "value", max: 9 },
    yAxis: { type: "category", inverse: true, data: sorted.map((m) => m.name), axisLabel: { fontSize: 12 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    series: [
      { name: "给", type: "bar", stack: "x", barWidth: 16, itemStyle: { color: "#2da44e" },
        data: sorted.map((m) => m.stats.option_counts.give || 0) },
      { name: "不给", type: "bar", stack: "x", itemStyle: { color: "#cf222e" },
        data: sorted.map((m) => m.stats.option_counts.not_give || 0) },
      { name: "含糊", type: "bar", stack: "x", itemStyle: { color: "#d4a72c" },
        data: sorted.map((m) => m.stats.option_counts.unclear || 0) },
    ],
  });

  // Model cards
  document.getElementById("model-cards").innerHTML = sorted
    .map((m) => {
      const t = tendencyOf(m.stats);
      const summaryText = m.analysis && m.analysis.style ? m.analysis.style.summary : "";
      return `
      <a class="card" href="model.html?m=${encodeURIComponent(m.name)}">
        <div class="head"><span class="name">${m.name}</span><span class="vendor-tag">${m.vendor}</span></div>
        <div class="prob ${t.cls}">${pct(m.stats.positive_probability)}</div>
        <div class="tendency ${t.cls}">${t.label}</div>
        <div class="summary">${summaryText}</div>
      </a>`;
    })
    .join("");

  window.addEventListener("resize", () => {
    lb.resize();
    dist.resize();
  });
})().catch((e) => {
  document.querySelector("main").insertAdjacentHTML(
    "afterbegin",
    `<div class="panel">数据加载失败：${e.message}。请确认通过 HTTP 服务访问（如 python -m http.server），而不是直接打开文件。</div>`
  );
});
