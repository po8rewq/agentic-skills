import json
import tempfile
import unittest
from pathlib import Path

from agentic.config import load_config
from agentic.pipeline import PipelineRunner, RunOptions, slugify


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

    def test_command_results_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = self.runner(root, {"steps": [{"id": "checks", "type": "command_group", "commands": ["test"]}]})
            runner.config["commands"]["test"] = "printf passed"
            run_dir = runner.run()
            result = (run_dir / "test-results.md").read_text()
            self.assertIn("Exit code: 0", result)
            self.assertIn("passed", result)

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
            artifact.write_text(ARCHITECTURE_READY.replace("level: low", "level: high"))
            approvals = []
            runner._approve = lambda stage, output_path, step: approvals.append(stage)
            requested = runner._enforce_stage_gate("architecture", artifact, {"id": "architecture", "output": "design.md"})
            self.assertTrue(requested)
            self.assertEqual(approvals, ["architecture"])
            self.assertEqual(runner.state["risk"]["level"], "high")


if __name__ == "__main__":
    unittest.main()
