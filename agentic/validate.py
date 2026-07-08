from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CONFIG_FILENAMES, load_config, load_pipeline, resolve_config_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate agentic.yaml or agentic.yml and its selected pipeline")
    parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args(argv)
    repo = Path.cwd()
    config_path = resolve_config_path(repo, args.path)
    if args.path is None and config_path is None:
        print(
            f"warning: no project config found; using built-in defaults "
            f"(searched {', '.join(CONFIG_FILENAMES)})",
            file=sys.stderr,
        )
    config = load_config(repo, args.path)
    load_pipeline(config)
    print(f"Valid: {config_path or 'built-in defaults'}")
    return 0
