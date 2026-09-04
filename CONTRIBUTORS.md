# Contributors

Every number here is counted on `master`, which is what a clone gives you, and
each one is printed by the command beside it.

That sentence used to be untrue. See "A correction" at the end.

Counted on 2026-09-03. Unlike the corpus figures in the README, commit counts
move with every commit, so a test that pinned them would fail on the next one.
They are stamped with a date instead, and the command beside each is the current
answer.

## Maintainer

**Ioannis Loutsis** ([@blitzcrieg1](https://github.com/blitzcrieg1)), 395 of the
414 commits on `master`.

Those commits carry two spellings of the same name against one email address.
[`.mailmap`](.mailmap) folds them into one without rewriting history.

```bash
git shortlog -sne HEAD
```

## External contributors

**[@hvadlamani1](https://github.com/hvadlamani1)** ([#126]), merged 2026-08-27:
three DLP rules for Stripe, Anthropic and generic provider API keys, with six
tests.

Two of those six are near-misses: `sk_live_abc123` and `echo sk-test` have to
stay *silent*, because a rule that fires on every mention of a key prefix in a
comment is worse than no rule. Writing the near-miss without being asked is the
thing this project cares most about in a detection contribution.

**[@jeetsingh008](https://github.com/jeetsingh008)** ([#30]), merged 2026-07-29:
[`e9a1b9c`](https://github.com/blitzcrieg1/agentmetry/commit/e9a1b9c), a neutral
Windows path in an ingest client test fixture.

That is the complete list of merged external code. It is short, and it is listed
by name rather than summarised, because two outside contributions on a
single-maintainer project are two more than none and both are easier to lose
than to add.

### In flight

**[@kkkhs](https://github.com/kkkhs)** has sent two pull requests. [#145] adds
benign corpus coverage and is open. [#140] added a detection disposition command
and was finished before it was closed unmerged on 2026-09-02, with the
contributor licence agreement as the blocker. That is a cost this project's
process imposes on the contributor, not a shortcoming of the contribution, and
it is recorded here because a finished piece of work should not vanish from the
history of who helped.

**[@hossainzarif23](https://github.com/hossainzarif23)** has [#139] open, a
`detections` command for triage.

Thank you to all four. If you are reading this and wondering whether a small
patch is worth sending: it is, and the list above is short enough that yours
would be visible.

## Automation

`dependabot[bot]` has 17 commits on `master`. Dependency bumps are reviewed and
merged by hand, including the ones that are declined: see the closed pull
requests for why several major bumps were not taken.

`github-actions[bot]` has commits in this repository but none of them are on
`master`, so it is not in the count above.

## AI assistance

**264 of the 414 commits on `master` carry at least one `Co-Authored-By`
trailer** naming the model that helped write them. The trailers total 271,
because seven commits name two models.

| Co-author | Trailers |
|---|---|
| Claude Opus 5 | 86 |
| Cursor | 77 |
| Claude Opus 4.8 | 67 |
| Claude Fable 5 | 41 |

This is disclosed rather than mentioned, because a project whose product is an
audit trail should be able to answer the question about its own history. The
trailers are in the commits and were there before anybody asked.

Every commit was reviewed and merged by the maintainer, `master` is protected
with required checks, and the test suite and detection benchmark gate the
merge. Authorship assistance is not the same as unreviewed code.

```bash
git rev-list --count HEAD
git log --format="%(trailers:key=Co-Authored-By,valueonly)" | sort | uniq -c
```

## A correction

Until 2026-09-03 this file published **382 of 511 commits**, with a maintainer
count of 486, dependabot at 20 and `github-actions[bot]` at 4. Every one of
those numbers was wrong, in three separate ways, and the command printed beside
them did not produce them.

**They were counted across every ref rather than `master`.** This clone holds a
`backup-pre-rewrite` branch and a `refs/original/` backup from a history
rewrite, which together hold a second copy of 116 July 2026 commits, plus around
twenty stale local branches. None of that is pushed. So the larger numbers were
not merely inflated, they were **impossible for anyone else to reproduce**: a
reviewer running the published command on their own clone would get 414, not
511, and would have no way to tell why.

**382 was a count of trailer lines, not of commits.** It was the sum of the four
rows in the table. Seven commits carry two trailers, so the number of commits is
lower than the number of trailers, and the sentence said commits.

**The mailmap note was stale.** It described folding a placeholder
`your-email@example.com` identity into the maintainer's, and that identity does
not appear on `master` at all any more, because the rewrite fixed the author
field. The mailmap still earns its place for the two name spellings, but the
reason it gave was no longer the reason.

It is recorded here rather than quietly edited because the argument this project
makes to everyone else is that a published number should come from a command
anybody can run, and this file was the one place that was not true. It was found
while re-verifying figures for a grant application that cites this file as
evidence, which is roughly the worst place to find it and the best reason to
write it down.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most useful contributions are small
and testable: detection rules, DLP patterns, SIEM adapters, YAML rules and
benchmark corpus cases.

A case that makes a rule fire when it should not is worth more than a case that
confirms it works. Four such reports arrived from strangers on r/mcp in August
2026 and became issues [#103] through [#106], [#111], [#112] and [#120]. Two of
those seven are closed and shipped, in 0.6.0 and 0.7.0. The other five are open,
and they stay open with the original critique attached, because an issue that
records why the first design was wrong is worth more than a tidy tracker.

[#30]: https://github.com/blitzcrieg1/agentmetry/pull/30
[#126]: https://github.com/blitzcrieg1/agentmetry/pull/126
[#139]: https://github.com/blitzcrieg1/agentmetry/pull/139
[#140]: https://github.com/blitzcrieg1/agentmetry/pull/140
[#145]: https://github.com/blitzcrieg1/agentmetry/pull/145
[#103]: https://github.com/blitzcrieg1/agentmetry/issues/103
[#106]: https://github.com/blitzcrieg1/agentmetry/issues/106
[#111]: https://github.com/blitzcrieg1/agentmetry/issues/111
[#112]: https://github.com/blitzcrieg1/agentmetry/issues/112
[#120]: https://github.com/blitzcrieg1/agentmetry/issues/120
