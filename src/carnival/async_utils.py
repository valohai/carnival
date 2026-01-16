import asyncio
import asyncio.subprocess


async def wait_for_process_or_event(proc: asyncio.subprocess.Process, event: asyncio.Event) -> None:
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
