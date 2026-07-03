"""In-process event bus — decoupled pub/sub with a durable SQLite outbox.

Import from the submodules (core.bus.bus, core.bus.events, core.bus.outbox);
bridges live in core.bus.bridges and api.ws_bridge and are wired in lifespan.
"""
