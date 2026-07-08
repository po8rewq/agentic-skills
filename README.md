# Agentic Coding Pipeline

A small, auditable orchestrator that runs software work through requirements,
architecture, implementation, checks, review, review fixes, and pull-request creation.
Skills remain provider-agnostic; repository config chooses providers and models.

## Install

```bash
cd /path/to/agentic-skills
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip setuptools
python3 -m pip install -e .

cp agentic.example.yaml /path/to/project/agentic.yaml
cd /path/to/project
/path/to/agentic-skills/.venv/bin/install-agentic-skills --source /path/to/agentic-skills/skills .ai/skills
```

The packaging-tool upgrade is required when the virtual environment contains an old
pip release that cannot install a `pyproject.toml`-based project in editable mode.
Keep the virtual environment activated whenever you use `run-pipeline`,
`validate-agentic-config`, or `install-agentic-skills`. Alternatively, invoke the
commands using their full paths under
`/path/to/agentic-skills/.venv/bin/`.

Confirm the installation with:

```bash
run-pipeline --help
```

### What gets installed or copied

The pipeline scripts are **not copied into the target project**. The editable pip
installation creates these executable commands inside the shared virtual environment:

```text
/path/to/agentic-skills/.venv/bin/run-pipeline
/path/to/agentic-skills/.venv/bin/validate-agentic-config
/path/to/agentic-skills/.venv/bin/install-agentic-skills
```

Activating that environment adds its `bin` directory to `PATH`, which makes those
commands available while working in any project:

```bash
source /path/to/agentic-skills/.venv/bin/activate
cd /path/to/project
run-pipeline --task "Add password reset flow"
```

Only two things live inside the target project:

1. `agentic.yaml` or `agentic.yml`, copied manually from `agentic.example.yaml` and
   customized for the project.
2. `.ai/skills/`, copied by `install-agentic-skills` from this repository's `skills/`
   directory. The install command above names both paths explicitly: `--source` is the
   shared skills directory and the final argument is the project-local destination.

Because this is an editable installation, `--source` is optional: the installed
command can derive the source directory from the `agentic-skills` package location.
These two commands are therefore equivalent when run from the target project:

```bash
install-agentic-skills --source /path/to/agentic-skills/skills .ai/skills
install-agentic-skills .ai/skills
```

The command prints the resolved source and destination after copying. If `.ai/skills`
already exists, it stops without changing it; pass `--force` to replace the existing
copy.

Optionally install starter repo-context and repo-memory templates:

```bash
install-agentic-skills \
  --with-context \
  --with-memory \
  .ai/skills
```

This also copies:

```text
.ai/context/
.ai/memory/
```

Context and memory templates are not installed by default, because those files are
intended to become project-specific documentation. Use `--context-destination` or
`--memory-destination` to choose different locations.

The shared Python package supplies the orchestrator and its scripts. This avoids
maintaining duplicate script copies in every project, while vendoring the Markdown
skills allows each project to pin or customize its agent behavior.

Edit `agentic.yaml` or `agentic.yml` for the project's commands, providers, gates, and
forge. Vendored skills default to `.ai/skills`; the installed package's shared skills
are used when no local override is configured. If neither config file exists,
`run-pipeline` and `validate-agentic-config` print a warning before using built-in
defaults.

## Run

```bash
run-pipeline --task "Add password reset flow"
run-pipeline --issue 123
run-pipeline --pipeline cheap --task "Fix a typo"
run-pipeline --stage requirements --task "Add audit logging"
run-pipeline --resume .ai/runs/2026-07-07-add-audit-logging
run-pipeline --model review=claude-opus-4-6 --task "Harden authentication"
run-pipeline --dry-run --skip-approval --task "Preview the workflow"
```

Every run stores the task, merged config snapshot, prompts, provider outputs, command
results, state, and PR context below `.ai/runs/<timestamp>-<task>/`. Resume skips
completed stages. Architecture risk metadata drives later routing decisions, with
task-keyword risk detection as a fallback before architecture exists.
Each non-dry run also writes `evaluation.yaml`, a cost-free structured summary of
the run status, completed stages, gate metadata, routing, checks, and PR outcome.
When `vcs.require_clean_worktree` is enabled, the runner checks repository cleanliness
before creating a run directory, so rejected starts do not leave partial artifacts.

### Requirements and architecture gates

The requirements and architecture artifacts must start with a fenced
`yaml agentic` metadata block. The runner validates this block before continuing:

```yaml
status: ready # ready | risky | blocked
confidence: 0.86
```

Requirements also report blocking questions, assumptions, acceptance criteria,
non-goals, and test scenarios. Architecture also reports affected modules, planned
files, contract changes, rollback information, and initial risk metadata.
The runner validates required metadata fields and enum values declared by each
skill's `output-schema.yaml`.

Gate behavior:

- `status: blocked` stops the pipeline before implementation.
- `status: risky` requires human approval.
- architecture `risk.level: high` or `risk.level: critical` requires human approval.

`--skip-approval` bypasses approval prompts for non-interactive runs, but it does
not bypass `blocked` gates.

At approval prompts, `r` reruns the current stage and `e` opens the current
artifact in an editor before returning to the same prompt. Configure the editor
with a top-level `editor` key in `agentic.yaml` or `agentic.yml`, for example
`editor: "code --wait"`. If `editor` is unset, the runner falls back to `$EDITOR`
and then `vi`.

### Risk routing

Architecture output includes:

