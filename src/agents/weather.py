"""Weather Agent — queries wttr.in API for weather data."""
from __future__ import annotations

import re

import httpx

from src.agents.base import BaseAgent
from src.protocol.models import Message, Part, Task

_STRIP_RE = re.compile(
    r"[？?！!。，,：:；;、\s]+"
    r"|天气|气候|温度|气温|湿度|降雨|预报|现在|今天|目前|怎么样|如何|什么|怎样|多少|呢|吗|的"
)
# wttr.in resolves Latin city names reliably; map the common Chinese ones.
_CITY_ALIASES: dict[str, str] = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "武汉": "Wuhan",
    "西安": "Xi'an",
    "南京": "Nanjing",
    "重庆": "Chongqing",
    "香港": "Hong Kong",
    "台北": "Taipei",
    "东京": "Tokyo",
    "纽约": "New York",
    "伦敦": "London",
    "巴黎": "Paris",
    "新加坡": "Singapore",
}


def _extract_city(raw: str) -> str:
    """Best-effort city extraction that tolerates Chinese question phrasing."""
    for zh, en in _CITY_ALIASES.items():
        if zh in raw:
            return en
    cleaned = _STRIP_RE.sub(" ", raw).strip()
    candidates = re.findall(r"[\u4e00-\u9fff]{2,}", cleaned)
    if candidates:
        return candidates[0]
    return cleaned or raw.strip()


class WeatherAgent(BaseAgent):
    API_URL = "https://wttr.in/{city}?format=j1"

    async def handle_message(self, message: Message, task: Task) -> Message:
        raw = self.extract_text(message)
        city = _extract_city(raw)
        try:
            result = await self._get_weather(city)
            parts = [
                Part(
                    kind="text",
                    text=(
                        f"Weather in {city}: {result['temperature']}°C, "
                        f"{result['condition']}"
                    ),
                ),
                Part(kind="data", data=result),
            ]
        except Exception as e:
            parts = [Part(kind="text", text=f"Failed to get weather for '{city}': {e}")]
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
                "condition": (
                    cc["weatherDesc"][0]["value"].strip() if cc.get("weatherDesc") else "unknown"
                ),
            }


