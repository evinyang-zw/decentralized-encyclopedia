"""Deterministic cross-domain evaluation harness for decentralized-encyclopedia.

Entry point::

    python -m eval.runner            # live run, writes reports/eval-latest.{json,md}

Modules:
    client.py   in-process ASGI runtime + 4 orchestration configs
    metrics.py  pure metric computation (no LLM judge)
    runner.py   CLI, orchestration and report rendering
"""
from __future__ import annotations

__all__ = ["client", "metrics", "runner"]
__version__ = "1.0.0"
