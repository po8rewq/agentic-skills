from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import RISK_LEVELS, keyword_risk_level, resolve_model, review_passes_for_risk
from .forges import make_forge
from .providers import make_provider
from .vcs import Git


def slugify(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return (slug[:limit].rstrip("-") or "task")


@dataclass
class RunOptions:
    task: str
    pipeline_name: str
    stage: str | None = None
    resume: Path | None = None
    model_overrides: dict[str, str] | None = None
    skip_approval: bool = False
    dry_run: bool = False
    verbose: bool = False


class PipelineRunner:
    def __init__(self, repo: Path, config: dict[str, Any], pipeline: dict[str, Any], options: RunOptions):
        self.repo, self.config, self.pipeline, self.options = repo, config, pipeline, options
        self.git = Git(repo)
        self.run_dir = options.resume or self._new_run_dir()
        self.logs_dir = self.run_dir / "logs"
        self.state_path = self.run_dir / "state.json"
        self.state: dict[str, Any] = {"completed": [], "branch": None, "status": "running"}
        self.test_results = ""

    def _new_run_dir(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        return Path(self.config["runtime"]["artifacts_dir"]) / f"{stamp}-{slugify(self.options.task)}"

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    def _load_task_from_artifacts(self) -> str:
        state_task = self.state.get("task")
        if isinstance(state_task, str) and state_task.strip():
            return state_task.strip()
        task_path = self.run_dir / "task.md"
        if task_path.exists():
            return task_path.read_text(encoding="utf-8").removeprefix("# Task\n\n").strip()
        return ""

    def _task_title(self) -> str:
        task = (self.options.task or self._load_task_from_artifacts()).strip()
        if task:
            return task.splitlines()[0][:120]
        return f"AI update: {self.run_id[:120]}"

    def _prepare_git_run(self) -> None:
        if not self.git.is_repo():
            return
        if self.config["vcs"].get("require_clean_worktree", True):
            self.git.ensure_clean()
        branch = self.config["vcs"].get("branch_prefix", "ai/") + slugify(self.options.task)
        self.git.create_branch(branch)
        self.state["branch"] = branch

    def prepare(self) -> None:
        if self.options.resume:
            if not self.run_dir.exists():
                raise ValueError(f"Resume directory does not exist: {self.run_dir}")
            if self.state_path.exists():
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not self.options.task:
                self.options.task = self._load_task_from_artifacts()
            self.logs_dir.mkdir(exist_ok=True)
            return
        if self.options.dry_run:
            print(f"[dry-run] would create {self.run_dir}")
            if self.git.is_repo():
                branch = self.config["vcs"].get("branch_prefix", "ai/") + slugify(self.options.task)
                self.state["branch"] = branch
                print(f"[dry-run] would create branch {branch}")
            return
        if self.git.is_repo():
            self._prepare_git_run()
        self.logs_dir.mkdir(parents=True, exist_ok=False)
        (self.run_dir / "task.md").write_text(f"# Task\n\n{self.options.task}\n", encoding="utf-8")
        (self.run_dir / "config.snapshot.yaml").write_text(
            yaml.safe_dump(self.config, sort_keys=False), encoding="utf-8"
        )
        self.state["task"] = self.options.task
        self._save_state()

    def _artifact(self, name: str) -> str:
        path = self.run_dir / name
        return path.read_text(encoding="utf-8") if path.exists() else "(not yet available)"

    def _repository_instructions(self) -> str:
        instructions = []
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = self.repo / name
            if path.exists():
                instructions.append(f"## {name}\n\n{path.read_text(encoding='utf-8')}")
        return "\n\n".join(instructions) or "No repository instruction file was found."

    def _configured_context_files(self, stage: str) -> list[Path]:
        context_dir = Path(self.config["context"]["dir"])
        return [context_dir / name for name in self.config.get("context", {}).get(stage, [])]

    def _configured_memory_files(self, stage: str) -> list[Path]:
        memory_dir = Path(self.config["memory"]["dir"])
        return [memory_dir / name for name in self.config.get("memory", {}).get(stage, [])]

    def _repo_context(self, stage: str) -> str:
        sections = []
        for path in self._configured_context_files(stage):
            if path.exists():
                try:
                    label = path.relative_to(self.repo)
                except ValueError:
                    label = path
                sections.append(f"## {label}\n\n{path.read_text(encoding='utf-8')}")
        return "\n\n".join(sections) or "No configured repo context file was found for this stage."

    def _repo_memory(self, stage: str) -> str:
        sections = []
        for path in self._configured_memory_files(stage):
            if path.exists():
                try:
                    label = path.relative_to(self.repo)
                except ValueError:
                    label = path
                sections.append(f"## {label}\n\n{path.read_text(encoding='utf-8')}")
        return "\n\n".join(sections) or "No configured repo memory file was found for this stage."

    def _prompt(self, step: dict[str, Any], skill_text: str) -> str:
        sections = [
            "# Pipeline task", self.options.task,
            "# Skill instructions", skill_text,
            "# Repository instructions", self._repository_instructions(),
            "# Repository context", self._repo_context(step["id"]),
            "# Repository memory", self._repo_memory(step["id"]),
        ]
        if step["id"] == "review":
            review_passes = self._selected_review_passes()
            sections += [
                "# Required review passes",
                "\n".join(f"- {name}" for name in review_passes),
            ]
        for item in step.get("inputs", []):
            if item == "repo_context":
                continue
            if item == "git_diff":
                value = self.git.diff() if self.git.is_repo() else "Not a git repository."
            elif item == "test_results":
                value = self.test_results or self._artifact("test-results.md")
            else:
                value = self._artifact(item)
            sections += [f"# Input: {item}", value]
        if step["id"] in {"implementation", "fix-review"}:
            sections += [
                "# Execution requirement",
                "Work directly in the repository to implement the requested changes. "
                "Afterwards, return a concise Markdown summary of changes and tests.",
            ]
        else:
            sections += ["# Output requirement", "Return only the requested Markdown artifact."]
        return "\n\n".join(sections) + "\n"

    def _run_skill(self, step: dict[str, Any]) -> None:
        stage = step["id"]
        if stage == "review" and self.config["gates"].get("require_tests_before_review"):
            if not self.test_results and not (self.run_dir / "test-results.md").exists():
                raise RuntimeError("Review requires check results, but test-results.md does not exist")
        skill_path = Path(self.config["runtime"]["skills_dir"]) / step["skill"] / "SKILL.md"
        if not skill_path.exists():
            raise ValueError(f"Skill not found: {skill_path}")
        prompt = self._prompt(step, skill_path.read_text(encoding="utf-8"))
        output_path = self.run_dir / step["output"]
        prompt_path = self.logs_dir / f"{stage}.prompt.md"
        output_log = self.logs_dir / f"{stage}.output.md"
        model = self._resolve_stage_model(stage)
        self._record_stage_routing(stage, model)
        provider_name = step.get("provider", self.config["providers"]["default"])
        print(f"[{stage}] {provider_name} / {model} -> {output_path}")
        if self.options.dry_run:
            return
        prompt_path.write_text(prompt, encoding="utf-8")
        result = make_provider(provider_name, self.config, self.repo).run(prompt, model, stage)
        output_path.write_text(result.output.rstrip() + "\n", encoding="utf-8")
        self._validate_output(skill_path.parent, result.output)
        gate_approval_requested = self._enforce_stage_gate(stage, output_path, step)
        if stage == "architecture":
            self._record_stage_routing(stage, model)
        output_log.write_text(result.output.rstrip() + "\n", encoding="utf-8")
        (self.logs_dir / f"{stage}.command.txt").write_text(shlex.join(result.command) + "\n", encoding="utf-8")
        if not gate_approval_requested and (
            step.get("approval") or stage in self.config["gates"].get("require_approval_after", [])
        ):
            self._approve(stage, output_path, step)
        if stage == "fix-review" and self._review_has_security_blocking_findings():
            self._approve(stage, output_path, step)

    def _resolve_stage_model(self, stage: str) -> str:
        risk_level = self._current_risk_level() if stage in {"architecture", "implementation", "review"} else None
        return resolve_model(stage, self.options.task, self.config, self.options.model_overrides or {}, risk_level)

    def _record_stage_routing(self, stage: str, model: str) -> None:
        routing = self.state.setdefault("routing", {})
        routing.setdefault("stages", {})[stage] = {"model": model}
        risk_level = self._current_risk_level()
        routing["risk_level"] = risk_level
        routing["review_passes"] = self._selected_review_passes(risk_level)
        routing["require_manual_merge"] = risk_level in self.config["risk_routing"].get("require_manual_merge", [])
        if stage == "implementation":
            routing["implementation_model"] = model

    def _approve(self, stage: str, output_path: Path, step: dict[str, Any]) -> None:
        if self.options.skip_approval:
            return
        while True:
            answer = input(f"Approve {stage} at {output_path}? [y/N/r/e] ").strip().casefold()
            if answer == "y":
                return
            if answer == "r":
                self._run_skill({**step, "approval": False})
                continue
            if answer == "e":
                editor = shlex.split(self.config.get("editor") or os.environ.get("EDITOR", "vi"))
                subprocess.run(editor + [str(output_path)], check=False)
                continue
            self.state["status"] = "stopped"
            self._save_state()
            raise RuntimeError(f"Pipeline stopped at approval gate: {stage}")

    @staticmethod
    def _validate_output(skill_dir: Path, output: str) -> None:
        schema_path = skill_dir / "output-schema.yaml"
        if not schema_path.exists():
            return
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
        metadata = PipelineRunner._extract_agentic_yaml(output) if schema.get("required_metadata") else {}
        missing_metadata = [name for name in schema.get("required_metadata", []) if not PipelineRunner._metadata_has(metadata, name)]
        if missing_metadata:
            raise RuntimeError(f"Provider output is missing required metadata: {', '.join(missing_metadata)}")
        invalid_enums = []
        for name, allowed in schema.get("metadata_enums", {}).items():
            value = PipelineRunner._metadata_get(metadata, name)
            if value is not None and value not in allowed:
                invalid_enums.append(f"{name}={value!r} (expected one of {', '.join(map(str, allowed))})")
        if invalid_enums:
            raise RuntimeError(f"Provider output has invalid metadata values: {'; '.join(invalid_enums)}")
        headings: set[str] = set()
        for match in re.finditer(r"^(?:#{1,6}\s+(.+?)|\*\*(.+?)\*\*)\s*$", output, re.M):
            title = next((group for group in match.groups() if group), "").strip().casefold()
            if title:
                headings.add(title)
        missing = [name for name in schema.get("required_sections", []) if name.casefold() not in headings]
        if missing:
            raise RuntimeError(f"Provider output is missing required sections: {', '.join(missing)}")

    @staticmethod
    def _extract_agentic_yaml(output: str) -> dict[str, Any]:
        match = re.search(r"```ya?ml\s+agentic\s*\n(.*?)\n```", output, re.S | re.I)
        if not match:
            raise RuntimeError("Provider output is missing required ```yaml agentic``` metadata block")
        try:
            value = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Provider output contains invalid agentic metadata YAML: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Provider output agentic metadata must be a YAML mapping")
        return value

    @staticmethod
    def _metadata_get(metadata: dict[str, Any], dotted_key: str) -> Any:
        value: Any = metadata
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    @staticmethod
    def _metadata_has(metadata: dict[str, Any], dotted_key: str) -> bool:
        value: Any = metadata
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        return True

    def _load_stage_metadata(self, artifact_name: str) -> dict[str, Any]:
        return self._extract_agentic_yaml(self._artifact(artifact_name))

    def _record_stage_metadata(self, stage: str, metadata: dict[str, Any]) -> None:
        stage_state: dict[str, Any] = self.state.setdefault("stages", {}).get(stage, {})
        if "status" in metadata:
            stage_state["status"] = metadata["status"]
        if "confidence" in metadata:
            stage_state["confidence"] = metadata["confidence"]
        if "risk" in metadata:
            stage_state["risk"] = metadata["risk"]
            self.state["risk"] = metadata["risk"]
        self.state.setdefault("stages", {})[stage] = stage_state

    def _enforce_stage_gate(self, stage: str, output_path: Path, step: dict[str, Any]) -> bool:
        if stage not in {"requirements", "architecture"}:
            return False
        metadata = self._load_stage_metadata(step["output"])
        self._record_stage_metadata(stage, metadata)
        status = str(metadata.get("status", "")).casefold()
        if status not in {"ready", "risky", "blocked"}:
            raise RuntimeError(f"{stage} gate metadata has invalid status: {metadata.get('status')!r}")
        if status == "blocked":
            self.state["status"] = "stopped"
            self._save_state()
            raise RuntimeError(f"{stage} gate blocked implementation; see {output_path}")
        risk_level = str(self._metadata_get(metadata, "risk.level") or "").casefold()
        if risk_level and risk_level not in RISK_LEVELS:
            raise RuntimeError(f"{stage} gate metadata has invalid risk level: {risk_level!r}")
        approval_levels = self.config["risk_routing"].get("require_human_approval", [])
        approval_required = status == "risky" or risk_level in approval_levels
        if approval_required:
            self._approve(stage, output_path, step)
            return True
        return False

    def _current_risk_level(self) -> str:
        state_level = self._metadata_get(self.state, "risk.level")
        if state_level:
            level = str(state_level).casefold()
            if level in RISK_LEVELS:
                return level
        design_path = self.run_dir / "design.md"
        if design_path.exists():
            try:
                metadata = self._extract_agentic_yaml(design_path.read_text(encoding="utf-8"))
            except RuntimeError:
                metadata = {}
            artifact_level = self._metadata_get(metadata, "risk.level")
            if artifact_level:
                level = str(artifact_level).casefold()
                if level in RISK_LEVELS:
                    self.state["risk"] = metadata.get("risk", {"level": level})
                    return level
        fallback = keyword_risk_level(self.options.task, self.config)
        return fallback or self.config["risk_routing"]["default_level"]

    def _selected_review_passes(self, risk_level: str | None = None) -> list[str]:
        return review_passes_for_risk(self.config, risk_level or self._current_risk_level())

    @staticmethod
    def _review_skill_for_pass(review_pass: str) -> str:
        mapping = {
            "correctness": "review-correctness",
            "tests": "review-tests",
            "architecture": "review-architecture",
            "security": "review-security",
            "migrations": "review-migrations",
            "migration_or_rollback": "review-migrations",
            "performance": "review-performance",
        }
        if review_pass not in mapping:
            raise ValueError(f"Unknown review pass: {review_pass}")
        return mapping[review_pass]

    @staticmethod
    def _review_artifact_for_pass(review_pass: str) -> str:
        artifact_name = "migrations" if review_pass == "migration_or_rollback" else review_pass
        return f"review-{artifact_name}.md"

    def _run_review_group(self, step: dict[str, Any]) -> None:
        stage = step["id"]
        if self.config["gates"].get("require_tests_before_review"):
            if not self.test_results and not (self.run_dir / "test-results.md").exists():
                raise RuntimeError("Review requires check results, but test-results.md does not exist")
        passes = step.get("passes") or self._selected_review_passes()
        model = self._resolve_stage_model(stage)
        self._record_stage_routing(stage, model)
        provider_name = step.get("provider", self.config["providers"]["default"])
        pass_results: dict[str, dict[str, Any]] = {}
        outputs: list[tuple[str, str, dict[str, Any]]] = []
        for review_pass in passes:
            skill = self._review_skill_for_pass(review_pass)
            skill_path = Path(self.config["runtime"]["skills_dir"]) / skill / "SKILL.md"
            if not skill_path.exists():
                raise ValueError(f"Review skill not found: {skill_path}")
            output_name = self._review_artifact_for_pass(review_pass)
            output_path = self.run_dir / output_name
            review_step = {**step, "id": stage, "skill": skill, "output": output_name}
            prompt = self._prompt(review_step, skill_path.read_text(encoding="utf-8"))
            print(f"[{stage}:{review_pass}] {provider_name} / {model} -> {output_path}")
            if self.options.dry_run:
                continue
            (self.logs_dir / f"{stage}-{review_pass}.prompt.md").write_text(prompt, encoding="utf-8")
            result = make_provider(provider_name, self.config, self.repo).run(prompt, model, f"{stage}:{review_pass}")
            output = result.output.rstrip() + "\n"
            output_path.write_text(output, encoding="utf-8")
            self._validate_output(skill_path.parent, output)
            metadata = self._extract_agentic_yaml(output)
            pass_results[review_pass] = metadata
            outputs.append((review_pass, output, metadata))
            (self.logs_dir / f"{stage}-{review_pass}.output.md").write_text(output, encoding="utf-8")
            (self.logs_dir / f"{stage}-{review_pass}.command.txt").write_text(
                shlex.join(result.command) + "\n", encoding="utf-8"
            )
        if not self.options.dry_run:
            self._write_review_aggregate(step["output"], outputs)
            self.state["review"] = {"passes": pass_results}
            review_state = self._review_group_state(pass_results)
            self.state.setdefault("stages", {})[stage] = review_state
            if step.get("approval") or stage in self.config["gates"].get("require_approval_after", []):
                self._approve(stage, self.run_dir / step["output"], step)

    def _review_group_state(self, pass_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        findings = [
            finding
            for metadata in pass_results.values()
            for finding in metadata.get("findings", [])
            if isinstance(finding, dict)
        ]
        blocking = [finding for finding in findings if finding.get("severity") == "blocking"]
        important = [finding for finding in findings if finding.get("severity") == "important"]
        optional = [finding for finding in findings if finding.get("severity") == "optional"]
        status = "blocked" if blocking else "changes_requested" if important else "approved"
        return {
            "status": status,
            "review_passes": list(pass_results.keys()),
            "blocking_findings": len(blocking),
            "important_findings": len(important),
            "optional_findings": len(optional),
        }

    def _write_review_aggregate(self, output_name: str, outputs: list[tuple[str, str, dict[str, Any]]]) -> None:
        pass_results = {review_pass: metadata for review_pass, _, metadata in outputs}
        review_state = self._review_group_state(pass_results)
        lines = [
            "# Review",
            "",
            "## Summary",
            "",
            f"Overall status: {review_state['status']}",
            "",
            "## Review Passes",
            "",
        ]
        for review_pass, _, metadata in outputs:
            artifact = self._review_artifact_for_pass(review_pass)
            lines += [f"- {review_pass}: {metadata.get('status', 'unknown')} (`{artifact}`)"]
        lines += ["", "## Findings", ""]
        findings = [
            (review_pass, finding)
            for review_pass, _, metadata in outputs
            for finding in metadata.get("findings", [])
            if isinstance(finding, dict)
        ]
        for severity in ("blocking", "important", "optional"):
            lines += [f"### {severity.title()}", ""]
            matching = [(review_pass, finding) for review_pass, finding in findings if finding.get("severity") == severity]
            if not matching:
                lines += ["None.", ""]
                continue
            for review_pass, finding in matching:
                location = finding.get("file") or "unknown"
                if finding.get("line") is not None:
                    location = f"{location}:{finding['line']}"
                category = finding.get("category") or review_pass
                lines += [
                    f"- [{category}] {location}: {finding.get('issue', '')}",
                    f"  Recommendation: {finding.get('recommendation', '')}",
                ]
            lines.append("")
        lines += ["## Verdict", "", "Blocked" if review_state["status"] == "blocked" else "Approved", ""]
        (self.run_dir / output_name).write_text("\n".join(lines), encoding="utf-8")

    def _run_commands(self, step: dict[str, Any]) -> None:
        lines = [f"# {step['id']} Results", ""]
        failed = False
        checks = self.state.setdefault("checks", {})
        for name in step.get("commands", []):
            command = self.config["commands"].get(name)
            if not command:
                lines += [f"## {name}", "", "Skipped: command is not configured.", ""]
                checks[name] = {"command": None, "exit_code": None, "status": "skipped", "stage": step["id"]}
                continue
            print(f"[{step['id']}] $ {command}")
            if self.options.dry_run:
                continue
            result = subprocess.run(command, cwd=self.repo, shell=True, text=True, capture_output=True)
            combined = (result.stdout + result.stderr).strip()
            lines += [f"## {name}", "", f"Exit code: {result.returncode}", "", "```text", combined, "```", ""]
            checks[name] = {
                "command": command,
                "exit_code": result.returncode,
                "status": "passed" if result.returncode == 0 else "failed",
                "stage": step["id"],
            }
            failed |= result.returncode != 0
            if self.options.verbose and combined:
                print(combined)
        self.test_results = "\n".join(lines)
        if not self.options.dry_run:
            (self.run_dir / "test-results.md").write_text(self.test_results, encoding="utf-8")
        if failed:
            raise RuntimeError(f"Command group '{step['id']}' failed; see {self.run_dir / 'test-results.md'}")

    def _condition(self, condition: str | None) -> bool:
        if not condition:
            return True
        if condition == "review_has_blocking_findings":
            if self._structured_review_findings():
                return self._review_has_blocking_findings()
            review = self._artifact("review.md").casefold()
            verdict_blocked = bool(re.search(r"##\s+verdict\s*\n+\s*blocked\b", review))
            configured = self.config["gates"].get("block_on_review_findings", [])
            has_finding = any(
                re.search(rf"###\s+{re.escape(word.casefold())}\s*\n+(?:(?!\n###|\n##).)*?(?:^-\s|^-\s*\[[ x]\])", review, re.M | re.S)
                for word in configured
            )
            return verdict_blocked or has_finding
        if condition == "forge_create_pr_enabled":
            return bool(self.config["forge"].get("create_pr"))
        raise ValueError(f"Unknown pipeline condition: {condition}")

    def _structured_review_findings(self) -> list[dict[str, Any]]:
        return [
            finding
            for metadata in self.state.get("review", {}).get("passes", {}).values()
            for finding in metadata.get("findings", [])
            if isinstance(finding, dict)
        ]

    def _review_has_blocking_findings(self) -> bool:
        return any(finding.get("severity") == "blocking" for finding in self._structured_review_findings())

    def _review_has_security_blocking_findings(self) -> bool:
        return any(
            finding.get("severity") == "blocking" and finding.get("category") == "security"
            for finding in self._structured_review_findings()
        )

    def _artifact_ref(self, name: str) -> str:
        path = self.run_dir / name
        try:
            return str(path.relative_to(self.repo))
        except ValueError:
            return str(path)

    def _checklist_status(self, status: str | None) -> str:
        return "x" if status == "passed" else " "

    def _review_artifact_refs(self) -> list[tuple[str, str]]:
        passes = list(self.state.get("review", {}).get("passes", {}).keys())
        if not passes:
            passes = self.state.get("routing", {}).get("review_passes", [])
        refs = []
        for review_pass in passes:
            artifact = self._review_artifact_for_pass(review_pass)
            if (self.run_dir / artifact).exists():
                refs.append((review_pass, self._artifact_ref(artifact)))
        if (self.run_dir / "review.md").exists():
            refs.insert(0, ("aggregate", self._artifact_ref("review.md")))
        return refs

    def _build_pr_body(self) -> str:
        risk = self.state.get("risk", {"level": self._current_risk_level()})
        routing = self.state.get("routing", {})
        lines = [
            "## Summary",
            "",
            self.options.task,
            "",
            "## Requirements",
            "",
            f"- Link: `{self._artifact_ref('requirements.md')}`",
            "",
            "## Architecture",
            "",
            f"- Link: `{self._artifact_ref('design.md')}`",
            "",
            "## Risk",
            "",
            f"Level: {risk.get('level', 'unknown')}",
        ]
        reasons = risk.get("reasons") or []
        if reasons:
            lines += ["", "Reasons:"]
            lines += [f"- {reason}" for reason in reasons]
        if routing.get("require_manual_merge"):
            lines += ["", "> Manual merge required for this risk level."]
        lines += ["", "## Checks", ""]
        checks = self.state.get("checks", {})
        if checks:
            for name, data in checks.items():
                status = data.get("status")
                exit_code = data.get("exit_code")
                suffix = f" (exit {exit_code})" if exit_code is not None else ""
                lines.append(f"- [{self._checklist_status(status)}] {name}: {status}{suffix}")
        else:
            lines.append("- [ ] No checks recorded.")
        lines += ["", "## Review Artifacts", ""]
        review_refs = self._review_artifact_refs()
        if review_refs:
            lines += [f"- {name}: `{path}`" for name, path in review_refs]
        else:
            lines.append("- No review artifacts recorded.")
        lines += [
            "",
            "## Evaluation",
            "",
            f"- Link: `{self._artifact_ref('evaluation.yaml')}`",
            "",
            "## Human Notes",
            "",
            "<!-- Human reviewer fills this in. -->",
            "",
        ]
        return "\n".join(lines)

    def _auto_commit_and_push_for_pr(self) -> None:
        artifacts_dir = Path(self.config["runtime"]["artifacts_dir"]).resolve()
        self.git.stage_all_except([artifacts_dir])
        if not self.git.has_staged_changes():
            return
        self.git.commit(f"AI: {self._task_title()}")
        self.git.push_current_branch()

    def _create_pr(self) -> None:
        forge = make_forge(self.config, self.repo)
        if forge is None:
            raise RuntimeError("PR creation is enabled but no supported forge is configured")
        if self.config["forge"].get("auto_commit_push"):
            self._auto_commit_and_push_for_pr()
        body = self.run_dir / "pr-body.md"
        body.write_text(self._build_pr_body(), encoding="utf-8")
        url = forge.create_pr(self._task_title(), body, self.config["project"]["default_branch"])
        (self.run_dir / "pr-url.txt").write_text(url + "\n", encoding="utf-8")
        self.state["pr"] = {"created": True, "url": url}
        print(f"Pull request: {url}")

    def _evaluation(self) -> dict[str, Any]:
        stages = {}
        for stage, values in self.state.get("stages", {}).items():
            stages[stage] = dict(values)
        for stage, values in self.state.get("routing", {}).get("stages", {}).items():
            stages.setdefault(stage, {})["model"] = values.get("model")
        routing = self.state.get("routing", {})
        if "review" in stages:
            stages["review"]["review_passes"] = routing.get("review_passes", [])
        return {
            "run_id": self.run_id,
            "task": self.options.task,
            "repo": self.config["project"]["name"],
            "branch": self.state.get("branch"),
            "pipeline": self.options.pipeline_name,
            "status": self.state.get("status"),
            "completed_stages": self.state.get("completed", []),
            "stages": stages,
            "risk": self.state.get("risk", {"level": self._current_risk_level()}),
            "routing": {
                "risk_level": routing.get("risk_level", self._current_risk_level()),
                "implementation_model": routing.get("implementation_model"),
                "review_passes": routing.get("review_passes", self._selected_review_passes()),
                "require_manual_merge": routing.get("require_manual_merge", False),
            },
            "checks": self.state.get("checks", {}),
            "outcome": {
                "pr_created": bool(self.state.get("pr", {}).get("created")),
                "pr_url": self.state.get("pr", {}).get("url"),
                "require_manual_merge": routing.get("require_manual_merge", False),
            },
        }

    def _write_evaluation(self) -> None:
        (self.run_dir / "evaluation.yaml").write_text(
            yaml.safe_dump(self._evaluation(), sort_keys=False), encoding="utf-8"
        )

    def run(self) -> Path:
        self.prepare()
        completed = set(self.state.get("completed", []))
        selected = [s for s in self.pipeline["steps"] if not self.options.stage or s["id"] == self.options.stage]
        if self.options.stage and not selected:
            raise ValueError(f"Stage not found in pipeline: {self.options.stage}")
        try:
            for step in selected:
                stage = step["id"]
                if stage in completed or not self._condition(step.get("condition")):
                    continue
                if step.get("type", "skill") == "skill":
                    self._run_skill(step)
                elif step["type"] == "review_group":
                    self._run_review_group(step)
                elif step["type"] == "command_group":
                    self._run_commands(step)
                elif step["type"] == "forge_pr":
                    if not self.options.dry_run:
                        self._create_pr()
                else:
                    raise ValueError(f"Unknown step type: {step['type']}")
                if not self.options.dry_run:
                    self.state.setdefault("completed", []).append(stage)
                    self._save_state()
        except Exception:
            if not self.options.dry_run:
                if self.state.get("status") == "running":
                    self.state["status"] = "failed"
                self._save_state()
                self._write_evaluation()
            raise
        if not self.options.dry_run:
            self.state["status"] = "completed"
            self._save_state()
            self._write_evaluation()
        return self.run_dir
