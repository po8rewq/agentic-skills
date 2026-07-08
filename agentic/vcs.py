from __future__ import annotations

import subprocess
from pathlib import Path


class Git:
    def __init__(self, repo: Path):
        self.repo = repo

    def run(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(["git", *args], cwd=self.repo, text=True, capture_output=True)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    def is_repo(self) -> bool:
        return self.run("rev-parse", "--is-inside-work-tree", check=False) == "true"

    def ensure_clean(self) -> None:
        if self.run("status", "--porcelain"):
            raise RuntimeError("Worktree is not clean; commit or stash changes before starting")

    def create_branch(self, branch: str) -> None:
        self.run("switch", "-c", branch)

    def diff(self) -> str:
        return self.run("diff", "--no-ext-diff", "HEAD", check=False)

    def current_branch(self) -> str:
        return self.run("branch", "--show-current")

    def stage_all_except(self, excluded_paths: list[Path] | None = None) -> None:
        self.run("add", "-A")
        for path in excluded_paths or []:
            try:
                relative = path.relative_to(self.repo)
            except ValueError:
                continue
            self.run("reset", "HEAD", "--", str(relative), check=False)

    def has_staged_changes(self) -> bool:
        return bool(self.run("diff", "--cached", "--name-only"))

    def commit(self, message: str) -> None:
        self.run("commit", "-m", message)

    def push_current_branch(self, remote: str = "origin") -> None:
        branch = self.current_branch()
        self.run("push", "-u", remote, branch)
