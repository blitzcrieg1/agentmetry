"""`agentmetry scan`: what an agent is about to depend on, checked before it runs.

The sensor records what an agent did. This answers the question a reviewer asks
before that: is the tool, skill or MCP server it is wired to shaped like an
attack. Two checks in v1, each built to say "this resembles X, look", never
"this is safe": instructions hidden in model-visible text (#188), and package
names that imitate well-known ones.

Nothing here runs a server or fetches a package. It reads configuration and
text that is already on the machine; descriptions a live server hands the model
are checked by the MCP proxy at `tools/list`, and land on the trail as counts.
"""
