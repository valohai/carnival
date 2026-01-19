import asyncio
import asyncio.subprocess
import logging
import os
import signal

logger = logging.getLogger(__name__)


async def wait_for_process_or_event(
    proc: asyncio.subprocess.Process,
    event: asyncio.Event,
) -> None:
    done, pending = await asyncio.wait(
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
        except asyncio.TimeoutError:
            logger.warning(f"{description} did not terminate, sending SIGKILL to process group")
            os.killpg(pid, signal.SIGKILL)
            await process.wait()
    except ProcessLookupError:  # Process already exited
        logger.debug(f"{description} already exited")
    except Exception as e:  # pragma: no cover
        logger.exception(f"Error terminating {description}: {e}")
