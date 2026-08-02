from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Awaitable

from src.protocol.models import AgentCard, Message, Task

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, timeout: float = 30.0, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries

    async def dispatch(
        self,
        tasks: list[tuple[AgentCard, Message]],
        send_fn: Callable[[Any, Message], Awaitable[Task]],
    ) -> list[Task]:
        from src.protocol.client import A2AClient

        async def _send_with_retry(card: AgentCard, msg: Message) -> Task:
            client = A2AClient(base_url=card.endpoint)
            try:
                for attempt in range(self.max_retries + 1):
                    try:
                        return await asyncio.wait_for(
                            send_fn(client, msg), timeout=self.timeout
                        )
                    except Exception:
                        if attempt == self.max_retries:
                            raise
                        logger.warning(
                            "Retry %d for %s after error", attempt + 1, card.name
                        )
                        await asyncio.sleep(2 ** attempt)
            finally:
                await client.close()

        coros = [_send_with_retry(card, msg) for card, msg in tasks]
        results = await asyncio.gather(*coros, return_exceptions=True)
        successful = []
        for r in results:
            if isinstance(r, Task):
                successful.append(r)
            else:
                logger.warning("Dispatch failed: %s", r)
        return successful
