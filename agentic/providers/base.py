from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProviderResult:
    output: str
    command: list[str]
    returncode: int
    stderr: str = ""


class Provider:
    def __init__(self, command: str, repo: Path):
        self.command = command
        self.repo = repo

    def run(self, prompt: str, model: str, stage: str) -> ProviderResult:
        raise NotImplementedError

    def _execute(self, argv: list[str], prompt: str) -> ProviderResult:
        try:
            completed = subprocess.run(
                argv, input=prompt, text=True, cwd=self.repo,
                capture_output=True, check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Provider executable not found: {argv[0]}") from exc
        if completed.returncode:
            raise RuntimeError(
                f"Provider failed ({completed.returncode}): {' '.join(argv)}\n{completed.stderr.strip()}"
            )
        return ProviderResult(completed.stdout, argv, completed.returncode, completed.stderr)

