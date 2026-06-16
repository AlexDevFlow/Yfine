import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "@fontsource-variable/inter";
import "slot-text/style.css";
import "./styles/globals.css";
import "./i18n";
import { ThemeProvider } from "@/components/theme/theme-provider";
import { LoginScreen } from "@/components/auth/login-screen";
import { isDbEncrypted, registerReencryptOnClose, setRuntimePassword } from "@/lib/auth-bridge";
import { router } from "./router";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
});

/** Gate the app behind unlock when the on-disk DB is encrypted (Tauri only). */
function Root() {
  const [locked, setLocked] = useState<boolean | null>(null);
  useEffect(() => {
    isDbEncrypted().then(setLocked).catch(() => setLocked(false));
  }, []);

  if (locked === null) {
    return <div className="grid h-full place-items-center text-sm text-muted">…</div>;
  }
  if (locked) {
    return (
      <LoginScreen
        onUnlock={(pw) => {
          setRuntimePassword(pw);
          void registerReencryptOnClose();
          setLocked(false);
        }}
      />
    );
  }
  return <RouterProvider router={router} />;
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <Root />
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
