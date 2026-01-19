import asyncio
import shlex
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from carnival.config import RestartPolicy, ServiceConfig
from carnival.process import ProcessReplica


@pytest.fixture
def shutdown_event():
    """Create a shutdown event."""
    return asyncio.Event()


@pytest.fixture
def basic_service_config():
    """Create a basic service config."""
    return ServiceConfig(
        name="test-service",
        command="echo",
        args=["hello"],
        replicas=1,
        restart=RestartPolicy.NO,
    )


@pytest.fixture
def restart_on_failure_config():
    """Create a service config with restart=on-failure."""
    return ServiceConfig(
        name="failing-service",
        command="false",
        restart=RestartPolicy.ON_FAILURE,
        restart_delay_ms=100,
        restart_limit=5,
    )


@pytest.mark.asyncio
async def test_should_restart_no_policy(basic_service_config, shutdown_event):
    """Test that restart=no never restarts."""
    replica = ProcessReplica(basic_service_config, 0, 1, shutdown_event)
    assert replica._should_restart(0) is False
    assert replica._should_restart(1) is False


@pytest.mark.asyncio
async def test_should_restart_always_policy(shutdown_event):
    """Test that restart=always always restarts."""
    config = ServiceConfig(
        name="restart-service",
        command="echo",
        args=["hello"],
        restart=RestartPolicy.ALWAYS,
        restart_delay_ms=10,
    )
    replica = ProcessReplica(config, 0, 1, shutdown_event)
    assert replica._should_restart(0) is True
    assert replica._should_restart(1) is True


@pytest.mark.asyncio
async def test_should_restart_on_failure_policy(restart_on_failure_config, shutdown_event):
    """Test that restart=on-failure only restarts on non-zero exit."""
    replica = ProcessReplica(restart_on_failure_config, 0, 1, shutdown_event)
    assert replica._should_restart(0) is False
    assert replica._should_restart(1) is True
    assert replica._should_restart(127) is True


@pytest.mark.asyncio
async def test_environment_variables_set(basic_service_config, shutdown_event, tmp_path):
    """Test that service environment variables are set correctly."""
    envfile_path = tmp_path / "envfile"
    sc = ServiceConfig(
        name="test-service",
        command="sh",
        args=["-c", f"printenv > {shlex.quote(str(envfile_path))}"],
        replicas=1,
        restart=RestartPolicy.NO,
    )
    replica = ProcessReplica(sc, 42, 67, shutdown_event)
    await replica.run()
    env = dict(line.split("=", 1) for line in envfile_path.read_text().splitlines())
    assert env["CARNIVAL_SERVICE_NAME"] == "test-service"
    assert env["CARNIVAL_REPLICA_ID"] == "42"
    assert env["CARNIVAL_REPLICA_COUNT"] == "67"
    assert env["CARNIVAL_RESTART_COUNT"] == "0"


@pytest.mark.asyncio
async def test_working_dir_set(shutdown_event, tmp_path):
    """Test that working directory is set if specified."""
    config = ServiceConfig(name="test", command="pwd", working_dir=str(tmp_path))
    replica = ProcessReplica(config, 0, 1, shutdown_event)

    with patch("asyncio.create_subprocess_exec", wraps=asyncio.create_subprocess_exec) as wrapped_exec:
        await replica.run()
        call_kwargs = wrapped_exec.call_args.kwargs
        assert call_kwargs["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_restart_count_and_limit(restart_on_failure_config, shutdown_event, caplog):
    """Test that restart count increments correctly."""
    replica = ProcessReplica(restart_on_failure_config, 0, 1, shutdown_event)
    await replica.run()
    assert replica.restart_count == 5
    for x in range(5):
        assert f"restart {x + 1}" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_event_stops_restart(shutdown_event):
    """Test that shutdown event stops restart loop."""
    config = ServiceConfig(
        name="restart-service",
        command="echo",
        args=["hello"],
        restart=RestartPolicy.ALWAYS,
        restart_delay_ms=100,
        restart_limit=10,
    )
    replica = ProcessReplica(config, 0, 1, shutdown_event)

    task = asyncio.create_task(replica.run())
    await asyncio.sleep(0.5)
    shutdown_event.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert 1 < replica.restart_count < 10
    assert task.done()


@pytest.mark.asyncio
async def test_process_termination(basic_service_config, shutdown_event):
    """Test graceful process termination."""
    replica = ProcessReplica(basic_service_config, 0, 1, shutdown_event)

    mock_process = MagicMock()
    mock_process.returncode = None  # Still running
    mock_process.pid = 12345
    mock_process.wait = AsyncMock(return_value=None)

    replica.process = mock_process

    with patch("carnival.process.os.killpg") as mock_killpg:
        await replica._terminate_process("test[0]")

        mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
        mock_process.wait.assert_called()


@pytest.mark.asyncio
async def test_process_termination_timeout(basic_service_config, shutdown_event):
    """Test that SIGKILL is sent on termination timeout."""
    replica = ProcessReplica(basic_service_config, 0, 1, shutdown_event)

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.pid = 12345

    # Make wait timeout then succeed
    wait_call_count = 0

    async def wait_with_timeout():
        nonlocal wait_call_count
        wait_call_count += 1
        if wait_call_count == 1:
            raise asyncio.TimeoutError()
        return None

    mock_process.wait = wait_with_timeout

    replica.process = mock_process

    with patch("carnival.process.os.killpg") as mock_killpg:
        await replica._terminate_process("test[0]")

        assert mock_killpg.call_count == 2
        mock_killpg.assert_any_call(12345, signal.SIGTERM)
        mock_killpg.assert_any_call(12345, signal.SIGKILL)


@pytest.mark.asyncio
async def test_critical_service_triggers_shutdown(shutdown_event):
    """Test that a critical service stopping triggers shutdown."""
    config = ServiceConfig(
        name="critical-service",
        command="true",  # Exits immediately with 0
        restart=RestartPolicy.NO,
        critical=True,
    )
    replica = ProcessReplica(config, 0, 1, shutdown_event)

    assert not shutdown_event.is_set()
    await replica.run()
    # Critical service exited, should trigger shutdown
    assert shutdown_event.is_set()
