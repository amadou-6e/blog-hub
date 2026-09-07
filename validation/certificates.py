"""Generate a disposable CA and fixture-only TLS certificate per validation run."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

root = Path('/certs')
root.mkdir(exist_ok=True)
if all((root / name).is_file() for name in ('ca.crt', 'tls.crt', 'tls.key')):
    raise SystemExit(0)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'BlogHub disposable validation CA')])
now = datetime.now(timezone.utc)
ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
      .public_key(key.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
      .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
      .sign(key, hashes.SHA256()))
leaf = rsa.generate_private_key(public_exponent=65537, key_size=2048)
cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture.test')]))
        .issuer_name(name).public_key(leaf.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('fixture.test'), x509.DNSName('identity.test')]), critical=False)
        .sign(key, hashes.SHA256()))
(root / 'ca.crt').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
(root / 'tls.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
(root / 'tls.key').write_bytes(leaf.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
(root / 'tls.key').chmod(0o600)
