from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .config import ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install shared skills into a project")
    parser.add_argument("destination", nargs="?", type=Path, default=Path(".ai/skills"))
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "skills",
        help="skills directory to copy (default: skills from the installed agentic-skills package)",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    source = args.source.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source skills directory does not exist: {source}")
    if destination.exists():
        if not args.force:
            parser.error(f"destination exists: {destination} (use --force to replace it)")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    print(f"Copied skills from {source}\nto {destination}")
    return 0
