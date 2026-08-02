from __future__ import annotations

DECOMPOSE_PROMPT = """将以下问题分解为子问题，每个子问题对应一个知识源。
可用知识源：{available_agents}

用户问题：{query}

返回 JSON 格式的子任务列表，格式：
[{{"query": "子问题", "agents": ["AgentName"]}}]"""

AGGREGATE_PROMPT = """基于以下各知识源的回答，生成一个综合、连贯的回答。

原始问题：{query}
各知识源回答：
{results}

要求：引用具体来源，标注信息来源。"""

ROUTE_PROMPT = """根据用户问题，推荐最合适的知识源。

可用知识源：{agents}

用户问题：{query}

返回应该调用的 Agent 名称列表（JSON 数组）。"""
