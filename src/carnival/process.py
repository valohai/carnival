"""Process management and replica handling for Carnival services."""

import asyncio
import logging
import os
import signal

from carnival.config import ServiceConfig

logger = logging.getLogger(__name__)


def _format_exit_status(returncode: int | None) -> str:
    """Format a process exit status for logging."""
    if returncode is None:
        return "still running"
    if returncode < 0:
        # Negative returncode means killed by signal
        sig_num = -returncode
        try:
            sig_name = signal.Signals(sig_num).name
            return f"killed by {sig_name}"
        except ValueError:
            return f"killed by signal {sig_num}"
    return f"exited with code {returncode}"


async def _forward_stream(
    stream: asyncio.StreamReader | None,
    replica_str: str,
    stream_name: str,
) -> None:  # pragma: no cover (presently unused)
    """Forward process output to logger."""
    if stream is None:
        return

    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            # Decode and log the line
            text = line.decode("utf-8", errors="replace").rstrip()
            logger.info(f"{replica_str} [{stream_name}]: {text}")
    except Exception as e:
        logger.debug(f"{replica_str} stream forwarding error: {e}")


class ProcessReplica:
    """Manages a single service replica with restart logic."""

    def __init__(
        self,
        service_config: ServiceConfig,
        replica_id: int,
        total_replicas: int,
        shutdown_event: asyncio.Event,
    ):
        self.config = service_config
        self.replica_id = replica_id
        self.total_replicas = total_replicas
        self.shutdown_event = shutdown_event
        self.restart_count = 0
        self.process: asyncio.subprocess.Process | None = None

    def __str__(self) -> str:
        return f"{self.config.name}[{self.replica_id}]"

    async def run(self) -> None:
        """Run the service replica with restart logic."""
        service_name = self.config.name
        replica_str = f"{service_name}[{self.replica_id}]"

        logger.info(f"Starting service replica: {replica_str}")

        while not self.shutdown_event.is_set():
            # Check if we've exceeded restart limit
            if self.config.restart_limit and self.restart_count >= self.config.restart_limit:
                logger.info(f"{replica_str} reached restart limit ({self.config.restart_limit}), stopping")
                break

            exit_code = await self._start_process(replica_str)

            if self.shutdown_event.is_set():
                # No need to log anything, we're shutting down
                break

            if not self._should_restart(exit_code):
                logger.info(
                    f"{replica_str} {_format_exit_status(exit_code)}, not restarting (policy: {self.config.restart})"
                )
                break

            self.restart_count += 1
            logger.info(
                f"{replica_str} {_format_exit_status(exit_code)}, "
                f"restarting in {self.config.restart_delay_ms}ms "
                f"(restart {self.restart_count})"
            )

            if self.config.restart_delay_ms:
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=self.config.restart_delay_ms / 1000.0,
                    )
                    # If we get here, shutdown was triggered
                    break
                except asyncio.TimeoutError:
                    # Timeout is expected, continue to restart
                    pass

        if self.config.critical and not self.shutdown_event.is_set():
            logger.warning(f"Critical service {replica_str} stopped, initiating shutdown")
            self.shutdown_event.set()

    async def _start_process(self, replica_str: str) -> int:
        """Start the process and wait for it to complete, return its exit code."""
        env = os.environ.copy()
        env["CARNIVAL_SERVICE_NAME"] = self.config.name
        env["CARNIVAL_REPLICA_ID"] = str(self.replica_id)
        env["CARNIVAL_REPLICA_COUNT"] = str(self.total_replicas)
        env["CARNIVAL_RESTART_COUNT"] = str(self.restart_count)
        redirect_output = False  # Currently always false, because we don't want this process throttling logs

        try:
            # Create the subprocess
            self.process = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                env=env,
                cwd=self.config.working_dir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=(asyncio.subprocess.PIPE if redirect_output else None),
                stderr=(asyncio.subprocess.PIPE if redirect_output else None),
                start_new_session=True,
            )

        except Exception as e:  # pragma: no cover
            logger.exception(f"{replica_str} failed to start: {e}")
            return 70  # EX_SOFTWARE

        logger.debug(f"{replica_str} started with PID {self.process.pid}")

        if redirect_output:  # pragma: no cover (presently unused)
            # Create tasks to forward stdout/stderr
            stdout_task = asyncio.create_task(_forward_stream(self.process.stdout, replica_str, "stdout"))
            stderr_task = asyncio.create_task(_forward_stream(self.process.stderr, replica_str, "stderr"))
        else:
            stdout_task = stderr_task = None

        # Wait for process to complete or shutdown event
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(self.process.wait()),
                asyncio.create_task(self.shutdown_event.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # If shutdown was triggered, terminate the process
        if self.shutdown_event.is_set() and self.process.returncode is None:
            await self._terminate_process(replica_str)

        if redirect_output:  # pragma: no cover (presently unused)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        return self.process.returncode or 0

    def _should_restart(self, exit_code: int) -> bool:
        """Determine if the service should restart based on exit code and policy."""
        if self.config.restart == "no":
            return False
        elif self.config.restart == "always":
            return True
        elif self.config.restart == "on-failure":
            return exit_code != 0
        raise ValueError("Invalid restart policy")  # pragma: no cover

    async def _terminate_process(self, replica_str: str) -> None:
        """Gracefully terminate the process and its process group."""
        if self.process is None or self.process.returncode is not None:  # pragma: no cover
            return

        pid = self.process.pid
        logger.info(f"Terminating {replica_str} (PID {pid})")

        try:
            # Send SIGTERM to the entire process group (since we use start_new_session=True,
            # the child is the process group leader and its PID equals the PGID)
            os.killpg(pid, signal.SIGTERM)
            # Wait for graceful shutdown
            stop_timeout = self.config.stop_timeout_ms / 1000.0
            try:
                await asyncio.wait_for(self.process.wait(), timeout=stop_timeout)
                logger.debug(f"{replica_str} terminated gracefully")
            except asyncio.TimeoutError:
                logger.warning(f"{replica_str} did not terminate, sending SIGKILL to process group")
                os.killpg(pid, signal.SIGKILL)
                await self.process.wait()
        except ProcessLookupError:  # Process already exited
            logger.debug(f"{replica_str} already exited")
        except Exception as e:  # pragma: no cover
            logger.exception(f"Error terminating {replica_str}: {e}")
