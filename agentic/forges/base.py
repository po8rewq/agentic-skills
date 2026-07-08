from __future__ import annotations

from pathlib import Path


class Forge:
    def load_issue(self, issue_id: str) -> str:
        raise NotImplementedError

    def create_pr(self, title: str, body_path: Path, base: str) -> str:
        raise NotImplementedError

