import {
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { AppShell } from "@/components/layout/app-shell";
import { Dashboard } from "@/pages/dashboard";
import { SourcesPage } from "@/pages/sources";
import { SourceDetail } from "@/pages/source-detail";
import { MovementsPage } from "@/pages/movements";
import { RecurringPage } from "@/pages/recurring";
import { NotificationsPage } from "@/pages/notifications";
import { BudgetsPage } from "@/pages/budgets";
import { GoalsPage } from "@/pages/goals";
import { WhimsPage } from "@/pages/whims";
import { PortfoliosPage } from "@/pages/portfolios";
import { SavingsPage } from "@/pages/savings";
import { TagsPage } from "@/pages/tags";
import { SettingsPage } from "@/pages/settings";

const rootRoute = createRootRoute({ component: AppShell });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: Dashboard,
});

const sourcesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sources",
  component: SourcesPage,
});

const sourceDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sources/$id",
  component: SourceDetail,
});

const movementsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/movements",
  component: MovementsPage,
});

const recurringRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recurring",
  component: RecurringPage,
});

const notificationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/notifications",
  component: NotificationsPage,
});

const budgetsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/budgets", component: BudgetsPage });
const goalsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/goals", component: GoalsPage });
const whimsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/whims", component: WhimsPage });
const portfoliosRoute = createRoute({ getParentRoute: () => rootRoute, path: "/portfolios", component: PortfoliosPage });
const savingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/savings", component: SavingsPage });
const tagsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/tags", component: TagsPage });
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsPage });

const routeTree = rootRoute.addChildren([
  indexRoute,
  sourcesRoute,
  sourceDetailRoute,
  movementsRoute,
  recurringRoute,
  notificationsRoute,
  budgetsRoute,
  goalsRoute,
  whimsRoute,
  portfoliosRoute,
  savingsRoute,
  tagsRoute,
  settingsRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
