from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Provider
from .claude import ClaudeProvider
from .codex import CodexProvider


def make_provider(name: str, config: dict[str, Any], repo: Path) -> Provider:
    available = config["providers"]["available"]
    if name not in available:
        raise ValueError(f"Unknown provider: {name}")
    command = available[name]["command"]
    if name == "claude-code":
        return ClaudeProvider(command, repo)
    if name == "codex":
        return CodexProvider(command, repo)
    raise ValueError(f"Unsupported provider implementation: {name}")
