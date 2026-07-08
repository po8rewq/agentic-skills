# Changelog

## Unreleased

- Added config-driven risk routing for implementation model selection.
- Added review-pass planning from architecture risk metadata.
- Recorded routing decisions in run state.
- Preserved explicit `--model` overrides over automatic risk routing.
- Added enum validation for gate and risk metadata.
- Added optional context and memory template installation.
- Added stage-specific repo context loading for pipeline prompts.
- Added cost-free `evaluation.yaml` run summaries.
- Added stage-specific read-only repo memory loading for pipeline prompts.
- Added specialized review skill contracts for correctness, tests, architecture, security, migrations, and performance.
- Added `review_group` orchestration for risk-selected specialized review passes.
- Added structured review finding blocking behavior with security approval after fixes.
- Generated richer PR bodies with artifact links, risk, checks, review artifacts, evaluation, and human notes.

## 0.1.0 - 2026-07-07

- Initial requirements-to-PR pipeline.
- Claude Code and Codex providers.
- GitHub and Gitea forge adapters.
- Approval gates, resumable audit artifacts, checks, review fixes, and risk routing.
