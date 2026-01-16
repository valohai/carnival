"""Tests for configuration parsing and validation."""

import pytest

from carnival.config import CarnivalConfig, RestartPolicy

complex_config_content = """
[global]
shutdown-timeout-ms = 5000

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

    assert snapshot(name="global") == config.global_config
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


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            '[[init]]\ncommand = "mkdir"\nextraneous = "fail"',
            id="init",
        ),
        pytest.param(
            '[[service]]\nname = "x"\ncommand = "y"\nextraneous = "fail"',
            id="service",
        ),
        pytest.param(
            '[global]\nextraneous = "fail"',
            id="global",
        ),
    ],
)
def test_extra_fields_fail(tmp_path, case):
    """Test that unknown fields in config sections raise an error."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(case)
    with pytest.raises(ValueError, match="Unknown fields"):
        CarnivalConfig.from_file(config_path)
