"""Agentmetry: a local-first flight recorder for AI coding agents.

Everything lives under this one top-level package on purpose. The orchestrator
used to ship `core`, `api` and `cli` as top-level names, which is harmless for an
editable install inside this repo and antisocial once published: three of the
most generic importable names in Python, dropped into someone else's
site-packages, where they collide with whatever else claims them.
"""

from agentmetry.core.version import __version__

__all__ = ["__version__"]
