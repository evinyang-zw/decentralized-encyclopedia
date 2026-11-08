"""一键启动整个系统：5 个 domain agents + Coordinator + Web Server。

Agents 是独立进程，各自暴露 A2A JSON-RPC 端点（端口 8001–8005）；
Coordinator 在 Web 进程内（不是独立端口），Web UI 在 http://localhost:8000。
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv

load_dotenv(os.path.join(_project_root, ".env"))

import httpx

from src.agents.catalog import AGENT_SPECS
from src.protocol.server import CARD_PATH


def _init_llm():
    """从环境变量初始化 LLM Provider，未配置则返回 None（规则模式）。"""
    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider == "orca":
        from src.llm.orcarouter_provider import OrcaRouterProvider

        api_key = os.getenv("ORCAROUTER_API_KEY", "")
        model = os.getenv("ORCAROUTER_MODEL")
        return OrcaRouterProvider(api_key=api_key, model=model) if api_key else None
    if provider == "openai":
        from src.llm.openai_provider import OpenAIProvider

        api_key = os.getenv("OPENAI_API_KEY", "")
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        return OpenAIProvider(api_key=api_key, model=model) if api_key else None
    if provider == "anthropic":
        from src.llm.anthropic_provider import AnthropicProvider

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        return AnthropicProvider(api_key=api_key, model=model) if api_key else None
    return None


def start_agents(project_root: str) -> list[tuple[str, subprocess.Popen]]:
    procs: list[tuple[str, subprocess.Popen]] = []
    for spec in AGENT_SPECS:
        script = (
            f"import sys; sys.path.insert(0, {project_root!r}); "
            f"from src.agents.catalog import get_spec as _get, build_card as _build; "
            f"from {spec.module} import {spec.class_name} as _Agent; "
            f"_agent = _Agent(card=_build(_get({spec.name!r}))); "
            f"_agent.start(port={spec.port})"
        )
        p = subprocess.Popen([sys.executable, "-c", script], cwd=project_root)
        procs.append((f"{spec.name}:{spec.port}", p))
    return procs


async def wait_for_agents(
    agents: list[tuple[str, int]], timeout: float = 30.0
) -> list[str]:
    ready: list[str] = []
    async with httpx.AsyncClient(timeout=2.0) as client:
        for name, port in agents:
            url = f"http://localhost:{port}{CARD_PATH}"
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        ready.append(name)
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.3)
            else:
                print(f"  ⚠ {name} on port {port} did not respond within {timeout}s")
    return ready


async def async_main() -> None:
    project_root = _project_root

    print("Starting domain agents (ports 8001-8005)...")
    procs = start_agents(project_root)

    ready = await wait_for_agents([(s.name, s.port) for s in AGENT_SPECS])
    print(f"Agents ready: {len(ready)}/{len(AGENT_SPECS)}")

    print("Discovering agents via Agent Cards...")
    from src.orchestrator.registry import AgentRegistry

    registry = AgentRegistry()
    await registry.auto_discover([f"http://localhost:{s.port}" for s in AGENT_SPECS])

    from src.agents.coordinator import Coordinator
    from src.orchestrator.dispatcher import Dispatcher
    from src.orchestrator.router import Router
    from src.web.api import init_coordinator
    from src.web.app import create_app

    llm = _init_llm()
    print(f"  LLM provider: {type(llm).__name__ if llm else 'none (rule-based mode)'}")
    router = Router(registry=registry, llm=llm)
    dispatcher = Dispatcher(timeout=10.0, max_retries=1)
    coordinator = Coordinator(
        registry=registry, router=router, dispatcher=dispatcher, llm=llm
    )

    init_coordinator(registry, llm, coordinator=coordinator)
    app = create_app()

    shutting_down = False

    def shutdown() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print("\nShutting down...")
        for _, p in procs:
            p.terminate()
        for name, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            print(f"  Stopped {name}")

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info"))
    loop = asyncio.get_running_loop()

    def handle_signal() -> None:
        shutdown()
        server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    print("\nAll systems ready!")
    print("  Domain agents: ports 8001-8005 (A2A JSON-RPC, cards at /.well-known/agent-card.json)")
    print("  Coordinator:   in-process, served by the Web API")
    print("  Web UI:        http://localhost:8000")
    try:
        await server.serve()
    finally:
        shutdown()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
