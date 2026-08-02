"""Weather Agent — queries OpenWeatherMap API for weather data."""
from __future__ import annotations
import os

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import AgentCard, Message, Part, Task


class WeatherAgent(BaseAgent):
    API_URL = "https://api.openweathermap.org/data/2.5/weather"

    def __init__(
        self,
        card: AgentCard,
        api_key: str | None = None,
        weather_api_key: str | None = None,
    ):
        super().__init__(card, api_key)
        self.weather_api_key = weather_api_key or os.getenv("OPENWEATHERMAP_API_KEY", "")

    async def handle_message(self, message: Message, task: Task) -> Message:
        city = self.extract_text(message)
        result = await self._get_weather(city)
        parts = [
            Part(type="text", text=f"Weather in {city}: {result['temperature']}°C, {result['condition']}"),
            Part(type="data", data=result),
        ]
        return Message(role="agent", parts=parts)

    async def _get_weather(self, city: str) -> dict:
        params = {"q": city, "appid": self.weather_api_key, "units": "metric"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return {
                "city": data.get("name", city),
                "temperature": data["main"]["temp"],
                "humidity": data["main"]["humidity"],
                "condition": data["weather"][0]["description"] if data.get("weather") else "unknown",
            }


