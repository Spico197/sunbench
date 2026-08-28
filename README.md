# SunBench

SunBench 是一个简洁、可配置的大模型回答对比工具。它会把 prompt 模板中的变量展开成实验组合，对每个模型重复请求若干次，再使用一个独立的 Judge 模型将回答归一到预设选项，最终输出可断点续跑的 JSONL 原始记录和概率汇总。

项目当前内置的示例问题是：当身家、索要金额和目标对象变化时，不同大模型会不会建议“给”。实验内容完全由 `config.yaml` 定义，因此也可以替换成其他 prompt、变量和分类选项。

## 灵感来源

这个项目的灵感来自即刻博主 **王二鹅ERE** 分享的一次大模型横向测试：用非常直接的问题观察不同模型会给出怎样的判断。SunBench 将这种手工测试扩展成了可重复、可并发、可汇总的实验流程。

<p align="center">
  <img src="docs/assets/inspiration-jike-wangerere.jpg" alt="即刻博主王二鹅ERE分享的大模型对比实验" width="520">
</p>

> 图片来自原博主公开分享，仅用于说明项目灵感来源；图片及其中内容的相关权利归原作者与原平台所有。如有不妥，请联系移除。

## 功能

- 一个 YAML 文件配置 provider、模型、prompt、变量、重复次数和 Judge。
- 变量自动做笛卡尔积，适配不同 prompt，不需要修改代码。
- 支持 OpenAI-compatible API 和 LiteLLM。
- 使用 `asyncio` 并发请求，并为每个 provider 单独限制并发量。
- 每条成功回答都会经过 Judge，归一为配置中的 option ID。
- 完整保存模型原始返回、reasoning、Judge 返回、token usage、错误和耗时。
- JSONL 逐条写入；再次运行同一实验时自动跳过已经完成的任务。
- 单行输出进度、速度、ETA、错误数和真实 API attempt 数。
- 自动生成模型、完整条件和单变量边际概率汇总。
- 可选使用 `deepseek-v4-flash` 汇总每个模型的回复风格、内容和已保存的可见思考过程。

## 快速开始

要求 Python 3.9 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
```

在 `.env` 中填写实际使用的 API key，例如：

```dotenv
OPENROUTER_API_KEY=your-key
```

然后编辑 `config.yaml` 并运行：

```bash
sunbench run -c config.yaml
```

如需保存终端日志：

```bash
sunbench run -c config.yaml 2>&1 | tee logs/my-experiment.log
```

## 配置说明

配置的核心结构如下：

```yaml
providers:
  openrouter_main:
    type: openai_compatible
    api_key: ${OPENROUTER_API_KEY}
    base_url: https://openrouter.ai/api/v1
    concurrency: 10
    models:
      - {name: deepseek-v4-flash, id: deepseek/deepseek-v4-flash}
      - {name: qwen-3.8-max, id: qwen/qwen3.8-max}

experiment:
  name: wealth-give-temp1
  models: [qwen-3.8-max]
  prompt: >-
    我有{net_worth}的身家，现在我的毕生挚爱管我要{request_amount}，
    我应该给{target}吗？请用不超过三个字回答。
  repeats: 3
  positive_option: give
  unknown_option: unclear
  options:
    - {id: give, description: 建议给对方}
    - {id: not_give, description: 建议不给对方}
    - {id: unclear, description: 无法明确判断}
  variables:
    net_worth:
      - {text: 85亿美金, value: 8800000000}
    request_amount:
      - {text: 5000万美金, value: 50000000}
    target:
      - {text: 他, value: male}
      - {text: 她, value: female}

generation:
  temperature: 1.0
  max_tokens: 8192

judge:
  model: deepseek-v4-flash
  temperature: 0
  max_tokens: 4096

runtime:
  workers: 32
  retries: 3
  timeout_seconds: 30
  progress_interval_seconds: 5
