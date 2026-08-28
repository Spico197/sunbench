#!/usr/bin/env python3
"""Export run data to static JSON files for the SunBench website.

Reads runs/<experiment>/{summary.json, results.jsonl, analysis.json} and
writes compact, committed JSON files into site/data/. Stdlib only.

Usage:
    python scripts/export_site_data.py [--run runs/temperature1.0] [--out site/data]
"""

import argparse
import json
import sys
from pathlib import Path

VENDORS = {
    "deepseek": "DeepSeek",
    "qwen": "通义千问",
    "moonshotai": "Kimi",
    "z-ai": "智谱 GLM",
    "x-ai": "Grok",
    "google": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Claude",
    "bytedance-seed": "字节 Seed",
    "xiaomi": "MiMo",
    "minimax": "MiniMax",
    "stepfun": "阶跃 Step",
    "meituan": "LongCat",
    "tencent": "混元",
    "dots-studio": "dots",
    "inclusionai": "Ling",
    "meta": "Muse Spark",
}

TARGET_ORDER = ["male", "female", "non_human"]
TARGET_LABELS = {"male": "他", "female": "她", "non_human": "它"}


def vendor_of(model_id):
    prefix = (model_id or "").split("/", 1)[0]
    return VENDORS.get(prefix, prefix or "未知")


def dump(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print("wrote", path)


def export_summary(summary, out_dir):
    keep = {
        k: summary[k]
        for k in (
            "schema_version",
            "experiment",
            "generated_at",
            "positive_option",
            "unknown_option",
            "overall",
            "models",
            "cells",
            "marginals",
            "sources",
        )
        if k in summary
    }
    dump(keep, out_dir / "summary.json")


def export_models(summary, analysis, model_ids, out_dir):
    per_target = {}
    for entry in summary.get("marginals", {}).get("target", []):
        var = entry["variable"]
        per_target.setdefault(entry["model"], {})[var["value"]] = {
            "text": var["text"],
            "positive_probability": entry["positive_probability"],
            "valid_count": entry["valid_count"],
            "option_counts": entry["option_counts"],
        }

    analysis_by_model = {}
    if analysis:
        for entry in analysis.get("models", []):
            if entry.get("status") != "complete":
                continue
            analysis_by_model[entry["model"]] = entry.get("analysis")

    models = []
    for m in summary.get("models", []):
        targets = per_target.get(m["model"], {})
        models.append(
            {
                "name": m["model"],
                "vendor": vendor_of(model_ids.get(m["model"])),
                "id": model_ids.get(m["model"]),
                "stats": m,
                "per_target": [
                    {
                        "value": v,
                        "text": TARGET_LABELS.get(v, v),
                        "positive_probability": t.get("positive_probability"),
                        "valid_count": t.get("valid_count", 0),
                        "option_counts": t.get("option_counts", {}),
                    }
                    for v in TARGET_ORDER
                    for t in (targets.get(v),)
                    if t is not None
                ],
                "analysis": analysis_by_model.get(m["model"]),
            }
        )
    dump({"models": models}, out_dir / "models.json")


def export_samples(results_path, out_dir):
    by_model = {}
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            gen_resp = (r.get("generation") or {}).get("response") or {}
            usage = gen_resp.get("usage") or {}
            judge = r.get("judge") or {}
            sample = {
                "repeat_index": r.get("repeat_index"),
                "target": (r.get("variables") or {}).get("target"),
                "prompt": r.get("prompt"),
                "content": gen_resp.get("content"),
                "reasoning_content": gen_resp.get("reasoning_content"),
                "usage": {
                    k: usage.get(k)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
                },
                "duration_seconds": r.get("duration_seconds"),
                "normalized_option": r.get("normalized_option"),
                "judge_reason": (judge.get("parsed") or {}).get("reason"),
                "status": r.get("status"),
            }
            by_model.setdefault(r["model"]["name"], []).append(sample)

    samples_dir = out_dir / "samples"
    for name in sorted(by_model):
        samples = sorted(
            by_model[name],
            key=lambda s: (
                TARGET_ORDER.index((s["target"] or {}).get("value", "male"))
                if (s["target"] or {}).get("value") in TARGET_ORDER
                else 99,
                s["repeat_index"] if s["repeat_index"] is not None else 99,
            ),
        )
        dump({"model": name, "samples": samples}, samples_dir / (name + ".json"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="runs/temperature1.0", help="run directory")
    parser.add_argument("--out", default="site/data", help="output data directory")
    args = parser.parse_args(argv)

    run_dir = Path(args.run)
    out_dir = Path(args.out)
    summary_path = run_dir / "summary.json"
    results_path = run_dir / "results.jsonl"
    analysis_path = run_dir / "analysis.json"

    if not summary_path.exists() or not results_path.exists():
        print("error: %s must contain summary.json and results.jsonl" % run_dir, file=sys.stderr)
        return 1

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    analysis = (
        json.loads(analysis_path.read_text(encoding="utf-8"))
        if analysis_path.exists()
        else None
    )

    model_ids = {}
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                model_ids.setdefault(r["model"]["name"], r["model"].get("id"))

    export_summary(summary, out_dir)
    export_models(summary, analysis, model_ids, out_dir)
    export_samples(results_path, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
