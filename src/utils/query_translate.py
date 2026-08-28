"""Query translator — converts Chinese queries to English keywords for API search.

Two-layer strategy: LLM translation (when configured) → dictionary fallback.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.base import LLMProvider

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

# High-frequency Chinese technical terms → English keywords
ZH_EN_KEYWORDS: dict[str, str] = {
    # CS / AI
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "强化学习": "reinforcement learning",
    "神经网络": "neural network",
    "卷积神经网络": "convolutional neural network",
    "循环神经网络": "recurrent neural network",
    "自然语言处理": "natural language processing",
    "计算机视觉": "computer vision",
    "大语言模型": "large language model",
    "生成式人工智能": "generative AI",
    "生成对抗网络": "generative adversarial network",
    "知识图谱": "knowledge graph",
    "知识蒸馏": "knowledge distillation",
    "迁移学习": "transfer learning",
    "联邦学习": "federated learning",
    "注意力机制": "attention mechanism",
    "预训练": "pre-training",
    "微调": "fine-tuning",
    "数据挖掘": "data mining",
    "推荐系统": "recommendation system",
    # Quantum
    "量子计算": "quantum computing",
    "量子力学": "quantum mechanics",
    "量子纠缠": "quantum entanglement",
    "量子比特": "qubit",
    # Robotics / other
    "机器人": "robot",
    "自动驾驶": "autonomous driving",
    "区块链": "blockchain",
    "加密货币": "cryptocurrency",
    "分布式系统": "distributed systems",
    "操作系统": "operating system",
    "编译器": "compiler",
    "数据库": "database",
    "搜索引擎": "search engine",
    # Filler / query words to strip
    "的": "",
    "了": "",
    "和": "",
    "与": "",
    "或": "",
    "的最新": "",
    "最新": "",
    "论文": "",
    "研究": "",
    "学术": "",
    "开源": "",
    "项目": "",
    "代码": "",
    "仓库": "",
    "是什么": "",
    "有哪些": "",
    "怎么样": "",
    "如何": "",
    "百科": "",
    "定义": "",
    "概念": "",
    "数据": "",
    "实体": "",
    "查询": "",
}


class QueryTranslator:
    """Translate Chinese queries to English keywords for API search.

    - When LLM is configured: uses LLM for translation (async).
    - When LLM is not configured: uses dictionary matching (sync).
    - LLM failure falls back to dictionary automatically.
    """

    def __init__(self, llm: LLMProvider | None = None):
        self._llm = llm

    async def translate(self, query: str) -> str:
        """Translate a potentially-Chinese query into English keywords."""
        if not self._contains_cjk(query):
            return query
        if self._llm:
            result = await self._llm_translate(query)
            if result:
                return result
        return self._dict_translate(query)

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return bool(_CJK_RE.search(text))

    def _dict_translate(self, query: str) -> str:
        """Match known Chinese terms in query and replace with English."""
        result = query
        # Sort by length descending so longer terms match first
        for zh, en in sorted(ZH_EN_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True):
            result = result.replace(zh, en)
        # Strip remaining CJK characters and clean up
        result = _CJK_RE.sub("", result)
        result = re.sub(r"[？?！!。，,：:;；\s]+", " ", result).strip()
        return result

    async def _llm_translate(self, query: str) -> str | None:
        """Use LLM to translate Chinese query to English keywords."""
        prompt = (
            "将以下中文查询翻译为适合学术论文或代码仓库搜索的英文关键词。"
            "只返回英文关键词，用空格分隔，不要解释，不要标点。\n"
            f"查询：{query}"
        )
        try:
            response = await self._llm.chat([{"role": "user", "content": prompt}])
            result = response.strip()
            # Sanity check: result should contain ASCII letters
            if result and re.search(r"[a-zA-Z]", result):
                return result
            return None
        except Exception:
            return None
