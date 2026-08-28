from pathlib import Path

import pytest
import yaml

from sunbench.config import ConfigError, load_config


def write_config(path: Path, config) -> None:
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")


def test_loads_dotenv_without_overriding_system_environment(
    tmp_path, monkeypatch, copy_config
):
    copy_config["providers"]["test_provider"]["api_key"] = "${SUNBENCH_TEST_KEY}"
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)
    (tmp_path / ".env").write_text("SUNBENCH_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SUNBENCH_TEST_KEY", "from-system")

    loaded = load_config(config_path)

    assert loaded["providers"]["test_provider"]["api_key"] == "from-system"
    assert loaded["output"]["jsonl"] == str((tmp_path / "results.jsonl").resolve())


def test_missing_environment_variable_fails_before_run(tmp_path, monkeypatch, copy_config):
    variable = "SUNBENCH_DEFINITELY_MISSING"
    monkeypatch.delenv(variable, raising=False)
    copy_config["providers"]["test_provider"]["api_key"] = "${%s}" % variable
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    with pytest.raises(ConfigError, match=variable):
        load_config(config_path)


def test_unused_provider_does_not_require_its_environment(tmp_path, monkeypatch, copy_config):
    variable = "SUNBENCH_UNUSED_KEY"
    monkeypatch.delenv(variable, raising=False)
    copy_config["providers"]["unused"] = {
        "type": "openai_compatible",
        "api_key": "${%s}" % variable,
        "base_url": "https://unused.test/v1",
        "concurrency": 1,
        "models": [{"name": "unused-model", "id": "unused"}],
    }
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    loaded = load_config(config_path)

    assert loaded["providers"]["unused"]["api_key"] == "${%s}" % variable


def test_duplicate_model_alias_is_rejected(tmp_path, copy_config):
    copy_config["providers"]["other"] = {
        "type": "litellm",
        "api_key": "key",
        "base_url": "https://other.test/v1",
        "concurrency": 1,
        "models": [{"name": "test-model", "id": "other/model"}],
    }
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    with pytest.raises(ConfigError, match="duplicated"):
        load_config(config_path)


def test_prompt_and_variables_must_match(tmp_path, copy_config):
    copy_config["experiment"]["variables"]["unused"] = [
        {"text": "x", "value": "x"}
    ]
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    with pytest.raises(ConfigError, match="unused variables"):
        load_config(config_path)


def test_progress_interval_must_be_positive(tmp_path, copy_config):
    copy_config["runtime"]["progress_interval_seconds"] = 0
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    with pytest.raises(ConfigError, match="progress_interval_seconds"):
        load_config(config_path)


def test_output_paths_default_to_experiment_name(tmp_path, copy_config):
    del copy_config["output"]
    copy_config["experiment"]["name"] = "my-experiment"
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    loaded = load_config(config_path)

    assert loaded["output"] == {
        "jsonl": str((tmp_path / "runs/my-experiment/results.jsonl").resolve()),
        "summary": str((tmp_path / "runs/my-experiment/summary.json").resolve()),
    }


def test_experiment_name_cannot_escape_runs_directory(tmp_path, copy_config):
    del copy_config["output"]
    copy_config["experiment"]["name"] = "../outside"
    config_path = tmp_path / "config.yaml"
    write_config(config_path, copy_config)

    with pytest.raises(ConfigError, match="safe directory name"):
        load_config(config_path)
