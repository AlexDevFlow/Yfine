/**
 * Thin bridge to the Rust auth/encryption commands. No-ops gracefully in the
 * browser preview (no Tauri runtime, no encryption). The runtime password is
 * held in memory after login so the working DB can be re-encrypted on close.
 */
import { isTauri } from "./tauri";

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke<T>(cmd, args);
}

export async function isDbEncrypted(): Promise<boolean> {
  return isTauri() ? invoke<boolean>("is_db_encrypted") : false;
}
export async function isPasswordSet(): Promise<boolean> {
  return isTauri() ? invoke<boolean>("is_password_set") : false;
}
export async function authLogin(password: string): Promise<boolean> {
  return invoke<boolean>("auth_login", { password });
}
export async function setAppPassword(password: string): Promise<void> {
  return invoke<void>("set_password", { password });
}
export async function removeAppPassword(password: string): Promise<boolean> {
  return invoke<boolean>("remove_password", { password });
}
async function encryptDb(password: string): Promise<void> {
  return invoke<void>("encrypt_db", { password });
}

let runtimePassword: string | null = null;
export function setRuntimePassword(pw: string | null): void {
  runtimePassword = pw;
}

let closeHookRegistered = false;
/** Re-encrypt the working DB when the window closes (mirrors the legacy atexit). */
export async function registerReencryptOnClose(): Promise<void> {
  if (!isTauri() || closeHookRegistered) return;
  closeHookRegistered = true;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const win = getCurrentWindow();
    await win.onCloseRequested(async (event) => {
      if (!runtimePassword) return;
      event.preventDefault();
      try {
        await encryptDb(runtimePassword);
      } catch {
        /* best-effort; the .enc is only replaced atomically on success */
      }
      runtimePassword = null;
      await win.destroy();
    });
  } catch {
    /* window API unavailable — skip */
  }
}
