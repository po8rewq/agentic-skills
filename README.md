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

1. `agentic.yaml`, copied manually from `agentic.example.yaml` and customized for the
   project.
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

The shared Python package supplies the orchestrator and its scripts. This avoids
maintaining duplicate script copies in every project, while vendoring the Markdown
skills allows each project to pin or customize its agent behavior.

Edit `agentic.yaml` for the project's commands, providers, gates, and forge. Vendored
skills default to `.ai/skills`; the installed package's shared skills are used when no
local override is configured.

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
completed stages. High-risk task keywords automatically escalate architecture,
implementation, and review to the configured best model.

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

Gate behavior:

- `status: blocked` stops the pipeline before implementation.
- `status: risky` requires human approval.
- architecture `risk.level: high` or `risk.level: critical` requires human approval.

`--skip-approval` bypasses approval prompts for non-interactive runs, but it does
not bypass `blocked` gates.

The runner creates an `ai/<task>` branch when invoked in a Git repository. A dirty
worktree is rejected by default. GitHub uses `gh`; Gitea uses `tea`. Merge remains a
human action.

## Configuration and development

Validate configuration with `validate-agentic-config`. Run tests with:

```bash
python3 -m unittest discover -s tests -v
```

Provider commands are non-interactive: Claude receives `--print --model`, while Codex
receives `exec --model ... -`. Override complete command prefixes in `providers.available`.
