"""一键启动所有 Agent 进程。"""
import subprocess
import sys
import time
import signal
import os


def _make_agent_script(agent_class: str, port: int) -> str:
    """Generate inline Python script to start an agent."""
    return (
        f"import asyncio; "
        f"from src.protocol.models import AgentCard, Skill; "
        f"from src.agents.{agent_class.split('.')[-1].lower()} import {agent_class.split('.')[-1]}; "
        f"card = AgentCard(name='{agent_class}', description='', version='1.0.0', "
        f"skills=[], endpoint='http://localhost:{port}'); "
        f"agent = {agent_class}(card=card); "
        f"agent.start(port={port})"
    )


AGENT_SCRIPTS = {
    "WikipediaAgent": ("src.agents.wikipedia", "WikipediaAgent", 8001),
    "ArxivAgent": ("src.agents.arxiv", "ArxivAgent", 8002),
    "GithubAgent": ("src.agents.github", "GithubAgent", 8003),
    "WeatherAgent": ("src.agents.weather", "WeatherAgent", 8004),
    "WikidataAgent": ("src.agents.wikidata", "WikidataAgent", 8005),
}


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    procs = []

    for name, (module, cls_name, port) in AGENT_SCRIPTS.items():
        print(f"Starting {name} on port {port}...")
        script = (
            f"import sys; sys.path.insert(0, '{project_root}'); "
            f"from {module} import {cls_name}; "
            f"from src.protocol.models import AgentCard; "
            f"card = AgentCard(name='{name}', description='', version='1.0.0', "
            f"skills=[], endpoint='http://localhost:{port}'); "
            f"agent = {cls_name}(card=card); "
            f"agent.start(port={port})"
        )
        p = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=project_root,
        )
        procs.append((name, p))
        time.sleep(0.5)

    print(f"\nAll {len(procs)} agents started!")
    print("Agents running on ports 8001-8005")

    def shutdown(sig, frame):
        print("\nShutting down...")
        for name, p in procs:
            p.terminate()
            print(f"  Stopped {name}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        for _, p in procs:
            p.wait()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
