import { Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Brand } from "@/components/layout/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authLogin } from "@/lib/auth-bridge";

export function LoginScreen({ onUnlock }: { onUnlock: (password: string) => void }) {
  const { t } = useTranslation();
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const ok = await authLogin(pw);
      if (ok) onUnlock(pw);
      else setError(t("login_wrong_password", { defaultValue: "Wrong password." }));
    } catch {
      setError(t("login_decrypt_failed", { defaultValue: "Couldn't unlock the database." }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid h-full place-items-center bg-background p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-card)]">
        <Brand />
        <div className="flex items-center gap-2 text-sm text-muted">
          <Lock className="h-4 w-4" /> {t("vault_locked", { defaultValue: "Your data is encrypted. Enter your password to unlock." })}
        </div>
        <Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={t("password", { defaultValue: "Password" })} autoFocus />
        {error && <p className="text-sm text-negative">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy || !pw}>
          {busy ? t("unlocking", { defaultValue: "Unlocking…" }) : t("unlock", { defaultValue: "Unlock" })}
        </Button>
      </form>
    </div>
  );
}
