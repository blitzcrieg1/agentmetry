# Design partner outreach

These are the cold openers used to find design partners for the 90-day pilot.

They are published, in the public repository, on purpose. If one of them lands
in your inbox you can read the reasoning that produced it, check the numbers it
cites, and see the other five. A message that only works when the recipient
cannot see how it was constructed is not a message worth sending, and a company
selling evidence should not run a sales process it would rather you did not read.

Nothing here is a template with your company name substituted in. Each opener
targets a different reason someone would need this, and most of them will be
wrong for most people.

**Status as of 2026-08-22: none sent yet.** Recipients and copy-ready bodies
for openers **#2** and **#5** are in [outreach-log.md](./outreach-log.md).
No reply data yet. Treat the sequencing below as reasoning rather than evidence.

## The offer they point at

90 days, up to 25 seats, MSI and Intune deployment, the Splunk TA, and 4 hours
of direct maintainer time. Fee in the SOW. No demo gate. See
[the pilot page](https://agentmetry.ai/pilot). Contact: `legal@agentmetry.ai`.

## Rules any edit must keep

Every opener states a limitation before asking for anything. This is not
modesty, it is the fastest way to establish that the rest of the message is
accurate. A security buyer who finds one overstatement stops reading, and a
recorder that oversells its coverage is selling the exact failure it exists to
catch.

- **Name the Tier C gap.** Unmanaged ChatGPT, Copilot, and an IDE with hooks
  removed are invisible. Agentmetry sees what it orchestrates. Say so before
  they ask.
- **One checkable fact per message.** A number, a technique id, a file path.
  Something the reader can verify in under a minute without replying.
- **No em-dashes.** House style for anything published.
- **Do not lead with "Agentic OS".** That framing belongs in the README and in
  investor conversations, not in a cold first line.
- **Ask for something smaller than a meeting** wherever the segment allows it.

---

## 1. Fleet rollout, SOC has no visibility

**Who:** security engineering at a company that has rolled out Cursor, Claude
Code or Copilot to a development team. **Trigger:** a public post, job ad, or
conference talk mentioning the rollout.

> **Subject: your Cursor rollout and what your SIEM sees**
>
> You rolled out Cursor to engineering. Your EDR sees `python` spawning `curl`.
> It does not see which developer prompted it, which agent invoked it, or
> whether the result left through an MCP server.
>
> I build a local-first recorder that sits at the tool boundary and forwards
> into the SIEM you already run. No vendor cloud, Apache-2.0, the trail stays on
> the laptop.
>
> Honest limit up front: it only sees agents it hooks. Unmanaged ChatGPT and a
> Cursor with hooks switched off stay invisible. That is CASB territory and I do
> not claim it.
>
> Running a 90-day design partner pilot, 25 seats, MSI and Intune. Worth 20
> minutes?

## 2. MCP supply chain

**Who:** anyone who has written publicly about `postmark-mcp` or MCP server
trust. **Trigger:** their own post. This is the warmest of the six.

> **Subject: the postmark-mcp gap, in one field**
>
> You wrote about postmark-mcp. The part that stuck with me: fifteen clean
> releases before the one that mattered, and the config file identical
> throughout.
>
> I fingerprint the `tools/list` schema per session. When the schema digest
> moves while the config digest holds still, that is the rug pull, and it is an
> event rather than a blog post. MITRE ATLAS calls it AML.T0109.
>
> Not selling you anything in this message. If the detection logic is wrong I
> would rather hear it from you than from a customer.
>
> `github.com/blitzcrieg1/agentmetry`

## 3. Detection engineer, Splunk shop

**Who:** detection engineering, security operations. **Trigger:** they publish
detection content, or work somewhere that does.

> **Subject: SPL for agent tool calls, if you want it**
>
> Do you have detection content for what your coding agents do? Most shops I ask
> have ATT&CK coverage for the host and nothing for the agent session above it.
>
> I ship the SPL rather than a dashboard. Seven searches,
> `sourcetype=agentmetry:json`, plus a TA. You keep Splunk as the console; I am
> only the sensor.
>
> The benchmark is 50 sessions, 26 attack and 24 benign. The benign half is the
> number I care about.
>
> Happy to send the searches with no call attached.

## 4. Regulated, EU AI Act Article 12

**Who:** compliance-adjacent security leadership in an EU-regulated
organisation. **Trigger:** an Article 12 readiness programme.

> **Subject: Article 12 logging for coding agents**
>
> Article 12 wants automatic recording of events over an AI system's lifetime.
> For coding agents most teams have model API logs, which is the wrong layer:
> they show the prompt, not what the agent did to the repository.
>
> I record the tool boundary to a hash-chained JSONL trail with RFC 6962
> inclusion proofs. A 1.2 KB proof against an 8.3 MB trail, verifiable by a
> third party who does not trust me.
>
> The honest boundary: it is tamper-evident, not attributable. Anyone with write
> access can build a valid chain from scratch. Per-host signing is not shipped.
>
> If Article 12 is on your 2027 list, worth a conversation now.

## 5. Prompt injection researchers

**Who:** people publishing on agent security, prompt injection, or agent data
injection. **Trigger:** their paper or talk. Treat as a peer message, not a
prospect.

> **Subject: labelling ADI with ATLAS, and where it breaks**
>
> I map the arXiv:2607.05120 chain to AML.T0051.001, indirect prompt injection,
> on the detection rather than the tool call, because the sequence is the
> evidence and no single call is.
>
> The rule is deliberately weak: content from a channel the model did not
> control, then an already-risky action. It cannot prove intent and the label
> does not claim to.
>
> I mapped 5 ATLAS techniques out of 178. About 3%, published as 3%, because a
> sensor that labels everything has labels that mean nothing.
>
> Would value you telling me the mapping is wrong.

## 6. Consultancy running agents on client code

**Who:** dev shops and consultancies billing for agent-assisted work.
**Trigger:** they advertise AI-assisted delivery.

> **Subject: proving what your agents did on a client repo**
>
> When agents write code on a client's repository, the question that eventually
> arrives is what exactly ran, when, and whether anything left the machine. A
> git history does not answer it.
>
> I record every tool call locally, hash-chained, on your machines rather than a
> vendor's. Client data never reaches me because there is no me in the path.
>
> The limit worth naming: it records, it does not prevent. Blocking is opt-in
> and only works at the hook boundary before a tool runs.
>
> 90-day pilot, 25 seats. If you are billing for agent-assisted work this is the
> artefact that backs the invoice.

---

## Sending order, and why

**2 and 5 first.** Both are peer messages to people who already published on the
topic. Both ask for criticism rather than a meeting, which is a smaller thing to
grant and a more useful thing to receive: being told the rug-pull logic or the
ATLAS mapping is wrong is worth more right now than a call that goes nowhere.
Neither costs anything if ignored.

**3 next.** Detection engineers respond to artefacts rather than to pitches.
Attach the SPL from
[detections-splunk.md](../integrations/detections-splunk.md) and let it carry
the message.

**1, 4 and 6 last.** These are the actual revenue paths and the slowest ones.
Send them once at least one of the first three has replied, so there is
something concrete to reference rather than a cold claim.

## What to record

Sent date, segment, whether the checkable fact was engaged with, and the reply
if any. The point of publishing these is that the next revision is informed by
what happened rather than by what sounded good, and right now the sample size is
zero.
