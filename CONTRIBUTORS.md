# Contributors

Every number here comes from `git log` and can be reproduced from a clone.

## Maintainer

**Ioannis Loutsis** ([@blitzcrieg1](https://github.com/blitzcrieg1)), 486 commits.

Those commits were authored under three git identities, one of them the default
placeholder `your-email@example.com`. [`.mailmap`](.mailmap) folds them into one
without rewriting history.

## External contributors

**[@hvadlamani1](https://github.com/hvadlamani1)** ([#126]), 2026-08-27: three
DLP rules for Stripe, Anthropic and generic provider API keys, with six tests.

Three of those tests are near-misses: `sk_live_abc123` and `echo sk-test` have
to stay *silent*, because a rule that fires on every mention of a key prefix in
a comment is worse than no rule. Writing the near-miss without being asked is
the thing this project cares most about in a detection contribution.

**[@jeetsingh008](https://github.com/jeetsingh008)** ([#30]), 2026-07-29:
[`e9a1b9c`](https://github.com/blitzcrieg1/agentmetry/commit/e9a1b9c), a neutral
Windows path in an ingest client test fixture.

That is the complete list. It is short, and it is listed by name rather than
summarised, because two outside contributions on a single-maintainer project
are two more than none and both are easier to lose than to add.

```bash
git shortlog -sne --all
```

## Automation

`dependabot[bot]` (20) and `github-actions[bot]` (4) appear in the history.
Dependency bumps are reviewed and merged by hand, including the ones that are
declined: see the closed pull requests for why several major bumps were not
taken.

## AI assistance

**382 of 511 commits carry a `Co-Authored-By` trailer** naming the model that
helped write them.

| Co-author | Commits |
|---|---|
| Cursor | 130 |
| Claude Opus 4.8 | 95 |
| Claude Fable 5 | 82 |
| Claude Opus 5 | 75 |

This is disclosed rather than mentioned, because a project whose product is an
audit trail should be able to answer the question about its own history. The
trailers are in the commits and were there before anybody asked.

Every commit was reviewed and merged by the maintainer, `master` is protected
with required checks, and the test suite and detection benchmark gate the
merge. Authorship assistance is not the same as unreviewed code.

```bash
git log --format="%(trailers:key=Co-Authored-By,valueonly)" | sort | uniq -c
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most useful contributions are small
and testable: detection rules, DLP patterns, SIEM adapters, YAML rules and
benchmark corpus cases.

A case that makes a rule fire when it should not is worth more than a case that
confirms it works. Four such reports arrived from strangers on r/mcp in August
2026 and became issues [#103] through [#106], [#111], [#112] and [#120]; three
shipped in 0.6.0 and 0.7.0. That is the highest-value thing anyone can send.

[#30]: https://github.com/blitzcrieg1/agentmetry/pull/30
[#126]: https://github.com/blitzcrieg1/agentmetry/pull/126
[#103]: https://github.com/blitzcrieg1/agentmetry/issues/103
[#106]: https://github.com/blitzcrieg1/agentmetry/issues/106
[#111]: https://github.com/blitzcrieg1/agentmetry/issues/111
[#112]: https://github.com/blitzcrieg1/agentmetry/issues/112
[#120]: https://github.com/blitzcrieg1/agentmetry/issues/120
