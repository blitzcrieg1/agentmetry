# Commercial licensing intent (non-binding)

This document describes the **Project Owner's current intent** for Agentmetry
commercialization. It is **not a contract** and does not change the Apache 2.0
license on the open-source code.

## What stays open source

- The core flight recorder, hook client, MCP audit proxy, detection engine, DLP
  manifest format, and SIEM forwarders in this repository are intended to remain
  available under **Apache 2.0**, subject to the [CLA](CLA.md).

See the full boundary table in **[Open-core split](docs/commercial/open-core-split.md)**
(Apache 2.0 sensor vs. proprietary enterprise add-ons).

## Current Enterprise terms

Agentmetry Enterprise is a separate proprietary package. Use, modification and
distribution require a written license agreement with the Project Owner. ELv2
has not been adopted. Customer rights are defined by the applicable written
agreement, not by this intent document.

The Project Owner may offer Enterprise as a hosted fleet console or for
deployment in customer-owned environments under written agreements. The
open-source sensor stays local-first and Apache 2.0; it requires no Enterprise
agreement to use under that license.

## Extension mechanism

Commercial add-ons ship as a separate Python package (`agentmetry-enterprise`) that
registers via standard entry points (`agentmetry.extensions`). The orchestrator
loads extensions at startup when the package is installed; the OSS quickstart is
unchanged when it is not. See `core/extensions.py`.

## What may be offered commercially (future)

The Project Owner may offer paid offerings such as:

- Enterprise support and SLAs
- Certified or long-term-support builds
- Managed deployment assistance in **customer-owned** environments
- Hosted Enterprise fleet console under a written commercial agreement
- Additional connectors, dashboards, or compliance packs under separate license

## Dual-licensing

Contributors sign the [CLA](CLA.md), which grants the Project Owner the right to
relicense contributions. A future **enterprise or copyleft license** may apply
to specific add-on products without revoking Apache 2.0 on the existing open-source
tree, subject to legal review and community notice.

## Trademark

"Agentmetry" is a trademark of the Project Owner. Commercial use of the name is
governed by [TRADEMARK.md](TRADEMARK.md). Open-source use of unmodified software
may refer to the project as Agentmetry.

## Contact

Commercial or licensing inquiries: **contact@agentmetry.ai**
