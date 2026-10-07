from __future__ import annotations

import smtplib
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from co_scientist.core.config import settings
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app import notifications

_RealSMTP = smtplib.SMTP


class _Smtp:
    def __init__(self, *, reject_certificate: bool = False) -> None:
        self.context: ssl.SSLContext | None = None
        self.reject_certificate = reject_certificate
        self.actions: list[str] = []

    def __enter__(self) -> _Smtp:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def starttls(self, *, context: ssl.SSLContext | None = None) -> None:
        self.context = context
        self.actions.append("tls")
        if self.reject_certificate:
            raise ssl.SSLCertVerificationError("untrusted server certificate")

    def login(self, username: str, password: str) -> None:
        self.actions.append("login")

    def send_message(self, message: EmailMessage) -> None:
        assert message["To"] == "scientist@example.org"
        assert message["Subject"] == "Report ready"
        self.actions.append("send")


def _install_smtp(monkeypatch: pytest.MonkeyPatch, smtp: _Smtp) -> None:
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "smtp_from_email", "reports@example.org")
    monkeypatch.setattr(settings, "smtp_username", "synthetic-user")
    monkeypatch.setattr(settings, "smtp_password", "synthetic-password")
    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: smtp)


@pytest.mark.asyncio
async def test_delivery_authenticates_the_smtp_server_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp = _Smtp()
    _install_smtp(monkeypatch, smtp)

    await notifications.deliver_email("scientist@example.org", "Report ready", "Open your report")

    assert smtp.context is not None
    assert smtp.context.verify_mode == ssl.CERT_REQUIRED
    assert smtp.context.check_hostname is True
    assert smtp.actions == ["tls", "login", "send"]


@pytest.mark.asyncio
async def test_certificate_failure_prevents_smtp_login_and_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp = _Smtp(reject_certificate=True)
    _install_smtp(monkeypatch, smtp)

    with pytest.raises(ssl.SSLCertVerificationError):
        await notifications.deliver_email("scientist@example.org", "Report ready", "Report")

    assert smtp.actions == ["tls"]


@pytest.mark.asyncio
async def test_smtp_without_credentials_still_verifies_before_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp = _Smtp()
    _install_smtp(monkeypatch, smtp)
    monkeypatch.setattr(settings, "smtp_username", "")

    await notifications.deliver_email("scientist@example.org", "Report ready", "Report")

    assert smtp.context is not None and smtp.context.check_hostname
    assert smtp.actions == ["tls", "send"]


@pytest.mark.asyncio
async def test_private_smtp_ca_is_added_without_removing_public_trust(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic SMTP test CA")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    bundle = tmp_path / "smtp-ca.pem"
    bundle.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    default_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))
    smtp = _Smtp()
    _install_smtp(monkeypatch, smtp)
    monkeypatch.setattr(settings, "smtp_ca_bundle", str(bundle))

    await notifications.deliver_email("scientist@example.org", "Report ready", "Report")

    assert smtp.context is not None
    actual_roots = set(smtp.context.get_ca_certs(binary_form=True))
    assert certificate.public_bytes(serialization.Encoding.DER) in actual_roots
    assert default_roots <= actual_roots
    assert smtp.context.verify_mode == ssl.CERT_REQUIRED and smtp.context.check_hostname
    assert smtp.actions == ["tls", "login", "send"]


@pytest.mark.asyncio
async def test_invalid_smtp_ca_bundle_prevents_login_and_delivery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smtp = _Smtp()
    _install_smtp(monkeypatch, smtp)
    monkeypatch.setattr(settings, "smtp_ca_bundle", str(tmp_path / "missing.pem"))

    with pytest.raises(FileNotFoundError):
        await notifications.deliver_email("scientist@example.org", "Report ready", "Report")

    assert smtp.actions == []


