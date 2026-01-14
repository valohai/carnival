"""Tests for configuration parsing and validation."""

import pytest

from carnival.config import CarnivalConfig, RestartPolicy

complex_config_content = """
[[init]]
command = "mkdir"
args = ["-p", "/data"]

[[init]]
command = "echo"
args = ["Initialized"]

[[service]]
name = "webserver"
command = "python"
args = ["-m", "http.server", "${PORT}"]
replicas = "${NUM_WORKERS:-2}"
restart = "always"
restart-delay-ms = 1500

[[service]]
name = "worker"
command = "python"
args = ["worker.py"]
replicas = 1
restart = "on-failure"
restart_limit = 3
working-dir = "/app"
"""


def test_complex_config(tmp_path, snapshot, monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.delenv("NUM_WORKERS", raising=False)

    config_path = tmp_path / "complex.toml"
    config_path.write_text(complex_config_content)
    config = CarnivalConfig.from_file(config_path)
    assert snapshot(name="init") == config.init_commands
    assert snapshot(name="srv") == config.services

    webserver = config.services[0]
    assert webserver.name == "webserver"
    assert "8080" in webserver.args  # From envvar
    assert webserver.replicas == 2  # From default
    assert webserver.restart == RestartPolicy.ALWAYS

    # Check worker service
    worker = config.services[1]
    assert worker.name == "worker"
    assert worker.restart == RestartPolicy.ON_FAILURE
    assert worker.restart_limit == 3
    assert worker.working_dir == "/app"


def test_extra_init_fields_fail(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("""
[[init]]
command = "mkdir"
args = ["-p", "/data"]
extraneous = "should cause failure"
    """)
    with pytest.raises(ValueError):
        CarnivalConfig.from_file(config_path)


def test_extra_service_fields_fail(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("""
[[service]]
name = "worker"
command = "python"
extraneous = "should cause failure"
    """)
    with pytest.raises(ValueError):
        CarnivalConfig.from_file(config_path)
