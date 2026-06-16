import {
  ArrowLeftRight,
  Bell,
  LayoutDashboard,
  PiggyBank,
  PieChart,
  Repeat,
  Settings,
  Sparkles,
  Tag,
  Target,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  /** i18n key (falls back to `label` if the key is missing) */
  key: string;
  label: string;
  icon: LucideIcon;
}

export interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    key: "overview",
    label: "Overview",
    items: [{ to: "/", key: "dashboard", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    key: "money",
    label: "Money",
    items: [
      { to: "/sources", key: "sources", label: "Sources", icon: Wallet },
      { to: "/movements", key: "movements", label: "Movements", icon: ArrowLeftRight },
      { to: "/recurring", key: "recurring", label: "Recurring", icon: Repeat },
    ],
  },
  {
    key: "plan",
    label: "Plan",
    items: [
      { to: "/budgets", key: "budgets", label: "Budgets", icon: PieChart },
      { to: "/goals", key: "goals", label: "Goals", icon: Target },
      { to: "/savings", key: "savings", label: "Savings", icon: PiggyBank },
      { to: "/whims", key: "whims", label: "Whims", icon: Sparkles },
    ],
  },
  {
    key: "invest",
    label: "Invest",
    items: [{ to: "/portfolios", key: "portfolios", label: "Portfolios", icon: TrendingUp }],
  },
  {
    key: "organize",
    label: "Organize",
    items: [{ to: "/tags", key: "tags", label: "Tags", icon: Tag }],
  },
];

export const FOOTER_NAV: NavItem[] = [
  { to: "/notifications", key: "notifications", label: "Notifications", icon: Bell },
  { to: "/settings", key: "settings", label: "Settings", icon: Settings },
];

export const ALL_NAV: NavItem[] = [
  ...NAV_GROUPS.flatMap((g) => g.items),
  ...FOOTER_NAV,
];

/** Items shown in the mobile bottom bar (most-used). */
export const MOBILE_NAV: NavItem[] = [
  ALL_NAV[0], // dashboard
  ALL_NAV[1], // sources
  ALL_NAV[2], // movements
  ALL_NAV[4], // budgets
  FOOTER_NAV[1], // settings
];
