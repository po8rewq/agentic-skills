import json
import subprocess
from pathlib import Path

from .base import Forge


class GiteaForge(Forge):
    """Gitea integration through the `tea` CLI."""

    def __init__(self, repo: Path, labels: list[str], reviewers: list[str]):
        self.repo, self.labels, self.reviewers = repo, labels, reviewers

    def _run(self, *args: str) -> str:
        result = subprocess.run(["tea", *args], cwd=self.repo, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    def load_issue(self, issue_id: str) -> str:
        raw = self._run("issues", issue_id, "--output", "json")
        data = json.loads(raw)
        return f"# {data['title']}\n\n{data.get('body', '')}".strip()

    def create_pr(self, title: str, body_path: Path, base: str) -> str:
        return self._run("pulls", "create", "--title", title, "--description", body_path.read_text(), "--base", base)