def _synthetic_ca(label: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def _synthetic_server_cert(
    directory: Path,
    label: str,
    hostname: str,
    ca_key: rsa.RSAPrivateKey,
    ca_certificate: x509.Certificate,
) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_path = directory / f"{label}.crt.pem"
    key_path = directory / f"{label}.key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _read_smtp_command(sock: socket.socket) -> bytes:
    line = bytearray()
    while not line.endswith(b"\r\n"):
        part = sock.recv(1)
        if not part:
            raise ConnectionError("SMTP peer closed before completing a command")
        line.extend(part)
    return bytes(line)


def _local_starttls(
    context: ssl.SSLContext,
    cert_path: Path,
    key_path: Path,
    hostname: str,
) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    server_errors: list[BaseException] = []

    def serve() -> None:
        try:
            raw, _ = listener.accept()
            with raw:
                raw.settimeout(5)
                raw.sendall(b"220 synthetic SMTP ready\r\n")
                initial_command = _read_smtp_command(raw)
                if not initial_command.upper().startswith(b"EHLO "):
                    raise AssertionError(f"unexpected initial SMTP command: {initial_command!r}")
                raw.sendall(b"250-local.test\r\n250-STARTTLS\r\n250 OK\r\n")
                if _read_smtp_command(raw).upper() != b"STARTTLS\r\n":
                    raise AssertionError("client omitted STARTTLS")
                raw.sendall(b"220 begin TLS\r\n")
                with server_context.wrap_socket(raw, server_side=True) as encrypted:
                    encrypted.settimeout(5)
                    if not _read_smtp_command(encrypted).upper().startswith(b"EHLO "):
                        raise AssertionError("client omitted post-TLS EHLO")
                    encrypted.sendall(b"250 local.test\r\n")
                    if _read_smtp_command(encrypted).upper() != b"QUIT\r\n":
                        raise AssertionError("client omitted QUIT")
                    encrypted.sendall(b"221 bye\r\n")
        except BaseException as exc:
            server_errors.append(exc)

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    client = _RealSMTP(timeout=5)
    client_error: BaseException | None = None
    try:
        code, _ = client.connect("127.0.0.1", port)
        if code != 220:
            raise AssertionError(f"unexpected SMTP greeting: {code}")
        # Connect to loopback while verifying the certificate for the SMTP DNS name.
        client._host = hostname  # type: ignore[attr-defined]
        client.starttls(context=context)
        client.ehlo()
        client.quit()
    except BaseException as exc:
        client_error = exc
    finally:
        client.close()
        listener.close()
        server.join(timeout=6)

    if server.is_alive():
        raise TimeoutError("local SMTP STARTTLS peer did not finish")
    if client_error is not None:
        if isinstance(client_error, smtplib.SMTPServerDisconnected) and server_errors:
            raise AssertionError(f"local SMTP peer failed: {server_errors[0]!r}") from client_error
        raise client_error
    if server_errors:
        raise server_errors[0]


@pytest.mark.asyncio
async def test_captured_context_verifies_private_ca_host_and_rejects_bad_certificates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hostname = "smtp.synthetic.test"
    trusted_key, trusted_ca = _synthetic_ca("Synthetic trusted CA")
    untrusted_key, untrusted_ca = _synthetic_ca("Synthetic untrusted CA")
    trusted_cert, trusted_server_key = _synthetic_server_cert(
        tmp_path, "trusted", hostname, trusted_key, trusted_ca
    )
    untrusted_cert, untrusted_server_key = _synthetic_server_cert(
        tmp_path, "untrusted", hostname, untrusted_key, untrusted_ca
    )
    ca_bundle = tmp_path / "smtp-private-ca.pem"
    ca_bundle.write_bytes(trusted_ca.public_bytes(serialization.Encoding.PEM))

    smtp = _Smtp()
    _install_smtp(monkeypatch, smtp)
    monkeypatch.setattr(settings, "smtp_ca_bundle", str(ca_bundle))
    await notifications.deliver_email("scientist@example.org", "Report ready", "Report")

    context = smtp.context
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    _local_starttls(context, trusted_cert, trusted_server_key, hostname)
    with pytest.raises(ssl.SSLCertVerificationError):
        _local_starttls(context, untrusted_cert, untrusted_server_key, hostname)
    with pytest.raises(ssl.SSLCertVerificationError):
        _local_starttls(context, trusted_cert, trusted_server_key, "wrong.synthetic.test")
