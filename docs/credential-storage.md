# Credential storage

BlogHub encrypts every provider credential before writing it to SQLite. New
installations create `data/credential-keys.json` with restricted file
permissions. The key file must be protected separately from database backups.
Losing it makes stored provider credentials unrecoverable.

The ciphertext format is versioned (`enc:v1:<key-id>:...`). On startup, BlogHub
transactionally upgrades plaintext legacy values, old `fernet:` values, and
credentials encrypted with an inactive key. Startup fails if an encrypted value
cannot be decrypted. It never falls back to plaintext storage.

## Production configuration

Set an active key through the environment when deployment secrets are managed
outside the application filesystem:

```bash
export BLOGHUB_SECRET_KEY='<Fernet key>'
export BLOGHUB_SECRET_KEY_ID='2026-08'
export BLOGHUB_PREVIOUS_SECRET_KEYS='{"2026-07":"<previous Fernet key>"}'
```

Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`BLOGHUB_CREDENTIAL_KEY_FILE` changes the local keyring location. Integrations
with KMS, Vault, or another secret manager can implement
`backend.store.crypto.KeyProvider` and install it with
`configure_key_provider()` before store initialization.

Do not commit keys, include them in database archives, print them, or return them
from an API. Back up the database and keyring into separate access-controlled
systems.

## Rotation

For the local keyring, stop application writes and run:

```bash
python scripts/bloghub_credentials.py rotate
```

This creates a new active key and re-encrypts all stored credentials while
retaining inactive keys for rollback. Restart BlogHub and test each connection.
After taking a protected keyring backup and verifying the rotation:

```bash
python scripts/bloghub_credentials.py retire --confirm
```

For environment or external secret managers, add the old key to
`BLOGHUB_PREVIOUS_SECRET_KEYS`, deploy the new active key and key id, and restart.
Startup re-encrypts credentials with the active key. Remove old keys only after
the database has been migrated and verified.

`python scripts/bloghub_credentials.py migrate` explicitly runs the same legacy
migration. `status` reports key identifiers and counts, never key material.

## Revocation and recovery

Disconnecting a provider erases its stored credential and leaves only a
credential-free disconnected marker. Reconnect to replace expired, revoked, or
otherwise unusable credentials. If a key is lost or ciphertext is corrupt,
restore the matching key from protected backup or remove the affected connection
row and reconnect. BlogHub will not silently discard the decryption error.
