from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent
RISK_LEVELS = ("low", "medium", "high", "critical")
CONFIG_FILENAMES = ("agentic.yaml", "agentic.yml")

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
    "context": {
        "dir": ".ai/context",
        "requirements": [],
        "architecture": [
            "repo-map.md",
            "module-boundaries.md",
            "test-commands.md",
            "coding-conventions.md",
            "dangerous-areas.md",
            "dependency-map.md",
            "ownership.md",
        ],
        "implementation": [
            "repo-map.md",
            "test-commands.md",
            "coding-conventions.md",
            "dangerous-areas.md",
        ],
        "review": [
            "repo-map.md",
            "module-boundaries.md",
            "test-commands.md",
            "coding-conventions.md",
            "dangerous-areas.md",
            "dependency-map.md",
        ],
    },
    "memory": {
        "dir": ".ai/memory",
        "requirements": [
            "decisions.md",
            "known-issues.md",
        ],
        "architecture": [
            "decisions.md",
            "preferred-patterns.md",
            "known-issues.md",
        ],
        "implementation": [
            "preferred-patterns.md",
            "lessons-learned.md",
            "known-issues.md",
        ],
        "review": [
            "recurring-review-comments.md",
            "known-issues.md",
            "decisions.md",
        ],
    },
    "vcs": {"type": "git", "require_clean_worktree": True, "branch_prefix": "ai/"},
    "forge": {"provider": "none", "create_pr": False, "labels": [], "reviewers": []},
    "gates": {
        "require_approval_after": ["requirements", "architecture"],
        "require_tests_before_review": True,
        "block_on_review_findings": ["blocking", "security"],
    },
    "risk_routing": {
        "default_level": "low",
        "implementation_models": {
            "low": "coding",
            "medium": "coding",
            "high": "best",
            "critical": "best",
        },
        "review_passes": {
            "low": ["correctness", "tests"],
            "medium": ["correctness", "architecture", "tests"],
            "high": ["correctness", "architecture", "security", "tests"],
            "critical": ["correctness", "architecture", "security", "tests", "migration_or_rollback"],
        },
        "require_human_approval": ["high", "critical"],
        "require_manual_merge": ["critical"],
        "keyword_fallback": {
            "level": "high",
            "high_risk_keywords": [
                "auth", "authorization", "billing", "payment", "migration",
                "encryption", "concurrency", "data loss",
            ],
        },
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


def resolve_config_path(repo: Path, path: Path | None = None) -> Path | None:
    if path is not None:
        return path
    for name in CONFIG_FILENAMES:
        candidate = repo / name
        if candidate.exists():
            return candidate
    return None


def load_config(repo: Path, path: Path | None = None) -> dict[str, Any]:
    config_path = resolve_config_path(repo, path)
    local = read_yaml(config_path) if config_path and config_path.exists() else {}
    config = deep_merge(DEFAULTS, local)
    config["project"]["name"] = config["project"]["name"] or repo.name
    for key in ("skills_dir", "pipelines_dir", "artifacts_dir"):
        p = Path(config["runtime"][key]).expanduser()
        config["runtime"][key] = str(p if p.is_absolute() else repo / p)
    context_dir = Path(config["context"]["dir"]).expanduser()
    config["context"]["dir"] = str(context_dir if context_dir.is_absolute() else repo / context_dir)
    memory_dir = Path(config["memory"]["dir"]).expanduser()
    config["memory"]["dir"] = str(memory_dir if memory_dir.is_absolute() else repo / memory_dir)
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
    risk_routing = config.get("risk_routing", {})
    if risk_routing.get("default_level") not in RISK_LEVELS:
        errors.append(f"risk_routing.default_level must be one of {', '.join(RISK_LEVELS)}")
    for key in ("implementation_models", "review_passes"):
        configured = risk_routing.get(key, {})
        missing = [level for level in RISK_LEVELS if level not in configured]
        if missing:
            errors.append(f"risk_routing.{key} is missing levels: {', '.join(missing)}")
    for key in ("require_human_approval", "require_manual_merge"):
        invalid = [level for level in risk_routing.get(key, []) if level not in RISK_LEVELS]
        if invalid:
            errors.append(f"risk_routing.{key} contains invalid levels: {', '.join(invalid)}")
    fallback = risk_routing.get("keyword_fallback", {})
    if fallback.get("level") not in RISK_LEVELS:
        errors.append(f"risk_routing.keyword_fallback.level must be one of {', '.join(RISK_LEVELS)}")
    for stage in ("requirements", "architecture", "implementation", "review"):
        if not isinstance(config.get("context", {}).get(stage, []), list):
            errors.append(f"context.{stage} must be a list of file names")
        if not isinstance(config.get("memory", {}).get(stage, []), list):
            errors.append(f"memory.{stage} must be a list of file names")
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


def resolve_alias(config: dict[str, Any], configured: str) -> str:
    return config["models"].get("aliases", {}).get(configured, configured)


def keyword_risk_level(task: str, config: dict[str, Any]) -> str | None:
    routing = config.get("risk_routing", {})
    fallback = routing.get("keyword_fallback", {})
    keywords = fallback.get("high_risk_keywords", routing.get("high_risk_keywords", []))
    if any(word.casefold() in task.casefold() for word in keywords):
        return fallback.get("level", "high")
    return None


def review_passes_for_risk(config: dict[str, Any], risk_level: str) -> list[str]:
    return list(config["risk_routing"]["review_passes"][risk_level])


def resolve_model(
    stage: str,
    task: str,
    config: dict[str, Any],
    overrides: dict[str, str],
    risk_level: str | None = None,
) -> str:
    if stage in overrides:
        return resolve_alias(config, overrides[stage])
    configured = config["models"]["by_stage"].get(stage, "coding")
    if risk_level and risk_level not in RISK_LEVELS:
        raise ValueError(f"Invalid risk level: {risk_level}")
    effective_risk = risk_level or keyword_risk_level(task, config)
    if stage == "implementation" and effective_risk:
        configured = config["risk_routing"]["implementation_models"][effective_risk]
    elif effective_risk in {"high", "critical"} and stage in {"architecture", "review"}:
        configured = config["risk_routing"]["implementation_models"][effective_risk]
    return resolve_alias(config, configured)
