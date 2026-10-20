"""Generate a localhost-only leaf certificate; trust installation is a separate step."""
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from config import TLS_DIRECTORY

if __name__ == '__main__':
    TLS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = TLS_DIRECTORY / 'localhost.crt', TLS_DIRECTORY / 'localhost.key'
    if cert_path.exists() or key_path.exists():
        raise SystemExit('TLS files already exist; refusing to overwrite.')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'OptionTracker local development')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1')), x509.DNSName('localhost')]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print('Created localhost leaf certificate, valid for 90 days. No CA certificate created.')
