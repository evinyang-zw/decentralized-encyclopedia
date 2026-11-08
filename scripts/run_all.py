"""只启动 5 个 domain agents（不含 Coordinator / Web Server）。

完整系统请用 `python scripts/start.py`。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.agents.catalog import AGENT_SPECS


def main() -> None:
    procs: list[tuple[str, subprocess.Popen]] = []
    for spec in AGENT_SPECS:
        print(f"Starting {spec.name} on port {spec.port}...")
        script = (
            f"import sys; sys.path.insert(0, {_project_root!r}); "
            f"from src.agents.catalog import get_spec as _get, build_card as _build; "
            f"from {spec.module} import {spec.class_name} as _Agent; "
            f"_agent = _Agent(card=_build(_get({spec.name!r}))); "
            f"_agent.start(port={spec.port})"
        )
        p = subprocess.Popen([sys.executable, "-c", script], cwd=_project_root)
        procs.append((spec.name, p))
        time.sleep(0.5)

    print(f"\nAll {len(procs)} agents started (ports 8001-8005)")
    print("Agent Cards: http://localhost:<port>/.well-known/agent-card.json")
    print("Note: Coordinator/Web are NOT started by this script — use scripts/start.py")

    def shutdown(sig, frame) -> None:  # type: ignore[no-untyped-def]
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
