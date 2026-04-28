"""Security utilities: password management, DB file encryption, TLS certificates."""

import atexit
import base64
import hashlib
import ipaddress
import json
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from database import DATA_DIR, DB_PATH

_logger = logging.getLogger(__name__)

AUTH_FILE = DATA_DIR / ".yfine-auth.json"
ENC_DB_PATH = DB_PATH.parent / "yfine.db.enc"
UNLOCK_MARKER = DATA_DIR / ".yfine-unlocked"
CERT_DIR = DATA_DIR / "certs"

# Holds the plaintext password in memory while the app is running,
# so we can re-encrypt on shutdown.  Never written to disk.
# Stored as bytearray (mutable, can be zeroed) rather than str (immutable).
_runtime_password: bytearray | None = None


# ---------------------------------------------------------------------------
# Auth config file  (lives outside the DB — always readable)
# ---------------------------------------------------------------------------

def get_auth_config() -> dict | None:
    if not AUTH_FILE.exists():
        return None
    try:
        return json.loads(AUTH_FILE.read_text())
    except Exception:
        _logger.warning("Failed to read auth config from %s", AUTH_FILE, exc_info=True)
        return None


def save_auth_config(config: dict):
    AUTH_FILE.write_text(json.dumps(config, indent=2))


def remove_auth_config():
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()


def is_password_set() -> bool:
    config = get_auth_config()
    return config is not None and bool(config.get("password_hash"))


def is_db_encrypted() -> bool:
    return ENC_DB_PATH.exists()


def get_session_secret() -> str:
    config = get_auth_config()
    if config and "session_secret" in config:
        return config["session_secret"]
    return "yfine-no-auth-fallback-key"


# ---------------------------------------------------------------------------
# Password hashing  (PBKDF2-SHA256 — stdlib, no extra dependency)
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 480_000