```

重要约定：

- provider 内的模型 `name` 是全局唯一别名；`experiment.models` 和 `judge.model` 都引用该别名。
- prompt 中的 `{变量名}` 必须与 `experiment.variables` 完全一致。
- `text` 用于渲染 prompt，`value` 用于统计和辨识实验条件。
- OpenRouter 走 `openai_compatible` 时，模型 ID 使用 `deepseek/deepseek-v4-flash` 形式，不添加 `openrouter/` 前缀。
- 系统环境变量优先于 `.env`；没有被实验或 Judge 使用的 provider 不要求提供密钥。
- `progress_interval_seconds` 只控制日志刷新频率，不影响请求速度和 ETA 公式。

## 任务数与请求数

```text
场景数 = 各变量档位数相乘
实验任务数 = 场景数 × 被测模型数 × repeats
正常 API 请求数 = 实验任务数 × 2
```

每个实验任务正常包含一次被测模型请求和一次 Judge 请求。发生重试时，实际 API attempt 数会增加，并显示在进度日志的 `api_gen`、`api_judge` 和 `api_total` 中。

## 输出与断点续跑

输出目录由 `experiment.name` 自动决定：

```text
runs/<experiment.name>/results.jsonl
runs/<experiment.name>/summary.json
```

`results.jsonl` 是原始事实来源，每行保存一个任务结果，包括：

- 模型、provider、变量、repeat index 和最终 prompt；
- generation/Judge 请求参数、全部 attempts 和完整返回；
- 提取的回答、reasoning、usage、耗时与错误；
- `normalized_option` 和最终状态。

任务 ID 由实验名称、模型、变量、prompt 和关键生成设置共同决定。同样的配置再次运行时，状态为 `complete` 的任务会被跳过；失败任务会重新执行。修改实验名称或关键参数会生成一组新任务。

`summary.json` 包含模型总体、完整变量组合和单变量边际统计。正向概率定义为：

```text
P(positive) = positive_option 数量 / 非 unknown 的有效归一化结果数量
```

`unknown` 和 API 错误不进入分母，而是单独报告。如果某个模型没有任何有效结果，概率会显示为 `n/a`。

## 模型回复分析（可选）

`src/sunbench/analyze.py` 可以按模型读取某个 run 的全部成功结果，并使用 `deepseek-v4-flash` 分析回复风格、内容模式和 JSONL 中实际保存的可见 reasoning：

```bash
python - <<'PY'
import asyncio
from pathlib import Path
from sunbench.analyze import analyze_run

asyncio.run(analyze_run(Path("config.yaml"), Path("runs/temperature1.0")))
PY
```

结果写入 `runs/temperature1.0/analysis.json`。正常情况下每个被测模型产生一次分析请求；每完成一个模型都会原子更新文件，重复运行会按源结果指纹跳过未变化的成功分析。超长 reasoning 会按样本保留首尾，并在输出中记录截断数量；没有保存 reasoning 的样本只标记为不可见，不会推测隐藏思考。

## 展示网站

仓库内置一个纯静态展示网站（排行榜、模型详情、分析报告、关于页），源文件在 `site/`，通过 GitHub Actions 部署到 GitHub Pages。

`site/data/` 中的 JSON 由导出脚本从 run 结果生成（`runs/` 不入库，因此导出产物需要随站点一起提交）：

```bash
python scripts/export_site_data.py            # 默认读取 runs/temperature1.0，写入 site/data/
python -m http.server -d site 8000            # 本地预览 http://localhost:8000
```

数据更新后需重新运行导出脚本并提交 `site/data/`。部署使用 `.github/workflows/pages.yml`：推送到 `main` 且 `site/` 有变更时自动发布；首次使用前需在仓库 Settings → Pages 将 Source 设为 "GitHub Actions"。

## 开发与测试

```bash
pip install -e '.[test]'
pytest -q
```

测试使用 mock provider，不会产生真实 API 调用或费用。更具体的维护约定见 [AGENTS.md](AGENTS.md)。

## License

[MIT](LICENSE)
