from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Forge
from .gitea import GiteaForge
from .github import GitHubForge


def make_forge(config: dict[str, Any], repo: Path) -> Forge | None:
    forge = config["forge"]
    common = (repo, forge.get("labels", []), forge.get("reviewers", []))
    if forge["provider"] == "github":
        return GitHubForge(*common)
    if forge["provider"] == "gitea":
        return GiteaForge(*common)
    if forge["provider"] in {"none", "gitlab"}:
        return None
    raise ValueError(f"Unknown forge: {forge['provider']}")
