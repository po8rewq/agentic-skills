from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .config import ROOT


def copy_tree(source: Path, destination: Path, force: bool, parser: argparse.ArgumentParser, label: str) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"{label} source directory does not exist: {source}")
    if destination.exists():
        if not force:
            parser.error(f"{label} destination exists: {destination} (use --force to replace it)")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    print(f"Copied {label} from {source}\nto {destination}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install shared skills into a project")
    parser.add_argument("destination", nargs="?", type=Path, default=Path(".ai/skills"))
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "skills",
        help="skills directory to copy (default: skills from the installed agentic-skills package)",
    )
    parser.add_argument("--with-context", action="store_true", help="also install repo-context templates")
    parser.add_argument("--with-memory", action="store_true", help="also install repo-memory templates")
    parser.add_argument(
        "--context-source",
        type=Path,
        default=ROOT / "templates" / "context",
        help="context template directory to copy",
    )
    parser.add_argument(
        "--memory-source",
        type=Path,
        default=ROOT / "templates" / "memory",
        help="memory template directory to copy",
    )
    parser.add_argument("--context-destination", type=Path, default=Path(".ai/context"))
    parser.add_argument("--memory-destination", type=Path, default=Path(".ai/memory"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    copy_tree(args.source, args.destination, args.force, parser, "skills")
    if args.with_context:
        copy_tree(args.context_source, args.context_destination, args.force, parser, "context templates")
    if args.with_memory:
        copy_tree(args.memory_source, args.memory_destination, args.force, parser, "memory templates")
    return 0
