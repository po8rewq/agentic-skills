import json
import subprocess
from pathlib import Path

from .base import Forge


class GitHubForge(Forge):
    def __init__(self, repo: Path, labels: list[str], reviewers: list[str]):
        self.repo, self.labels, self.reviewers = repo, labels, reviewers

    def _run(self, *args: str) -> str:
        result = subprocess.run(["gh", *args], cwd=self.repo, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    def load_issue(self, issue_id: str) -> str:
        data = json.loads(self._run("issue", "view", issue_id, "--json", "title,body,comments"))
        comments = "\n\n".join(c.get("body", "") for c in data.get("comments", []))
        return f"# {data['title']}\n\n{data.get('body', '')}\n\n{comments}".strip()

    def create_pr(self, title: str, body_path: Path, base: str) -> str:
        args = ["pr", "create", "--title", title, "--body-file", str(body_path), "--base", base]
        for label in self.labels:
            args += ["--label", label]
        for reviewer in self.reviewers:
            args += ["--reviewer", reviewer]
        return self._run(*args)

