"""Dispatcher — parallel fan-out to remote A2A agents, with timeout + retry."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.protocol.client import A2AClient
from src.protocol.models import AgentCard, Message, Task

logger = logging.getLogger(__name__)


def _describe_error(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"
    text = str(exc)
    return text if text else type(exc).__name__


@dataclass
class DispatchResult:
    """Outcome of one agent call; failures are kept instead of swallowed."""

    card: AgentCard
    task: Task | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.task is not None


SendFn = Callable[[A2AClient, Message], Awaitable[Task]]


class Dispatcher:
    def __init__(self, timeout: float = 30.0, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries

    async def dispatch(
        self,
        tasks: list[tuple[AgentCard, Message]],
        send_fn: SendFn,
        max_concurrency: int = 5,
    ) -> list[DispatchResult]:
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def _send_with_retry(card: AgentCard, msg: Message) -> DispatchResult:
            async with semaphore:
                client = A2AClient(base_url=card.url)
                try:
                    last_error: Exception | None = None
                    for attempt in range(self.max_retries + 1):
                        try:
                            task = await asyncio.wait_for(
                                send_fn(client, msg), timeout=self.timeout
                            )
                            return DispatchResult(card=card, task=task)
                        except Exception as exc:  # noqa: BLE001 - retried below
                            last_error = exc
                            if isinstance(exc, asyncio.TimeoutError):
                                last_error = TimeoutError(f"timeout after {self.timeout}s")
                            if attempt == self.max_retries:
                                break
                            logger.warning(
                                "Retry %d/%d for %s after error: %s",
                                attempt + 1,
                                self.max_retries,
                                card.name,
                                exc,
                            )
                            await asyncio.sleep(2**attempt)
                    return DispatchResult(card=card, error=_describe_error(last_error))
                finally:
                    await client.close()

        results = await asyncio.gather(
            *[_send_with_retry(card, msg) for card, msg in tasks],
            return_exceptions=True,
        )
        outcomes: list[DispatchResult] = []
        for (card, _), result in zip(tasks, results, strict=False):
            if isinstance(result, DispatchResult):
                outcomes.append(result)
            else:  # defensive: gather(return_exceptions=True) surfaced something odd
                outcomes.append(DispatchResult(card=card, error=str(result)))
        return outcomes
