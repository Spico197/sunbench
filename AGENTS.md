# AGENTS.md

本文件适用于整个仓库，供后续 Codex、自动化 Agent 和开发者维护 SunBench 时使用。

## 项目目标

SunBench 应保持“小、直白、能用”：通过一个配置文件和一个 `sunbench run -c config.yaml` 命令完成实验展开、并发请求、Judge、JSONL 续跑和汇总。不要重新引入 planner、数据库、独立 analyze/report/resume 命令或不必要的抽象层。

## 代码结构

- `src/sunbench/cli.py`：唯一 CLI 入口。
- `src/sunbench/config.py`：`.env`、YAML、环境变量展开和配置校验。
- `src/sunbench/runner.py`：任务展开、稳定 task ID、并发执行、进度、续跑和 summary。
- `src/sunbench/judge.py`：Judge prompt 与 option 归一化。
- `src/sunbench/analyze.py`：可选的 run 级模型回复与可见 reasoning 汇总；保持为 Python API，不增加 `sunbench analyze` CLI。
- `src/sunbench/providers/`：每种 provider 一个薄文件，统一导出异步 `completion(...)`。
- `src/sunbench/utils/`：registry、retry、并发信号量和 JSONL 辅助函数。
- `tests/`：全部测试必须离线，不得调用真实模型。
- `site/`：纯静态展示网站（vanilla HTML/JS + ECharts CDN），由 GitHub Actions 部署到 Pages；不引入 Node 工具链。
- `scripts/export_site_data.py`：把 run 结果导出为 `site/data/` 下的 JSON；保持 stdlib-only。`runs/` 不入库，因此 `site/data/` 的导出产物需要提交。

## 必须保持的不变量

1. 只保留 `sunbench run -c <config>` 这一条用户命令。
2. `experiment.models` 与 `judge.model` 使用全局唯一模型别名。
3. prompt 占位符必须和 `experiment.variables` 一一对应。
4. provider API key 只来自环境变量或 `.env`；绝不能进入日志、JSONL、测试 fixture 或提交记录。
5. 默认输出固定为 `runs/<experiment.name>/results.jsonl` 和 `summary.json`。
6. JSONL 是 append-only 原始记录；状态为 `complete` 的当前 task ID 才能被续跑逻辑跳过。
7. generation 成功后才调用 Judge；Judge 只做分类，不重新回答原问题。
8. `normalized_option` 必须是配置中声明的 option ID；解析失败不能静默归为 `unknown`。
9. 每个 provider 使用独立 semaphore，总 worker 数由 `runtime.workers` 控制。
10. 进度日志保持单行，至少保留任务数、成功/错误、elapsed、speed、ETA 和 API attempts。

## Provider 约定

provider 模块接口为：

```python
async def completion(provider, model_id, messages, generation) -> dict:
    ...
```

返回值至少包含 `raw`、`content`、`reasoning_content`、`usage` 和 `model`。

- OpenAI-compatible 服务使用 `providers/openai_compatible.py`。
- 只有确实需要 LiteLLM 的服务才使用 `providers/litellm.py`。
- OpenRouter 通过 OpenAI-compatible 接口调用时，模型 ID 不带 `openrouter/` 前缀。
- 不添加隐式 provider fallback 或 priority；一个模型别名必须明确绑定一个 provider instance。
- 新增 provider 类型时，只增加一个薄 provider 文件和 registry 映射，不建立新的继承体系。

## 结果与兼容性

- task ID 包含实验名、模型路由、变量、prompt、generation/Judge 设置和 options。修改这些字段会产生新任务，这是预期行为。
- 修改 task ID 输入、JSONL schema、概率分母或续跑判断时，必须补回归测试并在 README 说明兼容性影响。
- 不要删除、覆盖或格式化用户已有的 `runs/`、`logs/` 和 `.env`；除非用户明确指定源、目标和覆盖规则。
- 合并实验结果时保留来源信息，并验证逻辑任务唯一、状态完整和 summary 与 JSONL 一致。
- `P(positive)` 的分母只包含成功归一化且不属于 `unknown_option` 的结果；错误和 unknown 单独统计。

## 开发流程

使用仓库虚拟环境执行：

```bash
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
```

提交改动前至少执行：

```bash
pytest -q
python -m compileall -q src tests
git diff --check
```

测试要求：

- provider 调用必须 mock，不能消耗真实额度。
- 配置变更应覆盖环境变量、别名引用和输出路径。
- runner 变更应覆盖任务数量、并发、重试、断点续跑、Judge 和 summary。
- JSONL 变更应覆盖并发写入、损坏尾行和重复运行。

## 风格与文档

- 支持 Python 3.9；不要使用更高版本独有语法。
- 优先标准库和小函数，避免为简单流程增加框架。
- 保持配置字段少而明确；新增配置必须有合理默认值和校验。
- 所有用户可见行为变化同步更新 README。
- README 面向使用者，使用中文并提供可复制命令；本文件面向维护者，记录约束和不变量。
