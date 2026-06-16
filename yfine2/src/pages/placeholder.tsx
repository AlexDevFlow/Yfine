import { useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/card";
import { ALL_NAV } from "@/components/layout/nav";

/**
 * Generic "being rebuilt" page used for every route whose feature hasn't been
 * ported yet. Derives its title/icon from the active nav item.
 */
export function Placeholder() {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const item =
    ALL_NAV.find((i) => i.to !== "/" && pathname.startsWith(i.to)) ?? ALL_NAV[0];
  const Icon = item.icon;
  const title = t(item.key, { defaultValue: item.label });

  return (
    <Card className="grid place-items-center px-6 py-20 text-center">
      <div className="grid h-14 w-14 place-items-center rounded-2xl bg-accent-soft text-primary">
        <Icon className="h-7 w-7" />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-foreground">{title}</h2>
      <p className="mt-2 max-w-sm text-sm text-muted">
        {t("section_rebuilding", {
          defaultValue:
            "This section is being rebuilt in the new Yfine. It will be wired to your data in an upcoming phase.",
        })}
      </p>
    </Card>
  );
}
