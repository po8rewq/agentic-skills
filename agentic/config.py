from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "project": {"name": None, "default_branch": "main"},
    "runtime": {
        "pipeline": "default",
        "skills_dir": str(ROOT / "skills"),
        "pipelines_dir": str(ROOT / "pipelines"),
        "artifacts_dir": ".ai/runs",
    },
    "providers": {
        "default": "claude-code",
        "available": {
            "claude-code": {"command": "claude"},
            "codex": {"command": "codex exec"},
        },
    },
    "models": {
        "aliases": {"cheap": "haiku", "coding": "codex", "best": "opus"},
        "by_stage": {
            "requirements": "cheap",
            "architecture": "best",
            "implementation": "coding",
            "review": "best",
            "fix-review": "coding",
            "docs": "cheap",
        },
    },
    "commands": {},
    "vcs": {"type": "git", "require_clean_worktree": True, "branch_prefix": "ai/"},
    "forge": {"provider": "none", "create_pr": False, "labels": [], "reviewers": []},
    "gates": {
        "require_approval_after": ["requirements", "architecture"],
        "require_tests_before_review": True,
        "block_on_review_findings": ["blocking", "security"],
    },
    "risk_routing": {
        "high_risk_keywords": [
            "auth", "authorization", "billing", "payment", "migration",
            "encryption", "concurrency", "data loss",
        ],
        "escalate_to": "best",
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return value


def load_config(repo: Path, path: Path | None = None) -> dict[str, Any]:
    config_path = path or repo / "agentic.yaml"
    local = read_yaml(config_path) if config_path.exists() else {}
    config = deep_merge(DEFAULTS, local)
    config["project"]["name"] = config["project"]["name"] or repo.name
    for key in ("skills_dir", "pipelines_dir", "artifacts_dir"):
        p = Path(config["runtime"][key]).expanduser()
        config["runtime"][key] = str(p if p.is_absolute() else repo / p)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    errors: list[str] = []
    providers = config.get("providers", {}).get("available", {})
    default_provider = config.get("providers", {}).get("default")
    if default_provider not in providers:
        errors.append(f"providers.default '{default_provider}' is not declared in providers.available")
    if config.get("vcs", {}).get("type") != "git":
        errors.append("only vcs.type=git is currently supported")
    if config.get("forge", {}).get("provider") not in {"github", "gitea", "gitlab", "none"}:
        errors.append("forge.provider must be github, gitea, gitlab, or none")
    for stage, alias in config.get("models", {}).get("by_stage", {}).items():
        aliases = config.get("models", {}).get("aliases", {})
        if alias not in aliases and not isinstance(alias, str):
            errors.append(f"models.by_stage.{stage} must be a model name or alias")
    if errors:
        raise ValueError("Configuration errors:\n- " + "\n- ".join(errors))


def load_pipeline(config: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    selected = name or config["runtime"]["pipeline"]
    path = Path(config["runtime"]["pipelines_dir"]) / f"{selected}.yaml"
    if not path.exists():
        raise ValueError(f"Pipeline not found: {path}")
    pipeline = read_yaml(path)
    if not isinstance(pipeline.get("steps"), list):
        raise ValueError(f"Pipeline {path} must contain a steps list")
    return pipeline


def resolve_model(stage: str, task: str, config: dict[str, Any], overrides: dict[str, str]) -> str:
    configured = overrides.get(stage, config["models"]["by_stage"].get(stage, "coding"))
    keywords = config["risk_routing"].get("high_risk_keywords", [])
    high_risk = any(word.casefold() in task.casefold() for word in keywords)
    if high_risk and stage in {"architecture", "implementation", "review"}:
        configured = config["risk_routing"]["escalate_to"]
    return config["models"].get("aliases", {}).get(configured, configured)

