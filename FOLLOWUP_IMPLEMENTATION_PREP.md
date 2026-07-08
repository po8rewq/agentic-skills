# Follow-Up Implementation Preparation

Source plan: `/Users/adrien/Downloads/agentic_coding_followup_plan.md`

## Current State

The repository already has the core orchestrator shape:

- `agentic/pipeline.py` creates auditable run directories, prompts providers, validates simple Markdown section schemas, runs configured checks, gates manual approval, and can create PRs through a forge adapter.
- `agentic/config.py` merges defaults with `agentic.yaml`, resolves paths, validates basic config, loads pipeline YAML, and supports config-driven risk routing with keyword fallback.
- `pipelines/default.yaml` and `pipelines/production.yaml` define requirements, architecture, implementation, checks, review, fix-review, final checks, and PR creation.
- `skills/*/SKILL.md` define the provider-facing instructions. Requirements and architecture now require machine-readable `yaml agentic` gate metadata before their Markdown sections.
- Tests cover config loading, risk routing, gate enforcement, run directory creation, command persistence, resume behavior, and the current Markdown review-blocking heuristic.

The follow-up plan should be implemented as a set of strict pipeline controls, not as a large autonomous-agent rewrite.

## Implementation Strategy

Implement this in small, testable milestones. The first milestone should make ambiguous work stop before implementation. Later milestones can layer on richer routing, context, metrics, and PR quality.

Avoid changing provider integrations until the local orchestration semantics are deterministic and covered by tests.

## Milestone 1: Blocking Gates

Goal: requirements and architecture outputs become parseable, enforceable stage gates.

### Files to change

- `skills/requirements/SKILL.md`
- `skills/requirements/output-schema.yaml`
- `skills/architecture/SKILL.md`
- `skills/architecture/output-schema.yaml`
- `agentic/pipeline.py`
- `tests/test_pipeline.py`
- `README.md`

### Proposed artifact format

Keep artifacts human-readable Markdown, but require a fenced YAML front matter block at the top:

````markdown
```yaml agentic
status: ready
confidence: 0.86
blocking_questions: []
assumptions: []
acceptance_criteria: []
non_goals: []
test_scenarios: []
```

# Requirements
...
````

For architecture:

````markdown
```yaml agentic
status: ready
confidence: 0.82
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
...
````

This avoids a full artifact migration while still giving the runner stable machine-readable data.

### Runner behavior

Add helpers to `PipelineRunner`:

- `_extract_agentic_yaml(output: str) -> dict[str, Any]`
- `_load_stage_metadata(artifact_name: str) -> dict[str, Any]`
- `_enforce_stage_gate(stage: str, output_path: Path) -> None`

Gate rules:

- `requirements.status == blocked` stops the pipeline.
- `requirements.status == risky` requires approval, even when the step itself does not specify `approval: true`.
- `architecture.status == blocked` stops the pipeline.
- `architecture.status == risky` requires approval.
- `architecture.risk.level in ["high", "critical"]` requires approval.

`--skip-approval` should continue to mean “non-interactive test/automation mode,” but blocked status should still stop.

### Acceptance tests

Add tests that assert:

- Requirements output with `status: blocked` raises before implementation.
- Architecture output with `status: blocked` raises before implementation.
- `status: risky` calls the approval path when `skip_approval` is false.
- Missing required YAML keys fails output validation.
- Existing Markdown section validation still works.

## Milestone 2: Risk Scoring and Routing

Goal: route implementation and review from architecture risk metadata rather than task keywords alone.

### Files to change

- `agentic/config.py`
- `agentic/pipeline.py`
- `agentic.example.yaml`
- `pipelines/default.yaml`
- `pipelines/production.yaml`
- `tests/test_config.py`
- `tests/test_pipeline.py`

### Config shape

Extend config with explicit risk routing:

```yaml
risk_routing:
  default_level: low
  implementation_models:
    low: medium
    medium: coding
    high: best
    critical: best
  review_passes:
    low: [correctness, tests]
    medium: [correctness, architecture, tests]
    high: [correctness, architecture, security, tests]
    critical: [correctness, architecture, security, tests, migration_or_rollback]
  require_human_approval: [high, critical]
  require_manual_merge: [critical]
