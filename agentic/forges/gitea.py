import json
import re
import subprocess
from pathlib import Path

from .base import Forge


class GiteaForge(Forge):
    """Gitea integration through the `tea` CLI."""

    def __init__(self, repo: Path, labels: list[str], reviewers: list[str]):
        self.repo, self.labels, self.reviewers = repo, labels, reviewers

    def _git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    def _run(self, *args: str) -> str:
        result = subprocess.run(["tea", *args], cwd=self.repo, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    def _repo_slug(self) -> str:
        remote = self._git("remote", "get-url", "origin")
        patterns = (
            r"^[a-z]+://(?:[^@/]+@)?[^/]+/(?P<slug>.+?)(?:\.git)?$",
            r"^(?:[^@]+@)?[^:]+:(?P<slug>.+?)(?:\.git)?$",
        )
        for pattern in patterns:
            match = re.match(pattern, remote)
            if match:
                return match.group("slug")
        raise RuntimeError(f"Could not determine Gitea repository slug from origin remote: {remote}")

    def _current_branch(self) -> str:
        return self._git("branch", "--show-current")

    def _ensure_branch_is_pushed(self, branch: str) -> None:
        remote_branch = self._git("ls-remote", "--heads", "origin", branch)
        if not remote_branch:
            raise RuntimeError(
                f"Current branch '{branch}' is not pushed to origin. "
                "Push it before creating a Gitea pull request; the pipeline does not auto-commit or auto-push changes."
            )

    def load_issue(self, issue_id: str) -> str:
        raw = self._run("issues", issue_id, "--repo", self._repo_slug(), "--output", "json")
        data = json.loads(raw)
        return f"# {data['title']}\n\n{data.get('body', '')}".strip()

    def create_pr(self, title: str, body_path: Path, base: str) -> str:
        branch = self._current_branch()
        self._ensure_branch_is_pushed(branch)
        return self._run(
            "pulls",
            "create",
            "--repo",
            self._repo_slug(),
            "--head",
            branch,
            "--title",
            title,
            "--description",
            body_path.read_text(),
            "--base",
            base,
        )
