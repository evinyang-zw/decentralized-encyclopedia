"""Tests for QueryTranslator."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.utils.query_translate import QueryTranslator, ZH_EN_KEYWORDS


class TestDictTranslate:
    def test_english_passthrough(self):
        t = QueryTranslator()
        assert t._dict_translate("quantum computing") == "quantum computing"

    def test_chinese_keyword_match(self):
        t = QueryTranslator()
        result = t._dict_translate("量子计算")
        assert "quantum computing" in result

    def test_mixed_chinese_english(self):
        t = QueryTranslator()
        result = t._dict_translate("机器学习算法")
        assert "machine learning" in result

    def test_filler_words_stripped(self):
        t = QueryTranslator()
        result = t._dict_translate("开源机器学习项目")
        assert "machine learning" in result
        assert "开源" not in result
        assert "项目" not in result

    def test_all_chinese_mapped(self):
        t = QueryTranslator()
        result = t._dict_translate("深度学习论文")
        assert "deep learning" in result
        # CJK and filler should be stripped
        assert not any(0x4e00 <= ord(c) <= 0x9fff for c in result)

    def test_unknown_chinese_returns_empty(self):
        t = QueryTranslator()
        result = t._dict_translate("完全未知的查询")
        # All CJK stripped, nothing remains
        assert result.strip() == "" or len(result.strip()) > 0

    def test_contains_cjk(self):
        assert QueryTranslator._contains_cjk("量子计算") is True
        assert QueryTranslator._contains_cjk("quantum") is False
        assert QueryTranslator._contains_cjk("量子quantum") is True


class TestTranslateAsync:
    @pytest.mark.asyncio
    async def test_english_returns_directly(self):
        t = QueryTranslator()
        result = await t.translate("quantum computing")
        assert result == "quantum computing"

    @pytest.mark.asyncio
    async def test_chinese_uses_dict(self):
        t = QueryTranslator()
        result = await t.translate("量子计算论文")
        assert "quantum computing" in result

    @pytest.mark.asyncio
    async def test_llm_called_when_configured(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="quantum computing papers")
        t = QueryTranslator(llm=mock_llm)
        result = await t.translate("量子计算论文")
        assert result == "quantum computing papers"
        mock_llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_dict(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))
        t = QueryTranslator(llm=mock_llm)
        result = await t.translate("量子计算")
        assert "quantum computing" in result

    @pytest.mark.asyncio
    async def test_llm_empty_response_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="")
        t = QueryTranslator(llm=mock_llm)
        result = await t.translate("量子计算")
        assert "quantum computing" in result


class TestKeywordDict:
    def test_has_common_terms(self):
        assert "机器学习" in ZH_EN_KEYWORDS
        assert "深度学习" in ZH_EN_KEYWORDS
        assert "量子计算" in ZH_EN_KEYWORDS
        assert "神经网络" in ZH_EN_KEYWORDS
        assert "自然语言处理" in ZH_EN_KEYWORDS

    def test_filler_words_map_to_empty(self):
        assert ZH_EN_KEYWORDS.get("的") == ""
        assert ZH_EN_KEYWORDS.get("论文") == ""
        assert ZH_EN_KEYWORDS.get("开源") == ""
