"""Agent catalog — canonical Agent Cards and launch specs.

Keeping the cards in one place avoids the "empty Agent Card" problem
(``description=''``, ``skills=[]``) that made agents undiscoverable by
capability: the registry resolves skills from the card, and the Web UI
lists them via ``/api/agents``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.protocol.models import AgentCard, Skill


@dataclass(frozen=True)
class AgentSpec:
    name: str
    module: str
    class_name: str
    port: int
    description: str
    skills: tuple[Skill, ...] = field(default_factory=tuple)


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="WikipediaAgent",
        module="src.agents.wikipedia",
        class_name="WikipediaAgent",
        port=8001,
        description="百科实体检索：通过 DBpedia Lookup 返回实体摘要与词条链接（中英文查询均可）。",
        skills=(
            Skill(
                id="search-entities",
                name="百科实体检索",
                description="按关键词检索百科实体，返回标题、摘要与词条 URL。",
                tags=["encyclopedia", "dbpedia", "entity"],
                examples=["爱因斯坦是谁", "量子计算"],
            ),
        ),
    ),
    AgentSpec(
        name="ArxivAgent",
        module="src.agents.arxiv",
        class_name="ArxivAgent",
        port=8002,
        description=(
            "学术论文检索：调用 arXiv API 检索论文标题、摘要与作者"
            "（中文查询经词典/LLM 翻译）。"
        ),
        skills=(
            Skill(
                id="search-papers",
                name="学术论文检索",
                description="按关键词检索 arXiv 论文，返回标题、摘要、作者与链接。",
                tags=["papers", "arxiv", "academic"],
                examples=["量子计算最新论文", "large language model"],
            ),
        ),
    ),
    AgentSpec(
        name="GithubAgent",
        module="src.agents.github",
        class_name="GithubAgent",
        port=8003,
        description=(
            "开源仓库检索：按关键词检索 GitLab 公开项目"
            "（注意：数据源为 GitLab，非 GitHub）。"
        ),
        skills=(
            Skill(
                id="search-repositories",
                name="开源仓库检索",
                description="按关键词检索公开代码仓库，返回名称、描述、star 数与链接。",
                tags=["code", "gitlab", "repository"],
                examples=["量子计算开源实现", "RAG framework"],
            ),
        ),
    ),
    AgentSpec(
        name="WeatherAgent",
        module="src.agents.weather",
        class_name="WeatherAgent",
        port=8004,
        description="实时天气查询：调用 wttr.in 返回城市当前温度、湿度与天气描述。",
        skills=(
            Skill(
                id="get-weather",
                name="实时天气查询",
                description="按城市名查询当前天气（支持常见中文城市名映射）。",
                tags=["weather", "current"],
                examples=["北京现在天气", "上海气温"],
            ),
        ),
    ),
    AgentSpec(
        name="WikidataAgent",
        module="src.agents.wikidata",
        class_name="WikidataAgent",
        port=8005,
        description=(
            "知识图谱实体检索：调用 Wikidata 实体搜索 API；"
            "线上 API 不可用时回退到本地快照（mock），返回结果会标注来源。"
        ),
        skills=(
            Skill(
                id="search-knowledge-graph",
                name="知识图谱实体检索",
                description="按关键词检索 Wikidata 实体，返回 QID、标签、描述与实体 URL。",
                tags=["knowledge-graph", "wikidata", "entity"],
                examples=["北京", "人工智能"],
            ),
        ),
    ),
)

_SPEC_BY_NAME: dict[str, AgentSpec] = {spec.name: spec for spec in AGENT_SPECS}


def get_spec(name: str) -> AgentSpec | None:
    return _SPEC_BY_NAME.get(name)


def build_card(spec: AgentSpec, host: str = "localhost", scheme: str = "http") -> AgentCard:
    return AgentCard(
        name=spec.name,
        description=spec.description,
        version="0.2.0",
        protocolVersion="0.3.0",
        url=f"{scheme}://{host}:{spec.port}",
        skills=list(spec.skills),
    )