```yaml
risk:
  level: low # low | medium | high | critical
  reasons: []
  touches: []
  estimated_files_changed: 0
  user_data_impact: none
  rollback_complexity: low
```

After architecture runs, the pipeline uses `risk.level` as the source of truth for
implementation routing and review planning. If architecture has not run yet, the
runner falls back to `risk_routing.keyword_fallback.high_risk_keywords`.

Configure routing in `agentic.yaml`:

```yaml
risk_routing:
  default_level: low
  implementation_models:
    low: coding
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
  keyword_fallback:
    level: high
    high_risk_keywords: [auth, authorization, billing, payment, migration, encryption, concurrency, data loss]
```

The runner records routing decisions in `state.json`, including the implementation
model, selected review passes, effective risk level, and whether manual merge is
required. The generic review stage receives the selected review passes in its prompt;
later specialized review stages can consume the same routing data.

### Specialized review

The default pipelines use a `review_group` step that runs focused review passes
selected from `risk_routing.review_passes`:

```yaml
- id: review
  type: review_group
  inputs: [requirements.md, design.md, git_diff, test_results]
  output: review.md
```

Supported passes are:

- `correctness`
- `tests`
- `architecture`
- `security`
- `migrations`
- `migration_or_rollback`
- `performance`

Each pass writes its own artifact, such as `review-correctness.md` or
`review-security.md`, with structured `yaml agentic` metadata. The runner also
aggregates pass summaries and findings into `review.md` so the existing
review-fix flow can consume one review artifact.

Blocking structured findings trigger `fix-review`. Optional findings do not block
by default. If the original review contained a blocking security finding, the
runner requires approval after `fix-review` completes.

### Repo context

Agents can receive compact repository context from `.ai/context`. Install starter
templates with:

```bash
install-agentic-skills --with-context .ai/skills
```

Then fill in the generated files for the project. Configure which files each stage
receives:

```yaml
context:
  dir: .ai/context
  requirements: []
  architecture:
    - repo-map.md
    - module-boundaries.md
    - test-commands.md
    - coding-conventions.md
    - dangerous-areas.md
    - dependency-map.md
    - ownership.md
  implementation:
    - repo-map.md
    - test-commands.md
    - coding-conventions.md
    - dangerous-areas.md
  review:
    - repo-map.md
    - module-boundaries.md
    - test-commands.md
    - coding-conventions.md
    - dangerous-areas.md
    - dependency-map.md
```

Missing context files are skipped. This keeps new projects usable before the
templates are filled in, while letting mature repos give architecture and review
agents a richer map than implementation needs.

### Repo memory

Agents can also receive read-only durable memory from `.ai/memory`. Install starter
templates with:

```bash
install-agentic-skills --with-memory .ai/skills
```

Then fill in durable lessons, decisions, known issues, recurring review comments,
and preferred patterns. Configure memory per stage:

```yaml
memory:
  dir: .ai/memory
  requirements:
    - decisions.md
    - known-issues.md
  architecture:
    - decisions.md
    - preferred-patterns.md
    - known-issues.md
  implementation:
    - preferred-patterns.md
    - lessons-learned.md
    - known-issues.md
  review:
    - recurring-review-comments.md
    - known-issues.md
    - decisions.md
```

Memory files are read-only inputs to prompts. The runner does not automatically
write or update memory; missing files are skipped.

### Evaluation records

The runner writes `.ai/runs/<run-id>/evaluation.yaml` for completed, stopped, and
failed non-dry runs. It intentionally omits cost fields.

Example shape:

```yaml
run_id: 2026-07-08-120000-add-audit-logging
task: Add audit logging
repo: my-api
branch: ai/add-audit-logging
pipeline: default
status: completed
completed_stages: [requirements, architecture, implementation, checks, review]
stages:
  requirements:
    status: ready
    confidence: 0.9
    model: claude-haiku-4-5
risk:
  level: low
routing:
  risk_level: low
  implementation_model: gpt-5.1-codex
  review_passes: [correctness, tests]
  require_manual_merge: false
checks:
  test:
    command: pnpm test
    exit_code: 0
    status: passed
outcome:
  pr_created: false
  pr_url: null
  require_manual_merge: false
```

The runner creates an `ai/<task>` branch when invoked in a Git repository. A dirty
worktree is rejected by default. GitHub uses `gh`; Gitea uses `tea`. Merge remains a
human action.

### Pull requests

When `forge.create_pr` is enabled, the runner writes `pr-body.md` and opens a pull
request through the configured forge. The generated body includes:

- task summary;
- requirements and architecture artifact links;
- risk level and reasons;
- check status;
- review artifact links;
- evaluation artifact link;
- a human notes section.

If routing requires manual merge, the PR body calls that out explicitly. The runner
does not automatically commit artifacts, commit implementation changes, or merge
PRs. Artifact commits are intentionally parked for now; if added later they should
be explicitly opt-in.
Set `forge.auto_commit_push: true` to let the runner stage repository changes,
exclude the configured artifacts directory, create an `AI: ...` commit, and push
the current branch to `origin` before opening the PR. The default remains `false`.
For Gitea, this avoids `tea` remote autodiscovery issues by using the explicit repo
slug and branch name.

## Configuration and development

Validate configuration with `validate-agentic-config`. Run tests with:

```bash
python3 -m unittest discover -s tests -v
```

Provider commands are non-interactive: Claude receives `--print --model`, while Codex
receives `exec --model ... -`. Override complete command prefixes in `providers.available`.
