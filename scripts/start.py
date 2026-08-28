"""一键启动整个系统：5 个 domain agents + Coordinator + Web Server。"""
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

import httpx


AGENT_SCRIPTS: list[tuple[str, str, int]] = [
    ("src.agents.wikipedia", "WikipediaAgent", 8001),
    ("src.agents.arxiv", "ArxivAgent", 8002),
    ("src.agents.github", "GithubAgent", 8003),
    ("src.agents.weather", "WeatherAgent", 8004),
    ("src.agents.wikidata", "WikidataAgent", 8005),
]


def start_agents(project_root: str) -> list[tuple[str, subprocess.Popen]]:
    procs: list[tuple[str, subprocess.Popen]] = []
    for module, cls_name, port in AGENT_SCRIPTS:
        script = (
            f"import sys; sys.path.insert(0, '{project_root}'); "
            f"from {module} import {cls_name}; "
            f"from src.protocol.models import AgentCard; "
            f"card = AgentCard(name='{cls_name}', description='', version='1.0.0', "
            f"skills=[], endpoint='http://localhost:{port}'); "
            f"agent = {cls_name}(card=card); "
            f"agent.start(port={port})"
        )
        p = subprocess.Popen([sys.executable, "-c", script], cwd=project_root)
        procs.append((f"{cls_name}:{port}", p))
    return procs


async def wait_for_agents(ports: list[int], timeout: float = 30.0) -> None:
    async with httpx.AsyncClient(timeout=2.0) as client:
        deadline = time.monotonic() + timeout
        for port in ports:
            url = f"http://localhost:{port}/.well-known/agent.json"
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.3)
            else:
                print(f"  ⚠ Agent on port {port} did not respond within {timeout}s")


async def async_main() -> None:
    project_root = _project_root

    print("Starting domain agents (ports 8001-8005)...")
    procs = start_agents(project_root)

    ports = [p for _, _, p in AGENT_SCRIPTS]
    print("Waiting for agents to be ready...")
    await wait_for_agents(ports)

    print("Discovering agents...")
    from src.orchestrator.registry import AgentRegistry
    registry = AgentRegistry()
    await registry.auto_discover([f"http://localhost:{p}" for p in ports])

    from src.orchestrator.router import Router
    from src.orchestrator.dispatcher import Dispatcher
    from src.agents.coordinator import Coordinator
    from src.web.api import init_coordinator
    from src.web.app import create_app

    llm = None
    router = Router(registry=registry, llm=llm)
    dispatcher = Dispatcher(timeout=10.0, max_retries=1)
    _coordinator = Coordinator(
        registry=registry, router=router, dispatcher=dispatcher, llm=llm,
    )

    init_coordinator(registry, llm)
    app = create_app()

    shutting_down = False

    def shutdown() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print("\nShutting down...")
        for name, p in procs:
            p.terminate()
        for name, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            print(f"  Stopped {name}")

    loop = asyncio.get_running_loop()
    def handle_signal() -> None:
        shutdown()
        server.should_exit = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    import uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    print("\nAll systems ready!")
    print("  Domain agents: ports 8001-8005")
    print("  Coordinator:   port 8010")
    print("  Web UI:        http://localhost:8000")
    try:
        await server.serve()
    finally:
        shutdown()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
