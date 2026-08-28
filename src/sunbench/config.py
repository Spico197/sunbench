import copy
import os
import re
import string
from pathlib import Path
from typing import Any, Dict, Mapping, Set

import yaml
from dotenv import load_dotenv


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
PROVIDER_TYPES = {"litellm", "openai_compatible"}


class ConfigError(ValueError):
    """Raised when a configuration is incomplete or inconsistent."""


def _validate_experiment_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("experiment.name is required")
    name = value.strip()
    if name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise ConfigError("experiment.name must be a safe directory name")
    return name


def _require_mapping(data: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping")
    return value


def _expand_string(value: str) -> str:
    missing = []

    def replace(match: re.Match) -> str:
        name = match.group(1)
        resolved = os.environ.get(name)
        if resolved is None or resolved == "":
            missing.append(name)
            return match.group(0)
        return resolved

    expanded = ENV_PATTERN.sub(replace, value)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise ConfigError(f"Missing environment variable(s): {names}")
    return expanded


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_string(value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def build_model_index(config: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    providers = _require_mapping(config, "providers")
    for provider_name, provider in providers.items():
        if not isinstance(provider, dict):
            raise ConfigError(f"Provider '{provider_name}' must be a mapping")
        models = provider.get("models", [])
        if not isinstance(models, list):
            raise ConfigError(f"Provider '{provider_name}'.models must be a list")
        for model in models:
            if not isinstance(model, dict) or not model.get("name") or not model.get("id"):
                raise ConfigError(
                    f"Every model in provider '{provider_name}' needs name and id"
                )
            alias = str(model["name"])
            if alias in index:
                other = index[alias]["provider_name"]
                raise ConfigError(
                    f"Model alias '{alias}' is duplicated in '{other}' and '{provider_name}'"
                )
            index[alias] = {
                "name": alias,
                "id": str(model["id"]),
                "provider_name": provider_name,
                "provider": provider,
            }
    return index


def _used_model_aliases(config: Mapping[str, Any]) -> Set[str]:
    experiment = _require_mapping(config, "experiment")
    judge = _require_mapping(config, "judge")
    models = experiment.get("models")
    if not isinstance(models, list) or not models:
        raise ConfigError("experiment.models must be a non-empty list")
    judge_model = judge.get("model")
    if not isinstance(judge_model, str) or not judge_model:
        raise ConfigError("judge.model is required")
    return {str(alias) for alias in models} | {judge_model}


def _validate(config: Dict[str, Any]) -> None:
    providers = _require_mapping(config, "providers")
    experiment = _require_mapping(config, "experiment")
    generation = _require_mapping(config, "generation")
    judge = _require_mapping(config, "judge")
    runtime = _require_mapping(config, "runtime")
    output = _require_mapping(config, "output")
    _validate_experiment_name(experiment.get("name"))

    index = build_model_index(config)
    used_aliases = _used_model_aliases(config)
    missing_aliases = sorted(used_aliases - set(index))
    if missing_aliases:
        raise ConfigError(f"Unknown model alias(es): {', '.join(missing_aliases)}")

    used_providers = {index[alias]["provider_name"] for alias in used_aliases}
    for provider_name, provider in providers.items():
        provider_type = provider.get("type")
        if provider_type not in PROVIDER_TYPES:
            raise ConfigError(
                f"Provider '{provider_name}' has unsupported type '{provider_type}'"
            )
        concurrency = provider.get("concurrency", 1)
        if not isinstance(concurrency, int) or concurrency < 1:
            raise ConfigError(f"Provider '{provider_name}'.concurrency must be >= 1")
        if provider_name in used_providers:
            if not provider.get("api_key"):
                raise ConfigError(f"Provider '{provider_name}'.api_key is required")
            if not provider.get("base_url"):
                raise ConfigError(f"Provider '{provider_name}'.base_url is required")

    prompt = experiment.get("prompt")
    variables = experiment.get("variables")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ConfigError("experiment.prompt is required")
    if not isinstance(variables, dict) or not variables:
        raise ConfigError("experiment.variables must be a non-empty mapping")

    placeholders = {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(prompt)
        if field_name
    }
    if placeholders != set(variables):
        missing_variables = sorted(placeholders - set(variables))
        unused_variables = sorted(set(variables) - placeholders)
        details = []
        if missing_variables:
            details.append(f"missing variables: {', '.join(missing_variables)}")
        if unused_variables:
            details.append(f"unused variables: {', '.join(unused_variables)}")
        raise ConfigError("Prompt/variables mismatch (" + "; ".join(details) + ")")

    for variable_name, values in variables.items():
        if not isinstance(values, list) or not values:
            raise ConfigError(f"Variable '{variable_name}' must be a non-empty list")
        for item in values:
            if not isinstance(item, dict) or "text" not in item or "value" not in item:
                raise ConfigError(
                    f"Every value of '{variable_name}' needs text and value"
                )

    repeats = experiment.get("repeats")
    if not isinstance(repeats, int) or repeats < 1:
        raise ConfigError("experiment.repeats must be >= 1")

    options = experiment.get("options")
    if not isinstance(options, list) or not options:
        raise ConfigError("experiment.options must be a non-empty list")
    option_ids = []
    for option in options:
        if not isinstance(option, dict) or not option.get("id") or not option.get("description"):
            raise ConfigError("Every experiment option needs id and description")
        option_ids.append(str(option["id"]))
    if len(option_ids) != len(set(option_ids)):
        raise ConfigError("experiment option ids must be unique")
    for field in ("positive_option", "unknown_option"):
        if experiment.get(field) not in option_ids:
            raise ConfigError(f"experiment.{field} must match an option id")

    for section_name, section in (("generation", generation), ("judge", judge)):
        max_tokens = section.get("max_tokens")
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ConfigError(f"{section_name}.max_tokens must be >= 1")

    for key in ("workers", "retries", "timeout_seconds"):
        value = runtime.get(key)
        minimum = 1
        if not isinstance(value, int) or value < minimum:
            raise ConfigError(f"runtime.{key} must be >= {minimum}")
    progress_interval = runtime.get("progress_interval_seconds", 10)
    if not isinstance(progress_interval, (int, float)) or progress_interval <= 0:
        raise ConfigError("runtime.progress_interval_seconds must be > 0")

    for key in ("jsonl", "summary"):
        if not isinstance(output.get(key), str) or not output[key]:
            raise ConfigError(f"output.{key} is required")


def load_config(path: Path) -> Dict[str, Any]:
    config_path = path.expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    load_dotenv(config_path.parent / ".env", override=False)
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ConfigError("Config root must be a mapping")

    raw = copy.deepcopy(loaded)
    raw_index = build_model_index(raw)
    used_aliases = _used_model_aliases(raw)
    missing_aliases = sorted(used_aliases - set(raw_index))
    if missing_aliases:
        raise ConfigError(f"Unknown model alias(es): {', '.join(missing_aliases)}")
    used_providers = {raw_index[alias]["provider_name"] for alias in used_aliases}

    expanded = copy.deepcopy(raw)
    for key, value in list(expanded.items()):
        if key != "providers":
            expanded[key] = _expand_env(value)
    for provider_name, provider in list(expanded["providers"].items()):
        if provider_name in used_providers:
            expanded["providers"][provider_name] = _expand_env(provider)

    experiment = _require_mapping(expanded, "experiment")
    experiment_name = _validate_experiment_name(experiment.get("name"))
    experiment["name"] = experiment_name
    raw_output = expanded.get("output", {})
    if not isinstance(raw_output, dict):
        raise ConfigError("'output' must be a mapping when provided")
    output = dict(raw_output)
    default_directory = Path("runs") / experiment_name
    output.setdefault("jsonl", str(default_directory / "results.jsonl"))
    output.setdefault("summary", str(default_directory / "summary.json"))
    for key in ("jsonl", "summary"):
        output_path = Path(str(output[key])).expanduser()
        if not output_path.is_absolute():
            output_path = config_path.parent / output_path
        output[key] = str(output_path.resolve())
    expanded["output"] = output

    expanded["_config_path"] = str(config_path)
    _validate(expanded)
    return expanded
