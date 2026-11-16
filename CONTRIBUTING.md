# Contributing to Agentmetry

Thanks for helping build an open, local-first endpoint sensor for AI agents.
Contributions are welcome across detection rules, DLP patterns, SIEM adapters,
and dashboard UX.

## Good first contributions

These are small, self-contained, and testable. The best way in:

| Area | Where |
|------|-------|
| A new **detection rule** | `apps/orchestrator/agentmetry/core/audit/detection/rules.py`: a pure function over a session's events, plus tests in `tests/test_detection_engine.py` |
| A new **DLP pattern** | `agentmetry/policies/dlp/manifest.yaml`: regex only, no Python; add a fires/doesn't-fire test |
| A **SIEM adapter** | `apps/orchestrator/agentmetry/core/audit/sinks.py` |
| A **hook adapter** for a new IDE | [docs/agentmetry-external-ingest.md](docs/agentmetry-external-ingest.md) |
| A **Sigma rule** | [docs/integrations/sigma/](docs/integrations/sigma/) |

**The built-in detection ruleset is frozen for now.** `rules.py`, `traits.py`,
`engine.py`, `core/audit/mitre.py` and `policies/detection/manifest.yaml` are
hashed into a published fingerprint, and the "green weeks against an unchanged
ruleset" claim depends on it not moving. A new rule or a change to an existing
one is welcome as an issue first, with the event sequence it should catch;
it lands with the next planned ruleset change rather than on its own.

## Development setup

```bash
git clone https://github.com/blitzcrieg1/agentmetry.git
cd agentmetry/apps/orchestrator
python -m venv .venv && . .venv/bin/activate      # Windows: .\.venv\Scripts\activate
pip install -e ".[dev]"
```

Run the demo to confirm the pipeline works end-to-end (no server needed):

```bash
agentmetry demo     # or, without installing: python scripts/demo.py
```

## Before you open a PR

### Commit authorship (solo maintainers)

GitHub shows anyone listed in a commit trailer as a **contributor**. To keep the
repo attributed to you (and optional Claude co-authors only):

1. **Cursor:** Settings → Agent → Attribution → turn **Commit Attribution** off.
2. **Enable the repo hook** (strips `Co-authored-by: Cursor` if it slips in):

```bash
git config core.hooksPath .githooks
```

The repo ships `.githooks/prepare-commit-msg`; it removes Cursor co-author lines
and keeps other co-authors (e.g. Claude).

**Note:** Past commits already on GitHub may still list `cursoragent` until history
is rewritten. New commits after the steps above will not add Cursor as co-author.

From `apps/orchestrator`:

```bash
python -m ruff check agentmetry tests   # lint
python -m pytest -q                      # tests
```

If you touch the dashboard: `cd apps/dashboard && npm run build`.

CI runs ruff, pytest, a gitleaks secret scan, and the dashboard build on every
push. All four must pass.

## Ground rules

- **Never commit real secrets.** This is a secret-scanning project, so tests
  contain secret-*shaped* fixtures; use published non-functional examples (e.g.
  AWS's `AKIAIOSFODNN7EXAMPLE`), and if a fixture must live outside a test file,
  mark that line `gitleaks:allow`.
- **Detection rules must ship with both a fires-test and a does-not-fire test.**
  A rule that can't demonstrate it stays quiet on a benign session isn't done.
- **No default self-approve, ever.** Any change that lets an agent's gated action
  proceed without a human decision will be declined.
- **Keep the trail honest.** The canonical JSONL schema is a contract, so extend it
  additively; don't rename or repurpose existing fields.
- Match the surrounding code style; keep changes focused and reviewable.

## Reporting security issues

Do **not** open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## Contributor License Agreement (CLA)

All pull requests require a signed **[Individual CLA (CLA.md)](CLA.md)** before merge.

1. Open your pull request.
2. If you have not signed before, the maintainer will ask you to sign in a comment.
3. Reply on the pull request with exactly: **`I have read the CLA Document and I hereby sign the CLA`**
4. The maintainer records your GitHub username, and a link to that comment, in
   `signatures/version1/cla.json` on the `cla-signatures` branch. You sign once.

**What you are agreeing to:** You retain copyright in your contribution. You grant
the Project Owner (blitzcrieg1) the rights in CLA.md, including use under
**Apache 2.0** and the **right to relicense** your contribution under other terms
(including commercial licenses). See the plain-language summary at the top of
CLA.md.

**Employer contributions:** If you contribute on behalf of a company, your employer
must approve via [CCLA.md](CCLA.md) or an equivalent written authorization.

**AI-assisted contributions:** You are responsible for reviewing and licensing any
code you submit, including output from generative AI tools (CLA.md §7).

We do **not** require Developer Certificate of Origin (DCO) sign-off; the CLA
covers inbound licensing.

## Maintainer: checking the CLA

There is no CLA bot. The `contributor-assistant/github-action` workflow ran
until 2026-11-16, when the archived action stopped starting, and it was removed
rather than kept failing on every pull request. Signatures it collected are on
the `cla-signatures` branch and stay valid.

Before merging a pull request from anyone not in
`signatures/version1/cla.json` on that branch:

1. Ask them to reply with the sentence above, and wait for it.
2. Add an entry to `cla.json` in the same shape as the existing ones (`name`,
   `id`, `comment_id`, `created_at`, `repoId`, `pullRequestNo`) and commit it to
   `cla-signatures`.
3. Then merge. Dependabot needs no signature.

See also [COMMERCIAL.md](COMMERCIAL.md) for non-binding commercial-licensing intent.
