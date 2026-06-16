//! Auth / encryption Tauri commands. Operate on files in the app config dir
//! (same dir tauri-plugin-sql resolves `sqlite:yfine.db` against), keeping secrets
//! in `.yfine-auth.json` OUTSIDE the encrypted DB so the app can boot and prompt.

use crate::crypto;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use tauri::Manager;

fn data_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}
fn auth_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(data_dir(app)?.join(".yfine-auth.json"))
}
fn enc_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(data_dir(app)?.join("yfine.db.enc"))
}
fn db_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(data_dir(app)?.join("yfine.db"))
}
fn marker_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    Ok(data_dir(app)?.join(".yfine-unlocked"))
}

fn read_config(app: &tauri::AppHandle) -> Value {
    auth_path(app)
        .ok()
        .and_then(|p| fs::read(p).ok())
        .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
        .unwrap_or_else(|| json!({}))
}
fn write_config(app: &tauri::AppHandle, cfg: &Value) -> Result<(), String> {
    let p = auth_path(app)?;
    fs::write(p, serde_json::to_vec_pretty(cfg).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn is_db_encrypted(app: tauri::AppHandle) -> bool {
    enc_path(&app).map(|p| p.exists()).unwrap_or(false)
}

#[tauri::command]
pub fn is_password_set(app: tauri::AppHandle) -> bool {
    read_config(&app)
        .get("password_hash")
        .and_then(|v| v.as_str())
        .map(|s| !s.is_empty())
        .unwrap_or(false)
}

/// Verify the password and, if the DB is encrypted, decrypt it into place.
/// Returns true on success, false on wrong password; Err on decrypt failure.
#[tauri::command]
pub fn auth_login(app: tauri::AppHandle, password: String) -> Result<bool, String> {
    let cfg = read_config(&app);
    let hash = cfg["password_hash"].as_str().ok_or("no password set")?;
    let psalt = cfg["password_salt"].as_str().ok_or("no password salt")?;
    if !crypto::verify_password(&password, hash, psalt) {
        return Ok(false);
    }
    if enc_path(&app)?.exists() {
        let esalt_hex = cfg["encryption_salt"].as_str().ok_or("no encryption salt")?;
        let esalt = hex::decode(esalt_hex).map_err(|e| e.to_string())?;
        let key = crypto::derive_key(&password, &esalt);
        let archive = fs::read(enc_path(&app)?).map_err(|e| e.to_string())?;
        match crypto::decrypt(&archive, &key) {
            Ok(plain) => {
                fs::write(db_path(&app)?, plain).map_err(|e| e.to_string())?;
                let _ = fs::write(marker_path(&app)?, b"unlocked");
            }
            Err(e) => {
                let _ = fs::remove_file(db_path(&app)?); // never leave a partial plaintext
                return Err(e);
            }
        }
    }
    Ok(true)
}

/// Re-encrypt the working DB to `yfine.db.enc` (atomic) and wipe the plaintext.
/// Called on app exit when a password is set.
#[tauri::command]
pub fn encrypt_db(app: tauri::AppHandle, password: String) -> Result<(), String> {
    let cfg = read_config(&app);
    let esalt_hex = cfg["encryption_salt"].as_str().ok_or("no encryption salt")?;
    let esalt = hex::decode(esalt_hex).map_err(|e| e.to_string())?;
    let dbp = db_path(&app)?;
    if !dbp.exists() {
        return Ok(());
    }
    let key = crypto::derive_key(&password, &esalt);
    let plain = fs::read(&dbp).map_err(|e| e.to_string())?;
    let archive = crypto::encrypt(&plain, &key)?;
    let tmp = data_dir(&app)?.join("yfine.db.enc.tmp");
    {
        use std::io::Write;
        let mut f = fs::File::create(&tmp).map_err(|e| e.to_string())?;
        f.write_all(&archive).map_err(|e| e.to_string())?;
        f.sync_all().map_err(|e| e.to_string())?; // fsync: ciphertext durable on disk
    }
    fs::rename(&tmp, enc_path(&app)?).map_err(|e| e.to_string())?; // durable before deleting plaintext
    let _ = fs::remove_file(&dbp);
    let _ = fs::remove_file(marker_path(&app)?);
    Ok(())
}

/// Set a password for the first time (generates hashes + salts + session secret).
#[tauri::command]
pub fn set_password(app: tauri::AppHandle, password: String) -> Result<(), String> {
    if password.is_empty() {
        return Err("empty password".into());
    }
    let mut cfg = read_config(&app);
    let (h, s) = crypto::hash_password(&password);
    cfg["password_hash"] = json!(h);
    cfg["password_salt"] = json!(s);
    cfg["encryption_salt"] = json!(crypto::random_hex(32));
    cfg["session_secret"] = json!(crypto::random_hex(32));
    write_config(&app, &cfg)
}

/// Remove the password and decrypt at rest (verifies current password first).
#[tauri::command]
pub fn remove_password(app: tauri::AppHandle, password: String) -> Result<bool, String> {
    let cfg = read_config(&app);
    let hash = cfg["password_hash"].as_str().unwrap_or("");
    let psalt = cfg["password_salt"].as_str().unwrap_or("");
    if !crypto::verify_password(&password, hash, psalt) {
        return Ok(false);
    }
    let _ = fs::remove_file(enc_path(&app)?);
    let _ = fs::remove_file(marker_path(&app)?);
    let port = cfg.get("port").cloned();
    let mut new_cfg = json!({});
    if let Some(p) = port {
        new_cfg["port"] = p;
    }
    write_config(&app, &new_cfg)?;
    Ok(true)
}
