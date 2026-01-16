"""Main orchestrator for Carnival process management."""

import asyncio
import dataclasses
import logging
import signal
import subprocess
import time

from carnival.async_utils import wait_for_process_or_event
from carnival.config import CarnivalConfig, InitCommand
from carnival.process import ProcessReplica

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunningReplica:
    task: asyncio.Task
    replica: ProcessReplica


class AsyncioEventWithSignalData(asyncio.Event):
    """An asyncio Event that also stores the last signal received."""

    last_signal_received: signal.Signals | None = None


class CarnivalManager:
    """Orchestrates initialization, service management, and shutdown."""

    setup_signal_handlers = True  # Overridden by tests

    def __init__(self, config: CarnivalConfig):
        self.config = config
        self.shutdown_event = AsyncioEventWithSignalData()
        self.running_replicas: list[RunningReplica] = []

    def signal_handler(self, sig: signal.Signals) -> None:
        self.shutdown_event.set()
        self.shutdown_event.last_signal_received = sig

    async def run(self) -> int:
        loop = asyncio.get_running_loop()

        if self.setup_signal_handlers:  # pragma: no cover
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                loop.add_signal_handler(sig, self.signal_handler, sig)

        # Phase 1: Run initialization commands sequentially
        try:
            await self._run_init_commands()
        except Exception as exc:
            logger.exception("Initialization failed: %s, exiting", exc)
            return 1

        # Phase 2: Start all services
        logger.info("Starting services")
        await self._start_services()

        if not self.running_replicas:
            logger.warning("No services configured, exiting")
            return 0

        # Phase 3: Monitor services until shutdown
        logger.info(f"Running {len(self.running_replicas)} service replicas")
        await self._monitor_services()

        # Phase 4: Graceful shutdown
        if self.shutdown_event.last_signal_received:
            logger.info(
                "Shutdown requested via signal: %s",
                self.shutdown_event.last_signal_received.name,
            )
        logger.info("Shutting down services")
        await self._shutdown_services()

        logger.info("The Carnival is over...")
        return 0

    async def _run_init_commands(self) -> bool:
        """
        Run initialization commands sequentially.

        Returns:
            True if all commands succeeded; will raise on failure.
        """
        for i, init_cmd in enumerate(self.config.init_commands, 1):
            t0 = time.time()
            logger.info("Running init command %d: %s", i, init_cmd.as_command_line())
            await self._handle_run_init_command(init_cmd)
            t1 = time.time()
            logger.info("Init command %d finished in %.2f seconds", i, t1 - t0)
        return True

    async def _handle_run_init_command(self, init_cmd: InitCommand):
        proc = await asyncio.create_subprocess_exec(
            init_cmd.command,
            *init_cmd.args,
            cwd=init_cmd.working_dir,
            stdin=asyncio.subprocess.DEVNULL,
        )

        await wait_for_process_or_event(proc, self.shutdown_event)

        # If shutdown was triggered during init, terminate and raise
        if self.shutdown_event.is_set():
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            raise InterruptedError("Shutdown requested during initialization")
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, init_cmd.as_command_line())

    async def _start_services(self) -> None:
        """Start all service replicas."""
        for service_config in self.config.services:
            replicas = service_config.replicas
            logger.info(f"Starting service {service_config.name!r} with {replicas} replica(s)")

            for replica_id in range(replicas):
                replica = ProcessReplica(
                    service_config=service_config,
                    replica_id=replica_id,
                    total_replicas=replicas,
                    shutdown_event=self.shutdown_event,
                )
                task = asyncio.create_task(replica.run())
                self.running_replicas.append(RunningReplica(task=task, replica=replica))

    @property
    def replica_tasks(self) -> list[asyncio.Task]:
        """Get the list of tasks for running replicas."""
        return [rr.task for rr in self.running_replicas]

    async def _monitor_services(self) -> None:
        """Monitor service replicas until shutdown or all exit."""
        if not self.running_replicas:  # pragma: no cover
            raise ValueError("No service replicas to monitor")

        # Wait for either shutdown event or all tasks to complete
        shutdown_task = asyncio.create_task(self.shutdown_event.wait())
        tasks_with_shutdown = [shutdown_task, *self.replica_tasks]

        try:
            # Wait for first completion
            done, pending = await asyncio.wait(tasks_with_shutdown, return_when=asyncio.FIRST_COMPLETED)

            # Check if shutdown was triggered
            if shutdown_task in done:
                logger.debug("Shutdown event triggered")
                return

            # Check if any service tasks completed
            for task in done:
                if task != shutdown_task:
                    try:
                        await task
                    except Exception as e:  # pragma: no cover
                        logger.exception(f"Service task failed: {e}")

            # If we're here, at least one service exited
            # Wait for all remaining services to exit or shutdown
            remaining_tasks = [t for t in self.replica_tasks if not t.done()]
            if remaining_tasks:
                logger.info(f"Waiting for {len(remaining_tasks)} remaining services")
                await asyncio.wait(
                    [shutdown_task, *remaining_tasks],
                    return_when=asyncio.FIRST_COMPLETED,
                )

        except asyncio.CancelledError:
            logger.debug("Service monitoring cancelled")
            raise

    async def _shutdown_services(self) -> None:
        """Gracefully shutdown all services."""
        if not self.running_replicas:  # pragma: no cover
            return

        # Set shutdown event (in case not already set)
        self.shutdown_event.set()

        shutdown_timeout = self.config.global_config.shutdown_timeout_ms / 1000.0

        # Wait for all tasks to complete with timeout
        logger.info("Waiting for services to exit gracefully")
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.replica_tasks, return_exceptions=True),
                timeout=shutdown_timeout,
            )
            logger.info("All services exited")
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for services to exit")
            # Cancel any remaining tasks
            for task in self.replica_tasks:
                if not task.done():
                    task.cancel()
            # Wait a bit for cancellations
            await asyncio.wait_for(
                asyncio.gather(*self.replica_tasks, return_exceptions=True),
                timeout=2.0,
            )
