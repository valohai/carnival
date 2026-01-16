"""Tests for Carnival manager orchestration."""

import asyncio
from signal import Signals
from unittest.mock import AsyncMock, patch

import pytest

from carnival.config import CarnivalConfig, InitCommand, RestartPolicy, ServiceConfig
from carnival.manager import CarnivalManager


@pytest.mark.asyncio
async def test_run_init_commands_not_found():
    """Test init command not found."""
    config = CarnivalConfig(
        init_commands=[InitCommand(command="nonexistent_command_xyz", args=[])],
    )
    manager = CarnivalManager(config)

    with pytest.raises(FileNotFoundError):
        await manager._run_init_commands()


@pytest.mark.asyncio
async def test_start_services(multi_service_config):
    """Test starting multiple services with replicas."""
    manager = CarnivalManager(multi_service_config)

    # Mock ProcessReplica.run to return immediately
    with patch("carnival.manager.ProcessReplica") as MockReplica:
        mock_replica = AsyncMock()
        mock_replica.run = AsyncMock(return_value=None)
        MockReplica.return_value = mock_replica

        await manager._start_services()

        # Should create 3 replicas total (2 for service1, 1 for service2)
        assert len(manager.running_replicas) == 3
        assert MockReplica.call_count == 3


@pytest.mark.asyncio
async def test_start_services_correct_replica_ids(multi_service_config):
    """Test that replicas get correct IDs."""
    manager = CarnivalManager(multi_service_config)

    with patch("carnival.manager.ProcessReplica.run", side_effect=lambda: AsyncMock(return_value=None)):
        await manager._start_services()
        assert {str(rr.replica) for rr in manager.running_replicas} == {"service1[0]", "service1[1]", "service2[0]"}


@pytest.mark.asyncio
async def test_full_run_lifecycle(simple_config):
    """Test complete run lifecycle."""
    manager = CarnivalManager(simple_config)
    exit_code = await manager.run()
    # Should complete successfully
    assert exit_code == 0


@pytest.mark.asyncio
async def test_interrupt_signal(long_running_config, caplog):
    manager = CarnivalManager(long_running_config)
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(1)
    manager.signal_handler(Signals.SIGINT)  # Pretend we got SIGINT
    exit_code = await task
    # Should complete successfully
    assert exit_code == 0
    assert "Starting service replica: sleepy-service[0]" in caplog.text
    assert "Shutdown requested via signal: SIGINT" in caplog.text


@pytest.mark.asyncio
async def test_run_with_no_services(tmp_path):
    """Test run with only init commands."""
    tmp_file = tmp_path / "testfile.txt"
    config = CarnivalConfig(
        init_commands=[InitCommand(command="touch", args=[str(tmp_file)])],
        services=[],
    )
    manager = CarnivalManager(config)
    exit_code = await manager.run()
    assert exit_code == 0
    assert tmp_file.exists()


@pytest.mark.asyncio
async def test_run_init_failure_exits(tmp_path):
    """Test that init failure causes early exit."""
    init_canary = tmp_path / "ic"
    run_canary = tmp_path / "rc"
    config = CarnivalConfig(
        init_commands=[
            InitCommand(command="true", args=[]),
            InitCommand(command="false", args=[]),
            InitCommand(command="touch", args=[str(init_canary)]),
        ],
        services=[
            ServiceConfig(
                name="test-service",
                command="touch",
                args=[str(run_canary)],
                replicas=1,
                restart=RestartPolicy.NO,
            )
        ],
    )

    manager = CarnivalManager(config)
    exit_code = await manager.run()
    assert exit_code == 1
    assert not init_canary.exists(), "Last init command should not have run"
    assert not run_canary.exists(), "Service should not have started due to init failure"
