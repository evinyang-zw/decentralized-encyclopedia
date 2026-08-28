"""Weather Agent — queries wttr.in API for weather data."""
from __future__ import annotations

import re

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task


_STRIP_RE = re.compile(r"[？?！!。，,\s]+|天气|气候|温度|怎么样|如何|什么|怎样")


class WeatherAgent(BaseAgent):
    API_URL = "https://wttr.in/{city}?format=j1"

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message)
        city = _STRIP_RE.sub("", raw).strip() or raw.strip()
        try:
            result = await self._get_weather(city)
            parts = [
                Part(type="text", text=f"Weather in {city}: {result['temperature']}°C, {result['condition']}"),
                Part(type="data", data=result),
            ]
        except Exception as e:
            parts = [Part(type="text", text=f"Failed to get weather for '{city}': {e}")]
        return Message(role="agent", parts=parts)

    async def _get_weather(self, city: str) -> dict:
        url = self.API_URL.format(city=city)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            cc = data["current_condition"][0]
            area = data["nearest_area"][0]
            return {
                "city": area["areaName"][0]["value"] if area.get("areaName") else city,
                "temperature": int(cc["temp_C"]),
                "humidity": int(cc["humidity"]),
                "condition": cc["weatherDesc"][0]["value"].strip() if cc.get("weatherDesc") else "unknown",
            }


