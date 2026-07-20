"""Extension loader — OSS path with no enterprise package installed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.extensions import EXTENSION_GROUP, get_extension_registry, load_extensions


def test_load_extensions_empty_when_none_installed():
    app = MagicMock()
    settings = MagicMock()

    with patch("core.extensions._iter_extension_entry_points", return_value=[]):
        registry = load_extensions(app, settings=settings)

    assert registry.loaded == []
    assert get_extension_registry().summary() == {"count": 0, "extensions": []}


def test_load_extensions_invokes_entry_point():
    app = MagicMock()
    settings = MagicMock()
    register_fn = MagicMock()

    ep = MagicMock()
    ep.name = "test-plugin"
    ep.value = "fake_plugin.register:register"
    ep.module = "fake_plugin.register"
    ep.load.return_value = register_fn

    with patch("core.extensions._iter_extension_entry_points", return_value=[ep]):
        with patch("core.extensions._distribution_for_module", return_value="1.2.3"):
            registry = load_extensions(app, settings=settings)

    register_fn.assert_called_once_with(app, settings=settings)
    assert len(registry.loaded) == 1
    assert registry.loaded[0].name == "test-plugin"
    assert registry.summary()["count"] == 1


def test_extension_group_name():
    assert EXTENSION_GROUP == "agentmetry.extensions"