```

### Runner behavior

- Resolve architecture risk after the architecture stage completes.
- Store risk in `state.json`.
- Use risk to resolve the implementation model.
- Keep keyword routing as a fallback only when architecture metadata is unavailable.

### Milestone 2A status

Implemented:

- Config-driven `risk_routing` defaults and validation.
- Architecture risk/state/artifact lookup as the source of truth after architecture.
- Keyword fallback before architecture exists.
- Risk-based implementation model selection.
- Review-pass selection and injection into the generic review prompt.
- Routing decisions recorded in `state.json`.

Still pending for later Milestone 2/5 work:

- Separate specialized review stage execution.
- Review pass aggregation from multiple artifacts.

## Milestone 3: Repo Context

Goal: consistently feed compact repo context to architecture/review and limited context to implementation.

### Files to change

- `agentic/config.py`
- `agentic/pipeline.py`
- `agentic/install.py`
- `agentic.example.yaml`
- `README.md`
- `tests/test_pipeline.py`

### New template files

Add installable context templates:

```text
templates/context/repo-map.md
templates/context/module-boundaries.md
templates/context/test-commands.md
templates/context/coding-conventions.md
templates/context/dangerous-areas.md
templates/context/dependency-map.md
templates/context/ownership.md
```

Add memory templates:

```text
templates/memory/decisions.md
templates/memory/known-issues.md
templates/memory/lessons-learned.md
templates/memory/recurring-review-comments.md
templates/memory/preferred-patterns.md
```

### CLI support

Extend `install-agentic-skills` with:

- `--with-context`
- `--with-memory`
- `--context-destination .ai/context`
- `--memory-destination .ai/memory`

Default behavior should remain skill-only to avoid surprising writes.

## Milestone 4: Evaluation Harness

Goal: write `.ai/runs/<run-id>/evaluation.yaml` every run.

### Files to change

- `agentic/pipeline.py`
- `tests/test_pipeline.py`
- `README.md`

### Minimum first version

Record:

- `run_id`
- `task`
- `repo`
- `branch`
- completed stages
- stage model names
- gate statuses and confidence values
- risk level
- command results
- PR creation status

Do not block on accurate cost accounting in the first pass. Include `cost_usd: null` until providers expose usage reliably.

## Milestone 5: Specialized Review

Goal: replace one generic review stage with selected review passes.

### Files to add

- `skills/review-correctness/SKILL.md`
- `skills/review-correctness/output-schema.yaml`
- `skills/review-architecture/SKILL.md`
- `skills/review-architecture/output-schema.yaml`
- `skills/review-tests/SKILL.md`
- `skills/review-tests/output-schema.yaml`
- `skills/review-security/SKILL.md`
- `skills/review-security/output-schema.yaml`
- `skills/review-migrations/SKILL.md`
- `skills/review-migrations/output-schema.yaml`
- `skills/review-performance/SKILL.md`
- `skills/review-performance/output-schema.yaml`

### Runner behavior

- Add a new pipeline step type, likely `review_group`.
- Select review passes from risk metadata and config.
- Write one artifact per pass: `review-correctness.md`, `review-tests.md`, etc.
- Aggregate findings into `review.md`.
- Block fix-review on any `severity: blocking`.

## Milestone 6: PR Generation Upgrade

Goal: PRs include requirements, architecture, risk, checks, and review artifacts.

### Files to change

- `agentic/pipeline.py`
- `agentic/forges/github.py`
- `agentic/forges/gitea.py`
- `agentic.example.yaml`
- `README.md`
- `tests/test_pipeline.py`

### PR body sections

- Summary
- Requirements artifact link
- Architecture artifact link
- Risk level and reasons
- Checks
- Review artifacts
- Human notes

Keep merge manual. Critical-risk work should be clearly marked as manual-merge-only.

## Recommended First Coding Pass

Implement Milestone 1 and the architecture risk metadata shape from Milestone 2, but do not yet add specialized review passes.

That first pass should produce a pipeline that can:

1. Require parseable YAML gate metadata.
2. Stop on blocked requirements or blocked architecture.
3. Require approval for risky requirements, risky architecture, and high/critical risk.
4. Persist stage status/risk into `state.json`.
5. Keep all current tests passing, with new tests for gate enforcement.

This gives immediate safety value without exploding the surface area.

## Open Design Decisions Before Coding

- Whether fenced `yaml agentic` blocks are acceptable, or whether artifacts should become pure `.yaml` files plus companion `.md` explanations.
- Whether `--skip-approval` should bypass high-risk approval locally. Current recommendation: yes for CI/dry-run ergonomics, but never bypass `blocked`.
- Whether context/memory templates should be installed by default. Current recommendation: no; require explicit flags.
- Whether review specialization should be modeled as pipeline YAML expansion or a new runner step type. Current recommendation: add `review_group` because pass selection depends on runtime risk.
