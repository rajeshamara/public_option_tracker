"""Exercise HTTPS disconnects without importing the app or contacting Schwab."""
import asyncio
import http.client
import ipaddress
import socket
import ssl
import struct
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows TLS reset regression')
def test_https_server_recovers_from_abrupt_disconnects(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost test')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'test.crt', tmp_path / 'test.key'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    # Trust only this isolated test certificate; do not disable TLS verification.
    context = ssl.create_default_context(cafile=str(cert_path))

    async def probe(scope, receive, send):
        assert scope['type'] == 'http'
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [(b'content-length', b'2')]})
        await send({'type': 'http.response.body', 'body': b'ok'})

    config = uvicorn.Config(probe, loop='asyncio:SelectorEventLoop',
                            ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
                            lifespan='off', access_log=False, log_level='error')
    server = uvicorn.Server(config)
    errors = []
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]

    async def serve():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, details: errors.append(details))
        await server.serve(sockets=[listener])

    def run_server():
        try:
            with asyncio.Runner(loop_factory=config.get_loop_factory()) as runner:
                runner.run(serve())
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run_server, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, errors
        for _ in range(20):
            with socket.create_connection(('127.0.0.1', port), timeout=2) as raw:
                with context.wrap_socket(raw, server_hostname='127.0.0.1') as tls:
                    tls.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
                    assert tls.recv(4096).startswith(b'HTTP/1.1 200')
                    # Force a TCP RST instead of a TLS close-notify, as a client
                    # disappearing during a keep-alive connection can do.
                    tls.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                   struct.pack('HH', 1, 0))
            connection = http.client.HTTPSConnection('127.0.0.1', port,
                                                     context=context, timeout=2)
            try:
                connection.request('GET', '/')
                response = connection.getresponse()
                assert response.status == 200 and response.read() == b'ok'
            finally:
                connection.close()
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        listener.close()
    assert not worker.is_alive(), 'Server shutdown hung after client resets'
    assert not errors, errors
