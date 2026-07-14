# Contributing to Agentmetry

Thanks for helping build an open, local-first flight recorder for AI agents.
Contributions are welcome across detection rules, DLP patterns, SIEM adapters,
and dashboard UX.

## Good first contributions

These are small, self-contained, and testable — the best way in:

| Area | Where |
|------|-------|
| A new **detection rule** | `apps/orchestrator/core/audit/detection/rules.py` — a pure function over a session's events, plus tests in `tests/test_detection_engine.py` |
| A new **DLP pattern** | `policies/dlp/manifest.yaml` — regex only, no Python; add a fires/doesn't-fire test |
| A **SIEM adapter** | `apps/orchestrator/core/audit/sinks.py` |
| A **hook adapter** for a new IDE | [docs/agentmetry-external-ingest.md](docs/agentmetry-external-ingest.md) |
| A **Sigma rule** | [docs/integrations/sigma/](docs/integrations/sigma/) |

## Development setup

```bash
git clone https://github.com/blitzcrieg1/agentmetry.git
cd agentmetry/apps/orchestrator
python -m venv .venv && . .venv/bin/activate      # Windows: .\.venv\Scripts\activate
pip install -e ".[dev]"
```

Run the demo to confirm the pipeline works end-to-end (no server needed):

```bash
python scripts/demo.py
```

## Before you open a PR

From `apps/orchestrator`:

```bash
python -m ruff check core api tests      # lint
python -m pytest -q                      # tests
```

If you touch the dashboard: `cd apps/dashboard && npm run build`.

CI runs ruff, pytest, a gitleaks secret scan, and the dashboard build on every
push. All four must pass.

## Ground rules

- **Never commit real secrets.** This is a secret-scanning project, so tests
  contain secret-*shaped* fixtures — use published non-functional examples (e.g.
  AWS's `AKIAIOSFODNN7EXAMPLE`), and if a fixture must live outside a test file,
  mark that line `gitleaks:allow`.
- **Detection rules must ship with both a fires-test and a does-not-fire test.**
  A rule that can't demonstrate it stays quiet on a benign session isn't done.
- **No default self-approve, ever.** Any change that lets an agent's gated action
  proceed without a human decision will be declined.
- **Keep the trail honest.** The canonical JSONL schema is a contract — extend it
  additively; don't rename or repurpose existing fields.
- Match the surrounding code style; keep changes focused and reviewable.

## Reporting security issues

Do **not** open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree your contributions are licensed under Apache-2.0.