def hash_password(password: str) -> tuple[str, str]:
    """Return (hash_hex, salt_hex)."""
    salt = secrets.token_bytes(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return key.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return secrets.compare_digest(key.hex(), stored_hash)


# ---------------------------------------------------------------------------
# Database file encryption  (Fernet = AES-128-CBC + HMAC-SHA256)
# ---------------------------------------------------------------------------

_AES256_HEADER = b"YF256\x01"  # 6-byte magic to identify AES-256-GCM format


def _derive_key(password: str, salt_hex: str) -> bytes:
    """Derive a 32-byte key for AES-256."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=bytes.fromhex(salt_hex),
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode())


def _derive_fernet_key(password: str, salt_hex: str) -> bytes:
    """Derive a Fernet key (legacy, for reading old archives)."""
    raw = _derive_key(password, salt_hex)
    return base64.urlsafe_b64encode(raw)


def encrypt_db_file(password: str) -> bool:
    """Encrypt yfine.db -> yfine.db.enc (AES-256-GCM) and remove the plaintext.

    Writes the ciphertext to a temp file in the same directory and atomically
    renames it into place so a power loss mid-write can never leave a truncated
    .enc that crash recovery would treat as canonical.
    """
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    config = get_auth_config()
    if not config or not DB_PATH.exists():
        return False

    key = _derive_key(password, config["encryption_salt"])
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)

    data = DB_PATH.read_bytes()
    ciphertext = aesgcm.encrypt(nonce, data, None)
    payload = _AES256_HEADER + nonce + ciphertext

    # Format: HEADER + nonce (12) + ciphertext (includes 16-byte GCM tag).
    # Atomic write: temp file → fsync → rename. os.replace is atomic on POSIX
    # and Windows (Python 3.3+).
    tmp_path = ENC_DB_PATH.with_suffix(ENC_DB_PATH.suffix + ".tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync can fail on some filesystems (e.g. tmpfs); the rename
                # itself is still atomic, so we tolerate it.
                pass
        os.replace(tmp_path, ENC_DB_PATH)
    except Exception:
        # Clean up the partial temp file so we don't leak it on the next boot.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    DB_PATH.unlink(missing_ok=True)
    UNLOCK_MARKER.unlink(missing_ok=True)
    _logger.info("Database encrypted successfully (AES-256-GCM)")
    return True


def decrypt_db_file(password: str) -> bool:
    """Decrypt yfine.db.enc -> yfine.db.  Supports AES-256-GCM and legacy Fernet."""
    config = get_auth_config()
    if not config or not ENC_DB_PATH.exists():
        return False

    try:
        encrypted = ENC_DB_PATH.read_bytes()

        if encrypted[:len(_AES256_HEADER)] == _AES256_HEADER:
            # New AES-256-GCM format
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            key = _derive_key(password, config["encryption_salt"])
            payload = encrypted[len(_AES256_HEADER):]
            nonce = payload[:12]
            ciphertext = payload[12:]
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        else:
            # Legacy Fernet (AES-128-CBC) — for existing archives
            from cryptography.fernet import Fernet

            key = _derive_fernet_key(password, config["encryption_salt"])
            fernet = Fernet(key)
            decrypted = fernet.decrypt(encrypted)
            _logger.info("Decrypted legacy Fernet archive — will re-encrypt as AES-256-GCM on shutdown")

        DB_PATH.write_bytes(decrypted)
        UNLOCK_MARKER.write_text(datetime.utcnow().isoformat())
        _logger.info("Database decrypted successfully")
        return True
    except Exception:
        _logger.exception("Database decryption failed")
        DB_PATH.unlink(missing_ok=True)
        return False


def handle_crash_recovery():
    """Called on startup (before init_db): if a previous run crashed while the DB
    was unlocked, clean up.  Only acts when no deliberate unlock is in progress
    (i.e., the UNLOCK_MARKER was NOT just written by decrypt_db_file in this session).
    """
    if not is_password_set():
        UNLOCK_MARKER.unlink(missing_ok=True)
        return

    if ENC_DB_PATH.exists() and DB_PATH.exists() and not UNLOCK_MARKER.exists():
        # Both files exist but no marker → crash during previous decrypt/encrypt cycle.
        # The encrypted copy is canonical — remove stale plaintext.
        _logger.warning("Crash recovery: removing stale unencrypted DB copy")
        DB_PATH.unlink(missing_ok=True)


def register_shutdown_encryption():
    """Register atexit + signal handlers to re-encrypt the DB on clean exit."""

    def _encrypt_on_exit():
        global _runtime_password
        if _runtime_password and DB_PATH.exists() and is_password_set():
            try:
                encrypt_db_file(_runtime_password.decode("utf-8"))
            except Exception:
                _logger.exception("Failed to re-encrypt DB on shutdown")
            finally:
                # Zero the password from memory after use
                if _runtime_password is not None:
                    for i in range(len(_runtime_password)):
                        _runtime_password[i] = 0
                    _runtime_password = None

    atexit.register(_encrypt_on_exit)

    # Signal handlers are not needed — atexit covers clean exits,
    # and uvicorn handles SIGTERM/SIGINT gracefully, triggering atexit.


def set_runtime_password(password: str | None):
    global _runtime_password
    # Zero old password before replacing
    if _runtime_password is not None:
        for i in range(len(_runtime_password)):
            _runtime_password[i] = 0
    if password is not None:
        _runtime_password = bytearray(password.encode("utf-8"))
    else:
        _runtime_password = None


def get_runtime_password() -> str | None:
    """Return the runtime password as a string (for re-encryption checks)."""
    if _runtime_password is None:
        return None
    return _runtime_password.decode("utf-8")


# ---------------------------------------------------------------------------
# Password lifecycle  (set / change / remove)
# ---------------------------------------------------------------------------

def _sync_db_settings_to_config(config: dict):
    """Copy settings that desktop.py needs from the DB into auth config,
    so they remain accessible even when the DB is encrypted."""
    try:
        from sqlmodel import Session
        from database import engine
        from services.settings import get_settings

        with Session(engine) as session:
            settings = get_settings(session)
            config.setdefault("lan_access", settings.lan_access)
            config.setdefault("locale", settings.locale)
    except Exception:
        _logger.debug("Could not sync DB settings to auth config", exc_info=True)


def set_password(password: str):
    """Set a new password.  DB will be encrypted on next shutdown."""
    pw_hash, pw_salt = hash_password(password)
    config = get_auth_config() or {}
    config.update({
        "password_hash": pw_hash,
        "password_salt": pw_salt,
        "encryption_salt": secrets.token_bytes(32).hex(),
        "session_secret": secrets.token_hex(32),
    })

    # Copy DB-only settings into auth config so they survive DB encryption
    _sync_db_settings_to_config(config)

    save_auth_config(config)
    set_runtime_password(password)


def change_password(old_password: str, new_password: str) -> bool:
    config = get_auth_config()
    if not config:
        return False
    if not verify_password(old_password, config["password_hash"], config["password_salt"]):
        return False

    # If DB is currently decrypted, we just update the config; next shutdown
    # encrypts with the new key. We must also drop any stale .enc on disk —
    # it is keyed to the *old* salt and would be undecryptable with the new
    # password. Without this, a crash before clean shutdown would leave only
    # an unreadable .enc and erase the plaintext on the next failed login.
    pw_hash, pw_salt = hash_password(new_password)
    config["password_hash"] = pw_hash
    config["password_salt"] = pw_salt
    config["encryption_salt"] = secrets.token_bytes(32).hex()
    save_auth_config(config)
    set_runtime_password(new_password)
    if DB_PATH.exists():
        # Plaintext is intact — wipe the stale ciphertext so it can't outlive
        # the password change.
        ENC_DB_PATH.unlink(missing_ok=True)
        UNLOCK_MARKER.write_text(datetime.utcnow().isoformat())
    return True


def remove_password(current_password: str) -> bool:
    config = get_auth_config()
    if not config:
        return True
    if not verify_password(current_password, config["password_hash"], config["password_salt"]):
        return False

    # Preserve non-auth settings (e.g. port) before deleting auth config
    preserved = {k: config[k] for k in ("port",) if k in config}

    # Delete encrypted copy if it exists
    ENC_DB_PATH.unlink(missing_ok=True)
    UNLOCK_MARKER.unlink(missing_ok=True)

    if preserved:
        save_auth_config(preserved)
    else:
        remove_auth_config()

    set_runtime_password(None)
    return True


# ---------------------------------------------------------------------------
# Self-signed TLS certificate
# ---------------------------------------------------------------------------

def ensure_tls_cert() -> tuple[str, str]:
    """Generate a self-signed cert if absent.  Returns (cert_path, key_path)."""
    cert_path = CERT_DIR / "cert.pem"
    key_path = CERT_DIR / "key.pem"

    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    CERT_DIR.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "yfine.local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Yfine"),
    ])

    san_list = [
        x509.DNSName("localhost"),
        x509.DNSName("yfine.local"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]

    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        san_list.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
    except Exception:
        _logger.debug("Could not determine local IP for TLS cert SAN", exc_info=True)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(san_list), critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    _logger.info("Generated self-signed TLS certificate at %s", CERT_DIR)
    return str(cert_path), str(key_path)
