from __future__ import annotations
import logging

from src.protocol.models import AgentCard

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentCard] = {}
        self._disabled: set[str] = set()

    def register_sync(self, card: AgentCard) -> None:
        self._agents[card.name] = card
        logger.info("Registered agent: %s at %s", card.name, card.endpoint)

    def unregister_sync(self, name: str) -> None:
        self._agents.pop(name, None)
        self._disabled.discard(name)
        logger.info("Unregistered agent: %s", name)

    def disable(self, name: str) -> bool:
        if name not in self._agents:
            return False
        self._disabled.add(name)
        logger.info("Disabled agent: %s", name)
        return True

    def enable(self, name: str) -> bool:
        self._disabled.discard(name)
        logger.info("Enabled agent: %s", name)
        return True

    def is_disabled(self, name: str) -> bool:
        return name in self._disabled

    def discover_sync(self, skill_name: str) -> list[AgentCard]:
        result = []
        for card in self._agents.values():
            for skill in card.skills:
                if skill.name == skill_name:
                    result.append(card)
                    break
        return result

    def get_all(self) -> list[AgentCard]:
        return list(self._agents.values())

    def get_enabled(self) -> list[AgentCard]:
        return [c for c in self._agents.values() if c.name not in self._disabled]

    def get_by_name(self, name: str) -> AgentCard | None:
        return self._agents.get(name)

    async def auto_discover(self, endpoints: list[str]):
        from src.protocol.client import A2AClient
        for endpoint in endpoints:
            try:
                client = A2AClient(base_url=endpoint)
                card = await client.get_agent_card()
                self.register_sync(card)
                await client.close()
            except Exception as e:
                logger.warning("Failed to discover agent at %s: %s", endpoint, e)
