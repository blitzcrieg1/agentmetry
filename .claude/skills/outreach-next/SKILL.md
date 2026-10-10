---
name: outreach-next
description: Report the next Agentmetry outreach message to send and its exact text. Use when the user asks what commercial work is next, about the pipeline, design partners, sales, or which opener to send.
---

# Outreach next

This is the department that has shipped nothing. Treat it accordingly.

## Read, do not invent

```
../agentmetry-enterprise/sales/outreach-log.md  the queue, recipients, status, replies (private repo)
docs/commercial/outreach-openers.md              the six openers and the sending order (public)
```

The log holds **named recipients with real contact details**, which is why it
lives in the private repo. Never copy a name, an address or a reply into this
public repo, including into this skill. Do not invent a
recipient, do not substitute a different company, and do not rewrite an opener
into something more enthusiastic. Each opener is built around one checkable
fact and states a limitation before asking for anything. That structure is the
reason it works.

## Report

1. The **next unsent** row in the queue: opener number, person, channel
2. Its **exact text**, ready to paste
3. Anything in it that needs verifying before it goes out
4. The current sent/reply count, honestly. It has been zero for a while

## Verify before sending

The openers cite specific published work, and the whole approach collapses if a
detail is wrong. Your own rules say a first line that misquotes the thing you
claim to have read is worse than a generic one.

Check, every time:

- **The affiliation** of any academic recipient. arXiv abstract pages often
  carry no affiliations at all, and the paper's PDF is the place to confirm
  them. Do not send an academic an email that misplaces them.
- **The link resolves** and says what the opener claims it says
- **Any technique id** against the source. `AML.T0109` is the MCP rug pull;
  `AML.T0051.001` is indirect prompt injection

## Sending order, and the reasoning behind it

Openers **2 and 5 first**. Both go to people who already published on the topic,
and both ask for criticism rather than a meeting. That is a smaller thing to
grant and a more useful thing to receive: being told the rug-pull logic or the
ATLAS mapping is wrong is worth more right now than a call that goes nowhere.
Neither costs anything if ignored.

**3 next**, with the Splunk SPL attached, because detection engineers respond to
artefacts rather than pitches.

**1, 4 and 6 last.** They are the actual revenue paths and the slowest, and they
land better once there is something concrete to reference.

Do not reorder this without saying why. An earlier audit recommended starting
with opener 1 and did not engage with the argument above; that was wrong.

## After a send

Update the row in the private `outreach-log.md` with the date and channel. Record the reply
verbatim when one arrives, including a rejection. The point of the log is that
the next revision is informed by what happened rather than by what sounded good.

## What this skill will not do

**It will not send anything.** No email or messaging tool is available in this
session, and outreach on someone's behalf is theirs to press send on regardless.
Prepare it, verify it, hand it over.
