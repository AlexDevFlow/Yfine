//! At-rest DB encryption — byte-compatible with the legacy Yfine `yfine.db.enc`
//! format so an existing encrypted database migrates unchanged.
//!
//! Layout (new):  b"YF256\x01" (6) + nonce (12) + AES-256-GCM ciphertext(+tag).
//! Key:           PBKDF2-HMAC-SHA256, 32 bytes, 480_000 iters over the UTF-8
//!                password with the stored `encryption_salt`.
//! Legacy read:   archives without the magic header are Fernet tokens whose key
//!                is urlsafe-base64 of the same derived 32-byte key.
//! Password hash: PBKDF2-HMAC-SHA256, 32-byte hash + 32-byte salt, same iters.

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::Engine;
use rand::RngCore;
use sha2::Sha256;

const MAGIC: &[u8] = b"YF256\x01";
const ITERATIONS: u32 = 480_000;

pub fn derive_key(password: &str, salt: &[u8]) -> [u8; 32] {
    let mut key = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<Sha256>(password.as_bytes(), salt, ITERATIONS, &mut key);
    key
}

pub fn random_hex(n: usize) -> String {
    let mut buf = vec![0u8; n];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(buf)
}

/// (hash_hex, salt_hex)
pub fn hash_password(password: &str) -> (String, String) {
    let mut salt = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut salt);
    let key = derive_key(password, &salt);
    (hex::encode(key), hex::encode(salt))
}

pub fn verify_password(password: &str, hash_hex: &str, salt_hex: &str) -> bool {
    let salt = match hex::decode(salt_hex) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let computed = hex::encode(derive_key(password, &salt));
    // length-independent equality (inputs are fixed-length hex here)
    computed.len() == hash_hex.len()
        && computed
            .bytes()
            .zip(hash_hex.bytes())
            .fold(0u8, |acc, (a, b)| acc | (a ^ b))
            == 0
}

pub fn encrypt(plaintext: &[u8], key: &[u8; 32]) -> Result<Vec<u8>, String> {
    let cipher = Aes256Gcm::new(key.into());
    let mut nonce_bytes = [0u8; 12];
    rand::thread_rng().fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);
    let ct = cipher.encrypt(nonce, plaintext).map_err(|e| e.to_string())?;
    let mut out = Vec::with_capacity(MAGIC.len() + 12 + ct.len());
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&nonce_bytes);
    out.extend_from_slice(&ct);
    Ok(out)
}

pub fn decrypt(archive: &[u8], key: &[u8; 32]) -> Result<Vec<u8>, String> {
    if archive.starts_with(MAGIC) {
        if archive.len() < MAGIC.len() + 12 {
            return Err("truncated archive".into());
        }
        let nonce = Nonce::from_slice(&archive[MAGIC.len()..MAGIC.len() + 12]);
        let ct = &archive[MAGIC.len() + 12..];
        let cipher = Aes256Gcm::new(key.into());
        cipher.decrypt(nonce, ct).map_err(|e| e.to_string())
    } else {
        // legacy Fernet: key = urlsafe-b64 of the derived 32-byte key
        let fkey = base64::engine::general_purpose::URL_SAFE.encode(key);
        let f = fernet::Fernet::new(&fkey).ok_or_else(|| "invalid fernet key".to_string())?;
        let token = std::str::from_utf8(archive).map_err(|e| e.to_string())?;
        f.decrypt(token.trim()).map_err(|e| e.to_string())
    }
}
