import pytest

from carnival.config import CarnivalConfig, InitCommand, RestartPolicy, ServiceConfig
from carnival.manager import CarnivalManager


def pytest_configure():
    CarnivalManager.setup_signal_handlers = False  # No signal handlers during tests


@pytest.fixture
def simple_config():
    """Create a simple test config."""
    return CarnivalConfig(
        init_commands=[InitCommand(command="echo", args=["init"])],
        services=[
            ServiceConfig(
                name="test-service",
                command="echo",
                args=["hello"],
                replicas=1,
                restart=RestartPolicy.NO,
            )
        ],
    )


@pytest.fixture
def long_running_config():
    """Create a simple test config with a long-running service."""
    return CarnivalConfig(
        init_commands=[],
        services=[
            ServiceConfig(
                name="sleepy-service",
                command="sleep",
                args=["67"],
                replicas=1,
                restart=RestartPolicy.NO,
            )
        ],
    )


@pytest.fixture
def multi_service_config():
    """Create a config with multiple services."""
    return CarnivalConfig(
        init_commands=[],
        services=[
            ServiceConfig(
                name="service1",
                command="echo",
                args=["one"],
                replicas=2,
                restart=RestartPolicy.NO,
            ),
            ServiceConfig(
                name="service2",
                command="echo",
                args=["two"],
                replicas=1,
                restart=RestartPolicy.ALWAYS,
            ),
        ],
    )
