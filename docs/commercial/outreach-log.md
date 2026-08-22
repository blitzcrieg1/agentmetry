# Outreach log

Track sends and replies. The openers live in [outreach-openers.md](./outreach-openers.md).
Pilot offer: [agentmetry.ai/pilot](https://agentmetry.ai/pilot) · Contact: `legal@agentmetry.ai`.

---

## Queue (send in order)

| Priority | Opener | Recipient | Channel | Status |
|---|---|---|---|---|
| 1 | **#2 MCP supply chain** | Liran Tal (Snyk) | LinkedIn or Snyk contact | **Ready** |
| 2 | **#5 ADI / ATLAS** | Luyi Xing (UIUC) | `lxing2@illinois.edu` | **Ready** |
| 3 | **#2** (alt) | Idan Dardikman (Koi Security) | LinkedIn / Koi | **Ready** |
| 4 | **#5** (alt) | Byoungyoung Lee (SNU) | `byoungyoung@snu.ac.kr` | **Ready** |
| 5 | **#3 Splunk SPL** | (pick after one peer reply) | — | Hold |

---

## Opener #2 — ready to send (Liran Tal / Snyk)

**Why this person:** Wrote [Snyk's postmark-mcp analysis](https://snyk.io/blog/malicious-mcp-server-on-npm-postmark-mcp-harvests-emails/) (Sep 2025); maintains mcp-scan lineage.

**Subject:** the postmark-mcp gap, in one field

```
You wrote about postmark-mcp. The part that stuck with me: fifteen clean
releases before the one that mattered, and the config file identical
throughout.

I fingerprint the tools/list schema per session. When the schema digest
moves while the config digest holds still, that is the rug pull, and it
is an event rather than a blog post. MITRE ATLAS calls it AML.T0109.

Not selling you anything in this message. If the detection logic is wrong
I would rather hear it from you than from a customer.

github.com/blitzcrieg1/agentmetry
```

| Field | Value |
|---|---|
| Sent | |
| Engaged with checkable fact? | |
| Reply | |

---

## Opener #5 — ready to send (Luyi Xing / UIUC)

**Why this person:** Co-author, [arXiv:2607.05120](https://arxiv.org/abs/2607.05120) Agent Data Injection.

**Subject:** labelling ADI with ATLAS, and where it breaks

```
I map the arXiv:2607.05120 chain to AML.T0051.001, indirect prompt
injection, on the detection rather than the tool call, because the
sequence is the evidence and no single call is.

The rule is deliberately weak: content from a channel the model did not
control, then an already-risky action. It cannot prove intent and the
label does not claim to.

I mapped 5 ATLAS techniques out of 178. About 3%, published as 3%,
because a sensor that labels everything has labels that mean nothing.

Would value you telling me the mapping is wrong.
```

| Field | Value |
|---|---|
| Sent | |
| Engaged with checkable fact? | |
| Reply | |

---

## Opener #2 — alt (Idan Dardikman / Koi Security)

**Why:** [The Register quote](https://www.theregister.com/security/2025/09/29/fake-postmark-mcp-npm-package-stole-emails-with-one-liner/509095) on MCP ecosystem warning shot.

Same body as #2 above. Adjust opening line if you reference his quote specifically:

```
Your line about postmark-mcp being a warning shot about the MCP ecosystem
is the framing I use for runtime schema fingerprinting...
```

| Field | Value |
|---|---|
| Sent | |
| Reply | |

---

## Weekly dogfood (do not skip while 2 of 4)

| Week ending | GREEN? | events | detections | notes |
|---|---|---|---|---|
| 2026-08-08 | yes | | | week 1 |
| 2026-08-15 | yes | | | week 2 |
| 2026-08-22 | | | | week 3 in progress |
| 2026-08-29 | | | | |

Command: `agentmetry stats --days 7`

---

## Beta gate progress

| Gate | Status |
|---|---|
| 4 green dogfood weeks | 2 of 4 |
| verify --trail in README | done |
| doctor on 3 Win11 machines | 1 of 3 |
| Public claims match shipped | done |
