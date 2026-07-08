import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agentic.config import load_config
from agentic.pipeline import PipelineRunner, RunOptions, slugify
from agentic.providers.base import ProviderResult


REQUIREMENTS_READY = """```yaml agentic
status: ready
confidence: 0.9
blocking_questions: []
assumptions: []
acceptance_criteria: []
non_goals: []
test_scenarios: []
```

# Requirements
## Summary
## Assumptions
## Functional Requirements
## Non-Functional Requirements
## Edge Cases
## Acceptance Criteria
## Open Questions
## Suggested Test Scenarios
"""

ARCHITECTURE_READY = """```yaml agentic
status: ready
confidence: 0.8
affected_modules: []
files_to_change: []
data_model_changes: []
api_changes: []
security_considerations: []
rollback_plan: null
implementation_plan: []
risk:
  level: low
  reasons: []
  touches: []
  estimated_files_changed: 0
  user_data_impact: none
  rollback_complexity: low
```

# Architecture
## Context
## Proposed Design
## Components and Interfaces
## Data Flow
## Error Handling
## Security and Privacy
## Alternatives
## Rollout
## Implementation Plan
## Validation Plan
"""

REVIEW_APPROVED = """```yaml agentic
summary: "No issues found."
status: approved
findings: []
```

# Review Correctness
## Summary
No issues found.
## Findings
None.
## Verdict
Approved
"""

REVIEW_BLOCKED = """```yaml agentic
summary: "Security issue found."
status: blocked
findings:
  - severity: blocking
    category: security
    file: app/auth.py
    line: 12
    issue: "Authorization check can be bypassed."
    recommendation: "Enforce authorization before returning user data."
```

# Review Security
## Summary
Security issue found.
## Findings
- Authorization check can be bypassed.
## Verdict
Blocked
"""


class PipelineTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify(" Add OAuth 2.0! "), "add-oauth-2-0")

    def runner(self, root: Path, pipeline=None, task="Do a thing") -> PipelineRunner:
        config = load_config(root)
        config["runtime"]["artifacts_dir"] = str(root / "runs")
        return PipelineRunner(
            root,
            config,
            pipeline or {"steps": []},
            RunOptions(task=task, pipeline_name="test", skip_approval=True, dry_run=False),
        )

    def test_prepare_creates_auditable_run(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            run_dir = runner.run()
            self.assertTrue((run_dir / "task.md").exists())
            self.assertTrue((run_dir / "config.snapshot.yaml").exists())
            self.assertEqual(json.loads((run_dir / "state.json").read_text())["status"], "completed")

    def test_review_condition_uses_verdict_or_actual_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            runner.prepare()
            (runner.run_dir / "review.md").write_text(
                "# Review\n## Findings\n### Blocking\n\nNone.\n### Security\n\nNone.\n## Verdict\nApproved\n"
            )
            self.assertFalse(runner._condition("review_has_blocking_findings"))
            (runner.run_dir / "review.md").write_text(
                "# Review\n## Findings\n### Blocking\n\n- Missing check\n## Verdict\nBlocked\n"
            )
            self.assertTrue(runner._condition("review_has_blocking_findings"))

    def test_review_group_runs_selected_passes_and_aggregates_results(self):
        class FakeProvider:
            def run(self, prompt, model, stage):
                output = REVIEW_BLOCKED if stage.endswith(":security") else REVIEW_APPROVED
                return ProviderResult(output=output, command=["fake-review", stage], returncode=0)

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="harden auth")
            runner.prepare()
            runner.test_results = "# checks\npassed"
            step = {
                "id": "review",
                "type": "review_group",
                "passes": ["correctness", "security"],
                "inputs": ["git_diff", "test_results"],
                "output": "review.md",
            }
            with patch("agentic.pipeline.make_provider", return_value=FakeProvider()):
                runner._run_review_group(step)

            self.assertTrue((runner.run_dir / "review-correctness.md").exists())
            self.assertTrue((runner.run_dir / "review-security.md").exists())
            aggregate = (runner.run_dir / "review.md").read_text()
            self.assertIn("### Blocking", aggregate)
            self.assertIn("[security] app/auth.py:12", aggregate)
            self.assertIn("## Verdict\n\nBlocked", aggregate)
            self.assertTrue(runner._condition("review_has_blocking_findings"))
            self.assertEqual(runner.state["stages"]["review"]["status"], "blocked")
            self.assertEqual(runner.state["stages"]["review"]["blocking_findings"], 1)
            self.assertIn("security", runner.state["review"]["passes"])

    def test_command_results_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = self.runner(root, {"steps": [{"id": "checks", "type": "command_group", "commands": ["test"]}]})
            runner.config["commands"]["test"] = "printf passed"
            run_dir = runner.run()
            result = (run_dir / "test-results.md").read_text()
            state = json.loads((run_dir / "state.json").read_text())
            self.assertIn("Exit code: 0", result)
            self.assertIn("passed", result)
            self.assertEqual(state["checks"]["test"]["status"], "passed")

    def test_resume_skips_completed_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.runner(root, {"steps": [{"id": "checks", "type": "command_group", "commands": []}]})
            run_dir = first.run()
            options = RunOptions(task="", pipeline_name="test", resume=run_dir, skip_approval=True)
            resumed = PipelineRunner(root, first.config, first.pipeline, options)
            resumed.run()
            self.assertEqual(json.loads((run_dir / "state.json").read_text())["completed"], ["checks"])

    def test_output_schema_rejects_missing_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "output-schema.yaml").write_text("required_sections: [Summary, Verdict]\n")
            with self.assertRaisesRegex(RuntimeError, "Verdict"):
                PipelineRunner._validate_output(skill, "# Summary\n\nLooks good.\n")

    def test_output_schema_requires_agentic_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "output-schema.yaml").write_text("required_metadata: [status, confidence]\n")
            with self.assertRaisesRegex(RuntimeError, "metadata block"):
                PipelineRunner._validate_output(skill, "# Summary\n\nLooks good.\n")

    def test_output_schema_accepts_present_null_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "output-schema.yaml").write_text("required_metadata: [rollback_plan]\n")
            PipelineRunner._validate_output(skill, "```yaml agentic\nrollback_plan: null\n```\n")

    def test_output_schema_rejects_invalid_metadata_enum(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "output-schema.yaml").write_text(
                "required_metadata: [status]\nmetadata_enums:\n  status: [ready, risky, blocked]\n"
            )
            with self.assertRaisesRegex(RuntimeError, "invalid metadata values"):
                PipelineRunner._validate_output(skill, "```yaml agentic\nstatus: maybe\n```\n")

    def test_specialized_review_schemas_accept_structured_output(self):
        root = Path(__file__).resolve().parent.parent
        for name in (
            "review-correctness",
            "review-tests",
            "review-architecture",
            "review-security",
            "review-migrations",
            "review-performance",
        ):
            with self.subTest(name=name):
                PipelineRunner._validate_output(root / "skills" / name, REVIEW_APPROVED)

    def test_review_pass_mapping(self):
        self.assertEqual(PipelineRunner._review_skill_for_pass("correctness"), "review-correctness")
        self.assertEqual(PipelineRunner._review_skill_for_pass("migration_or_rollback"), "review-migrations")
        self.assertEqual(PipelineRunner._review_artifact_for_pass("migration_or_rollback"), "review-migrations.md")

    def test_requirements_blocked_gate_stops_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            runner.prepare()
            artifact = runner.run_dir / "requirements.md"
            artifact.write_text(REQUIREMENTS_READY.replace("status: ready", "status: blocked"))
            with self.assertRaisesRegex(RuntimeError, "requirements gate blocked"):
                runner._enforce_stage_gate("requirements", artifact, {"id": "requirements", "output": "requirements.md"})
            state = json.loads((runner.run_dir / "state.json").read_text())
            self.assertEqual(state["status"], "stopped")

    def test_architecture_blocked_gate_stops_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            runner.prepare()
            artifact = runner.run_dir / "design.md"
            artifact.write_text(ARCHITECTURE_READY.replace("status: ready", "status: blocked"))
            with self.assertRaisesRegex(RuntimeError, "architecture gate blocked"):
                runner._enforce_stage_gate("architecture", artifact, {"id": "architecture", "output": "design.md"})

    def test_risky_gate_requires_approval_when_step_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            runner.options.skip_approval = False
            runner.prepare()
            artifact = runner.run_dir / "requirements.md"
            artifact.write_text(REQUIREMENTS_READY.replace("status: ready", "status: risky"))
            approvals = []

            def approve(stage, output_path, step):
                approvals.append((stage, output_path.name, step["output"]))

            runner._approve = approve
            requested = runner._enforce_stage_gate(
                "requirements", artifact, {"id": "requirements", "output": "requirements.md", "approval": False}
            )
            self.assertTrue(requested)
            self.assertEqual(approvals, [("requirements", "requirements.md", "requirements.md")])

    def test_high_risk_architecture_requires_approval_and_records_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            runner.prepare()
            artifact = runner.run_dir / "design.md"
            runner._record_stage_routing("architecture", "opus")
            self.assertEqual(runner.state["routing"]["risk_level"], "low")
            artifact.write_text(ARCHITECTURE_READY.replace("level: low", "level: high"))
            approvals = []
            runner._approve = lambda stage, output_path, step: approvals.append(stage)
            requested = runner._enforce_stage_gate("architecture", artifact, {"id": "architecture", "output": "design.md"})
            runner._record_stage_routing("architecture", "opus")
            self.assertTrue(requested)
            self.assertEqual(approvals, ["architecture"])
            self.assertEqual(runner.state["risk"]["level"], "high")
            self.assertEqual(runner.state["routing"]["risk_level"], "high")
            self.assertIn("security", runner.state["routing"]["review_passes"])

    def test_invalid_architecture_risk_level_fails_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory))
            runner.prepare()
            artifact = runner.run_dir / "design.md"
            artifact.write_text(ARCHITECTURE_READY.replace("level: low", "level: extreme"))
            with self.assertRaisesRegex(RuntimeError, "invalid risk level"):
                runner._enforce_stage_gate("architecture", artifact, {"id": "architecture", "output": "design.md"})

    def test_current_risk_level_prefers_architecture_state(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="rename button")
            runner.state["risk"] = {"level": "critical"}
            self.assertEqual(runner._current_risk_level(), "critical")
            self.assertEqual(runner._resolve_stage_model("implementation"), "opus")

    def test_current_risk_level_reads_architecture_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="rename button")
            runner.prepare()
            (runner.run_dir / "design.md").write_text(ARCHITECTURE_READY.replace("level: low", "level: high"))
            self.assertEqual(runner._current_risk_level(), "high")
            self.assertEqual(runner._resolve_stage_model("implementation"), "opus")

    def test_current_risk_level_uses_keyword_fallback_before_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="change payment flow")
            self.assertEqual(runner._current_risk_level(), "high")

    def test_review_prompt_includes_selected_review_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="rename button")
            runner.prepare()
            (runner.run_dir / "design.md").write_text(ARCHITECTURE_READY.replace("level: low", "level: high"))
            prompt = runner._prompt({"id": "review", "inputs": []}, "Review skill")
            self.assertIn("# Required review passes", prompt)
            self.assertIn("- security", prompt)

    def test_prompt_includes_stage_specific_repo_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_dir = root / ".ai" / "context"
            context_dir.mkdir(parents=True)
            (context_dir / "repo-map.md").write_text("# Repo Map\n\nArchitecture and implementation context.\n")
            (context_dir / "module-boundaries.md").write_text("# Module Boundaries\n\nArchitecture-only context.\n")
            runner = self.runner(root, task="rename button")
            runner.config["context"]["architecture"] = ["repo-map.md", "module-boundaries.md"]
            runner.config["context"]["implementation"] = ["repo-map.md"]

            architecture_prompt = runner._prompt({"id": "architecture", "inputs": []}, "Architecture skill")
            implementation_prompt = runner._prompt({"id": "implementation", "inputs": []}, "Implementation skill")

            self.assertIn("Architecture-only context", architecture_prompt)
            self.assertIn("Architecture and implementation context", implementation_prompt)
            self.assertNotIn("Architecture-only context", implementation_prompt)

    def test_prompt_handles_missing_repo_context_files(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="rename button")
            prompt = runner._prompt({"id": "architecture", "inputs": []}, "Architecture skill")
            self.assertIn("No configured repo context file was found", prompt)

    def test_prompt_includes_stage_specific_repo_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory_dir = root / ".ai" / "memory"
            memory_dir.mkdir(parents=True)
            (memory_dir / "decisions.md").write_text("# Decisions\n\nArchitecture and review memory.\n")
            (memory_dir / "lessons-learned.md").write_text("# Lessons\n\nImplementation-only memory.\n")
            runner = self.runner(root, task="rename button")
            runner.config["memory"]["architecture"] = ["decisions.md"]
            runner.config["memory"]["implementation"] = ["lessons-learned.md"]

            architecture_prompt = runner._prompt({"id": "architecture", "inputs": []}, "Architecture skill")
            implementation_prompt = runner._prompt({"id": "implementation", "inputs": []}, "Implementation skill")

            self.assertIn("# Repository memory", architecture_prompt)
            self.assertIn("Architecture and review memory", architecture_prompt)
            self.assertIn("Implementation-only memory", implementation_prompt)
            self.assertNotIn("Implementation-only memory", architecture_prompt)

    def test_prompt_handles_missing_repo_memory_files(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="rename button")
            prompt = runner._prompt({"id": "review", "inputs": []}, "Review skill")
            self.assertIn("No configured repo memory file was found", prompt)

    def test_stage_routing_records_review_passes_and_manual_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(Path(directory), task="rename button")
            runner.prepare()
            runner.state["risk"] = {"level": "critical"}
            runner._record_stage_routing("implementation", "opus")
            self.assertEqual(runner.state["routing"]["implementation_model"], "opus")
            self.assertIn("migration_or_rollback", runner.state["routing"]["review_passes"])
            self.assertTrue(runner.state["routing"]["require_manual_merge"])

    def test_evaluation_yaml_records_run_without_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = self.runner(root, {"steps": [{"id": "checks", "type": "command_group", "commands": ["test"]}]})
            runner.config["commands"]["test"] = "printf passed"
            runner.state["stages"] = {"requirements": {"status": "ready", "confidence": 0.9}}
            runner.state["routing"] = {
                "stages": {"requirements": {"model": "haiku"}},
                "risk_level": "low",
                "review_passes": ["correctness", "tests"],
                "require_manual_merge": False,
            }
            run_dir = runner.run()
            evaluation = yaml.safe_load((run_dir / "evaluation.yaml").read_text())

            self.assertEqual(evaluation["run_id"], run_dir.name)
            self.assertEqual(evaluation["repo"], root.name)
            self.assertEqual(evaluation["checks"]["test"]["status"], "passed")
            self.assertEqual(evaluation["stages"]["requirements"]["model"], "haiku")
            self.assertFalse(evaluation["outcome"]["pr_created"])
            self.assertNotIn("cost_usd", str(evaluation))

    def test_failed_command_writes_evaluation_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = self.runner(root, {"steps": [{"id": "checks", "type": "command_group", "commands": ["test"]}]})
            runner.config["commands"]["test"] = "python3 -c 'import sys; sys.exit(2)'"
            with self.assertRaisesRegex(RuntimeError, "failed"):
                runner.run()

            evaluation = yaml.safe_load((runner.run_dir / "evaluation.yaml").read_text())
            self.assertEqual(evaluation["status"], "failed")
            self.assertEqual(evaluation["checks"]["test"]["exit_code"], 2)
            self.assertEqual(evaluation["checks"]["test"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
