"""TLS certificate bootstrap helpers for the gateway.

The gateway imports HTTP stacks during plugin discovery, before platform
adapters are started.  Keep the compatibility work here dependency-light so
the CLI can run it before importing those plugins.
"""

from __future__ import annotations

import logging
import os
import ssl
import sys
import warnings
from typing import Any


logger = logging.getLogger(__name__)

_WINDOWS_CERT_LOADER_MARKER = "_hermes_skips_malformed_certificates"
_warned_about_malformed_windows_certs = False


def _is_truncated_asn1_certificate_error(exc: BaseException) -> bool:
    """Return whether *exc* is the Windows-store corruption seen by OpenSSL."""
    if not isinstance(exc, ssl.SSLError):
        return False
    library = str(getattr(exc, "library", "") or "").upper()
    reason = str(getattr(exc, "reason", "") or "").upper()
    message = str(exc).upper()
    return (
        library == "ASN1" and reason == "NOT_ENOUGH_DATA"
    ) or "[ASN1: NOT_ENOUGH_DATA]" in message


def _load_windows_store_certs_individually(
    context: ssl.SSLContext, storename: str, purpose: Any
) -> bytearray:
    """Load usable Windows certificates while isolating malformed entries.

    CPython normally concatenates every DER certificate in a Windows store and
    passes the entire byte array to OpenSSL.  One truncated entry therefore
    rejects the complete store.  Loading each certificate separately preserves
    every valid system and enterprise CA while allowing only the unreadable
    entry to be ignored.
    """
    global _warned_about_malformed_windows_certs

    loaded = bytearray()
    skipped = 0
    try:
        for cert, encoding, trust in ssl.enum_certificates(storename):
            if encoding != "x509_asn":
                continue
            if trust is not True and purpose.oid not in trust:
                continue
            try:
                context.load_verify_locations(cadata=cert)
            except ssl.SSLError as exc:
                if not _is_truncated_asn1_certificate_error(exc):
                    raise
                skipped += 1
                continue
            loaded.extend(cert)
    except PermissionError:
        warnings.warn(
            f"unable to enumerate Windows certificate store {storename!r}",
            RuntimeWarning,
            stacklevel=2,
        )

    if skipped and not _warned_about_malformed_windows_certs:
        logger.warning(
            "Ignored %d malformed certificate(s) in the Windows %s store; "
            "TLS verification remains enabled for all valid certificates",
            skipped,
            storename,
        )
        _warned_about_malformed_windows_certs = True
    return loaded


def _install_windows_cert_store_fallback() -> bool:
    """Install a narrow fallback when the aggregate Windows store is corrupt."""
    if sys.platform != "win32":
        return False

    current_loader = getattr(ssl.SSLContext, "_load_windows_store_certs", None)
    if current_loader is None:
        return False
    if getattr(current_loader, _WINDOWS_CERT_LOADER_MARKER, False):
        return False

    try:
        ssl.create_default_context()
    except ssl.SSLError as exc:
        if not _is_truncated_asn1_certificate_error(exc):
            return False
    else:
        return False

    setattr(
        _load_windows_store_certs_individually,
        _WINDOWS_CERT_LOADER_MARKER,
        True,
    )
    try:
        setattr(
            ssl.SSLContext,
            "_load_windows_store_certs",
            _load_windows_store_certs_individually,
        )
        # Verify that the fallback fixes context construction.  Restore the
        # stdlib method if a different certificate problem remains.
        ssl.create_default_context()
    except Exception:
        setattr(ssl.SSLContext, "_load_windows_store_certs", current_loader)
        return False
    return True


def ensure_gateway_ssl_certs() -> None:
    """Select a CA bundle and tolerate isolated corrupt Windows certs.

    A valid explicit ``SSL_CERT_FILE`` remains authoritative.  A stale path is
    removed and resolved through Python defaults, certifi, then common POSIX
    locations.  Windows-store hardening still runs for an explicit bundle
    because ``SSLContext.load_default_certs()`` enumerates the Windows stores
    before applying OpenSSL's file defaults.
    """
    configured_cert = os.environ.get("SSL_CERT_FILE")
    if configured_cert and not os.path.exists(configured_cert):
        logger.warning(
            "Ignoring stale SSL_CERT_FILE=%r because the path does not exist",
            configured_cert,
        )
        os.environ.pop("SSL_CERT_FILE", None)
        configured_cert = None

    if not configured_cert:
        paths = ssl.get_default_verify_paths()
        for candidate in (paths.cafile, paths.openssl_cafile):
            if candidate and os.path.exists(candidate):
                os.environ["SSL_CERT_FILE"] = candidate
                break
        else:
            try:
                import certifi

                os.environ["SSL_CERT_FILE"] = certifi.where()
            except ImportError:
                for candidate in (
                    "/etc/ssl/certs/ca-certificates.crt",
                    "/etc/pki/tls/certs/ca-bundle.crt",
                    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
                    "/etc/ssl/ca-bundle.pem",
                    "/etc/ssl/cert.pem",
                    "/etc/pki/tls/cert.pem",
                    "/usr/local/etc/openssl@1.1/cert.pem",
                    "/opt/homebrew/etc/openssl@1.1/cert.pem",
                ):
                    if os.path.exists(candidate):
                        os.environ["SSL_CERT_FILE"] = candidate
                        break

    _install_windows_cert_store_fallback()
