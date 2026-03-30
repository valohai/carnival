import asyncio
import asyncio.subprocess
import logging
import os
import signal

logger = logging.getLogger(__name__)


async def reap_zombies(interval: float = 30.0) -> None:
    """Periodically reap orphaned child processes.

    When running as PID 1 (e.g. in a Docker container), grandchild processes
    whose parents exit get reparented to us. This task reaps them so they
    don't accumulate as zombies.

    Note: This uses waitpid(-1), which can race with asyncio's child watcher
    and steal the exit status of a managed subprocess. When this happens,
    asyncio reports the process as having exited with code 255. A longer
    polling interval reduces the likelihood of this race, but does not
    eliminate it entirely. In practice, since this is primarily needed in
    PID 1 / container scenarios where zombie accumulation is the bigger
    concern, the trade-off is acceptable.
    """
    while True:
        await asyncio.sleep(interval)
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)  # noqa: ASYNC222 (wnohang; will return immediately)
                if pid == 0:
                    break
                logger.debug("Reaped orphaned child process (PID %d, status %d)", pid, status)
            except ChildProcessError:
                # No child processes at all
                break


async def wait_for_process_or_event(
    proc: asyncio.subprocess.Process,
    event: asyncio.Event,
) -> None:
    _done, pending = await asyncio.wait(
        [
            asyncio.create_task(proc.wait()),
            asyncio.create_task(event.wait()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def kill_process_group(
    process: asyncio.subprocess.Process,
    *,
    description: str,
    stop_timeout: float,
):
    pid = process.pid
    logger.info(f"Terminating {description} (PID {pid})")
    try:
        # Send SIGTERM to the entire process group (since we use start_new_session=True,
        # the child is the process group leader and its PID equals the PGID)
        os.killpg(pid, signal.SIGTERM)
        # Wait for graceful shutdown
        try:
            await asyncio.wait_for(process.wait(), timeout=stop_timeout)
            logger.debug(f"{description} terminated gracefully")
        except TimeoutError:
            logger.warning(f"{description} did not terminate, sending SIGKILL to process group")
            os.killpg(pid, signal.SIGKILL)
            await process.wait()
    except ProcessLookupError:  # Process already exited
        logger.debug(f"{description} already exited")
    except Exception as e:  # pragma: no cover
        logger.exception(f"Error terminating {description}: {e}")
