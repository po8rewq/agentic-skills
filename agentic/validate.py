from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config, load_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate agentic.yaml and its selected pipeline")
    parser.add_argument("path", nargs="?", type=Path, default=Path("agentic.yaml"))
    args = parser.parse_args(argv)
    config = load_config(Path.cwd(), args.path)
    load_pipeline(config)
    print(f"Valid: {args.path}")
    return 0
