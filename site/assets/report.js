/* Report page charts — all figures computed from exported data. */
(async function () {
  const [summary, modelsData] = await Promise.all([
    loadJSON("data/summary.json"),
    loadJSON("data/models.json"),
  ]);
  const models = modelsData.models;
  const colors = vendorColors(models);

  // 1. Aggregate P(give) by target
  const agg = {};
  for (const e of summary.marginals.target) {
    const v = e.variable.value;
    const a = (agg[v] = agg[v] || { text: e.variable.text, give: 0, not_give: 0, unclear: 0 });
    for (const k of ["give", "not_give", "unclear"]) a[k] += e.option_counts[k] || 0;
  }
  const order = ["male", "female", "non_human"];
  const overallChart = echarts.init(document.getElementById("target-overall"));
  overallChart.setOption({
    grid: { left: 20, right: 40, top: 30, bottom: 30, containLabel: true },
    xAxis: { type: "category", data: order.map((v) => agg[v].text), axisLabel: { fontSize: 15 } },
    yAxis: { type: "value", max: 1, axisLabel: { formatter: (v) => v * 100 + "%" } },
    tooltip: {
      formatter: (p) => {
        const a = agg[order[p.dataIndex]];
        return `对象是"${a.text}"<br/>P(给) = ${pct(a.give / (a.give + a.not_give))}<br/>` +
          `给 ${a.give} · 不给 ${a.not_give} · 含糊 ${a.unclear}`;
      },
    },
    series: [{
      type: "bar",
      barWidth: 64,
      data: order.map((v) => {
        const a = agg[v];
        return { value: a.give / (a.give + a.not_give), itemStyle: { color: "#c2570b", borderRadius: [4, 4, 0, 0] } };
      }),
      label: { show: true, position: "top", formatter: (p) => pct(p.value), fontSize: 13 },
    }],
  });

  // 2. Per-model per-target heatmap (sorted by overall P(give))
  const sorted = [...models].sort(
    (a, b) => (b.stats.positive_probability ?? -1) - (a.stats.positive_probability ?? -1)
  );
  const heatData = [];
  sorted.forEach((m, y) => {
    order.forEach((v, x) => {
      const pt = m.per_target.find((t) => t.value === v);
      heatData.push([x, y, pt && pt.positive_probability !== null ? pt.positive_probability : -1]);
    });
  });
  const heatmap = echarts.init(document.getElementById("target-heatmap"));
  heatmap.setOption({
    grid: { left: 10, right: 20, top: 10, bottom: 60, containLabel: true },
    xAxis: { type: "category", data: order.map((v) => agg[v].text), splitArea: { show: true } },
    yAxis: { type: "category", inverse: true, data: sorted.map((m) => m.name), axisLabel: { fontSize: 11 }, splitArea: { show: true } },
    visualMap: {
      min: 0, max: 1, orient: "horizontal", left: "center", bottom: 0,
      inRange: { color: ["#cf222e", "#fff8c5", "#2da44e"] },
      formatter: (v) => Math.round(v * 100) + "%",
    },
    tooltip: {
      formatter: (p) => {
        const m = sorted[p.value[1]];
        const pt = m.per_target.find((t) => t.value === order[p.value[0]]);
        if (!pt || pt.positive_probability === null || pt.positive_probability === undefined)
          return `${m.name} · "${agg[order[p.value[0]]].text}"：无有效判定`;
        const c = pt.option_counts;
        return `${m.name} · 对象是"${pt.text}"<br/>P(给) = ${pct(pt.positive_probability)}<br/>` +
          `给 ${c.give || 0} · 不给 ${c.not_give || 0} · 含糊 ${c.unclear || 0}`;
      },
    },
    series: [{
      type: "heatmap",
      data: heatData,
      label: {
        show: true, fontSize: 11,
        formatter: (p) => (p.value[2] < 0 ? "n/a" : Math.round(p.value[2] * 100) + "%"),
      },
    }],
  });

  // 3. Stability: per-model count of fully consistent cells (3/3 decisive & unanimous)
  const consistency = {};
  for (const m of models) consistency[m.name] = 0;
  for (const c of summary.cells) {
    const oc = c.option_counts;
    const decisive = (oc.give || 0) + (oc.not_give || 0);
    if (decisive === 3 && ((oc.give || 0) === 3 || (oc.not_give || 0) === 3)) {
      consistency[c.model] = (consistency[c.model] || 0) + 1;
    }
  }
  const stabSorted = [...models].sort((a, b) => consistency[b.name] - consistency[a.name]);
  const stability = echarts.init(document.getElementById("stability"));
  stability.setOption({
    grid: { left: 10, right: 40, top: 10, bottom: 10, containLabel: true },
    xAxis: { type: "value", max: 3, minInterval: 1 },
    yAxis: { type: "category", inverse: true, data: stabSorted.map((m) => m.name), axisLabel: { fontSize: 11 } },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (ps) => {
        const m = stabSorted[ps[0].dataIndex];
        return `${m.name}：${consistency[m.name]}/3 组条件完全一致`;
      },
    },
    series: [{
      type: "bar", barWidth: 14,
      data: stabSorted.map((m) => ({
        value: consistency[m.name],
        itemStyle: { color: colors[m.vendor], borderRadius: [0, 4, 4, 0] },
      })),
      label: { show: true, position: "right", formatter: (p) => p.value + "/3", fontSize: 11, color: "#6a737d" },
    }],
  });

  window.addEventListener("resize", () => {
    overallChart.resize();
    heatmap.resize();
    stability.resize();
  });
})().catch((e) => {
  document.querySelector("main").insertAdjacentHTML(
    "afterbegin",
    `<div class="panel">图表数据加载失败：${e.message}</div>`
  );
});
