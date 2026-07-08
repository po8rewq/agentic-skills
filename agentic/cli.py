from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CONFIG_FILENAMES, load_config, load_pipeline, resolve_config_path
from .forges import make_forge
from .pipeline import PipelineRunner, RunOptions


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run an auditable agentic coding pipeline")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--task", help="Inline task description")
    source.add_argument("--issue", help="Load a task from the configured forge")
    p.add_argument("--pipeline", help="Pipeline variant")
    p.add_argument("--stage", help="Run only one stage")
    p.add_argument("--resume", type=Path, help="Resume an existing run directory")
    p.add_argument("--model", action="append", default=[], metavar="STAGE=MODEL")
    p.add_argument("--skip-approval", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--config", type=Path, help="Configuration file (default: agentic.yaml)")
    return p


def parse_models(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --model '{value}'; expected STAGE=MODEL")
        stage, model = value.split("=", 1)
        result[stage] = model
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = Path.cwd().resolve()
    try:
        config_path = resolve_config_path(repo, args.config)
        if args.config is None and config_path is None:
            print(
                f"warning: no project config found; using built-in defaults "
                f"(searched {', '.join(CONFIG_FILENAMES)})",
                file=sys.stderr,
            )
        config = load_config(repo, args.config)
        task = args.task or ""
        if args.issue:
            forge = make_forge(config, repo)
            if forge is None:
                raise ValueError("--issue requires a configured GitHub or Gitea forge")
            task = forge.load_issue(args.issue)
        if not task and not args.resume:
            raise ValueError("one of --task, --issue, or --resume is required")
        pipeline_name = args.pipeline or config["runtime"]["pipeline"]
        pipeline = load_pipeline(config, pipeline_name)
        options = RunOptions(
            task=task, pipeline_name=pipeline_name, stage=args.stage, resume=args.resume,
            model_overrides=parse_models(args.model), skip_approval=args.skip_approval,
            dry_run=args.dry_run, verbose=args.verbose,
        )
        run_dir = PipelineRunner(repo, config, pipeline, options).run()
        print(f"Run artifacts: {run_dir}")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
