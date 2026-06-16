mod auth;
mod crypto;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_sql::Builder::default().build())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![
            auth::is_db_encrypted,
            auth::is_password_set,
            auth::auth_login,
            auth::encrypt_db,
            auth::set_password,
            auth::remove_password,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
