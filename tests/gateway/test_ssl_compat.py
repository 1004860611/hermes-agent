"""Regression tests for gateway TLS startup compatibility."""

from __future__ import annotations

import ssl
import sys
import types
from types import SimpleNamespace

import pytest

from gateway import ssl_compat


def _truncated_cert_error() -> ssl.SSLError:
    return ssl.SSLError(1, "[ASN1: NOT_ENOUGH_DATA] not enough data (_ssl.c:4057)")


def test_individual_windows_store_loader_skips_only_truncated_cert(monkeypatch):
    good_cert = b"good-der"
    bad_cert = b"bad-der"
    purpose = SimpleNamespace(oid="server-auth")

    monkeypatch.setattr(
        ssl,
        "enum_certificates",
        lambda _store: [
            (bad_cert, "x509_asn", True),
            (good_cert, "x509_asn", {"server-auth"}),
            (b"ignored", "pkcs_7_asn", True),
        ],
        raising=False,
    )

    class Context:
        def __init__(self):
            self.loaded = []

        def load_verify_locations(self, *, cadata):
            if cadata == bad_cert:
                raise _truncated_cert_error()
            self.loaded.append(cadata)

    context = Context()
    ssl_compat._warned_about_malformed_windows_certs = False

    loaded = ssl_compat._load_windows_store_certs_individually(
        context, "ROOT", purpose
    )

    assert context.loaded == [good_cert]
    assert loaded == bytearray(good_cert)


def test_individual_windows_store_loader_preserves_other_ssl_errors(monkeypatch):
    monkeypatch.setattr(
        ssl,
        "enum_certificates",
        lambda _store: [(b"cert", "x509_asn", True)],
        raising=False,
    )

    class Context:
        def load_verify_locations(self, *, cadata):
            raise ssl.SSLError("certificate verify failed")

    with pytest.raises(ssl.SSLError, match="certificate verify failed"):
        ssl_compat._load_windows_store_certs_individually(
            Context(), "ROOT", SimpleNamespace(oid="server-auth")
        )


def test_windows_fallback_is_installed_only_for_truncated_asn1(monkeypatch):
    def original_loader(_context, _storename, _purpose):
        return bytearray()

    calls = 0

    def create_context():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _truncated_cert_error()
        return object()

    monkeypatch.setattr(ssl_compat.sys, "platform", "win32")
    monkeypatch.setattr(ssl, "create_default_context", create_context)
    monkeypatch.setattr(
        ssl.SSLContext,
        "_load_windows_store_certs",
        original_loader,
        raising=False,
    )

    assert ssl_compat._install_windows_cert_store_fallback() is True
    assert ssl.SSLContext._load_windows_store_certs is not original_loader
    assert getattr(
        ssl.SSLContext._load_windows_store_certs,
        ssl_compat._WINDOWS_CERT_LOADER_MARKER,
    ) is True
    assert calls == 2


def test_windows_fallback_does_not_mask_unrelated_ssl_error(monkeypatch):
    def original_loader(_context, _storename, _purpose):
        return bytearray()

    monkeypatch.setattr(ssl_compat.sys, "platform", "win32")
    monkeypatch.setattr(
        ssl.SSLContext,
        "_load_windows_store_certs",
        original_loader,
        raising=False,
    )
    monkeypatch.setattr(
        ssl,
        "create_default_context",
        lambda: (_ for _ in ()).throw(ssl.SSLError("wrong version number")),
    )

    assert ssl_compat._install_windows_cert_store_fallback() is False
    assert ssl.SSLContext._load_windows_store_certs is original_loader


def test_ensure_gateway_ssl_certs_keeps_explicit_bundle_and_hardens_windows(
    monkeypatch, tmp_path
):
    bundle = tmp_path / "corp-ca.pem"
    bundle.write_text("placeholder", encoding="utf-8")
    hardened = []
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.setattr(
        ssl_compat,
        "_install_windows_cert_store_fallback",
        lambda: hardened.append(True) or True,
    )

    ssl_compat.ensure_gateway_ssl_certs()

    assert __import__("os").environ["SSL_CERT_FILE"] == str(bundle)
    assert hardened == [True]


def test_gateway_cli_prepares_ssl_before_plugin_discovery(monkeypatch):
    from hermes_cli import main as main_mod

    events = []
    monkeypatch.setattr(
        ssl_compat,
        "ensure_gateway_ssl_certs",
        lambda: events.append("ssl"),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.plugins",
        types.SimpleNamespace(discover_plugins=lambda: events.append("plugins")),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.config",
        types.SimpleNamespace(load_config=lambda: {}),
    )
    monkeypatch.setitem(
        sys.modules,
        "agent.shell_hooks",
        types.SimpleNamespace(register_from_config=lambda *_args, **_kwargs: None),
    )

    main_mod._prepare_agent_startup(
        SimpleNamespace(
            command="gateway",
            gateway_command="run",
            yolo=False,
            safe_mode=False,
            accept_hooks=False,
            tui=False,
        )
    )

    assert events == ["ssl", "plugins"]
