import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";
import { lazy } from "react";
import { meQuery } from "@/api/queries";
import { AppShell } from "@/components/app-shell";
import { currentMonthKey, isMonthKey } from "@/lib/dates";
import { parseForecastMonths } from "@/lib/forecast";
import { validateTransactionSearch } from "@/lib/transaction-search";
import { InvitePage } from "@/routes/invite";
import { LoginPage } from "@/routes/login";

// Pages load on demand (React.lazy; the router wraps matches in Suspense) so the entry chunk stays small (recharts lives in the lazy chunks only).
const AccountDetailPage = lazy(() =>
  import("@/routes/accounts").then((m) => ({ default: m.AccountDetailPage })),
);
const AccountsPage = lazy(() => import("@/routes/accounts").then((m) => ({ default: m.AccountsPage })));
const BankPage = lazy(() => import("@/routes/bank").then((m) => ({ default: m.BankPage })));
const BudgetsPage = lazy(() => import("@/routes/budgets").then((m) => ({ default: m.BudgetsPage })));
const CategoriesPage = lazy(() => import("@/routes/categories").then((m) => ({ default: m.CategoriesPage })));
const ContractDetailPage = lazy(() =>
  import("@/routes/contract-detail").then((m) => ({ default: m.ContractDetailPage })),
);
const ContractsPage = lazy(() => import("@/routes/contracts").then((m) => ({ default: m.ContractsPage })));
const DashboardPage = lazy(() => import("@/routes/dashboard").then((m) => ({ default: m.DashboardPage })));
const ForecastPage = lazy(() => import("@/routes/forecast").then((m) => ({ default: m.ForecastPage })));
const GoalsPage = lazy(() => import("@/routes/goals").then((m) => ({ default: m.GoalsPage })));
const HouseholdPage = lazy(() => import("@/routes/household").then((m) => ({ default: m.HouseholdPage })));
const ImportPage = lazy(() => import("@/routes/import").then((m) => ({ default: m.ImportPage })));
const MorePage = lazy(() => import("@/routes/more").then((m) => ({ default: m.MorePage })));
const ReportsPage = lazy(() => import("@/routes/reports").then((m) => ({ default: m.ReportsPage })));
const SecurityPage = lazy(() => import("@/routes/security").then((m) => ({ default: m.SecurityPage })));
const TransactionsPage = lazy(() =>
  import("@/routes/transactions").then((m) => ({ default: m.TransactionsPage })),
);

type RouterContext = { queryClient: QueryClient };

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: Outlet });

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  beforeLoad: async ({ context }) => {
    if (await context.queryClient.ensureQueryData(meQuery)) {
      throw redirect({ to: "/" });
    }
  },
  component: LoginPage,
});

const inviteRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/invite/$token",
  component: function InviteRoute() {
    return <InvitePage token={inviteRoute.useParams().token} />;
  },
});

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: async ({ context }) => {
    if (!(await context.queryClient.ensureQueryData(meQuery))) {
      throw redirect({ to: "/login" });
    }
  },
  component: AppShell,
});

const dashboardRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  validateSearch: (raw: Record<string, unknown>): { month?: string } =>
    isMonthKey(raw.month) ? { month: raw.month } : {},
  component: function DashboardRoute() {
    const { month } = dashboardRoute.useSearch();
    return <DashboardPage month={month ?? currentMonthKey()} />;
  },
});
const accountsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/accounts",
  component: AccountsPage,
});
const accountDetailRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/accounts/$accountId",
  component: function AccountDetailRoute() {
    return <AccountDetailPage accountId={accountDetailRoute.useParams().accountId} />;
  },
});
const transactionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/transactions",
  validateSearch: validateTransactionSearch,
  component: function TransactionsRoute() {
    return <TransactionsPage search={transactionsRoute.useSearch()} />;
  },
});
const contractsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/contracts",
  component: ContractsPage,
});
const contractDetailRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/contracts/$contractId",
  component: function ContractDetailRoute() {
    return <ContractDetailPage contractId={contractDetailRoute.useParams().contractId} />;
  },
});
const bankRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/bank",
  validateSearch: (raw: Record<string, unknown>): { connection?: string; error?: string } => ({
    ...(typeof raw.connection === "string" && raw.connection ? { connection: raw.connection } : {}),
    ...(typeof raw.error === "string" && raw.error ? { error: raw.error } : {}),
  }),
  component: function BankRoute() {
    const { connection, error } = bankRoute.useSearch();
    return <BankPage connection={connection} error={error} />;
  },
});
const budgetsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/budgets",
  validateSearch: (raw: Record<string, unknown>): { month?: string } =>
    isMonthKey(raw.month) ? { month: raw.month } : {},
  component: function BudgetsRoute() {
    const { month } = budgetsRoute.useSearch();
    return <BudgetsPage month={month ?? currentMonthKey()} />;
  },
});
const forecastRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/forecast",
  validateSearch: (raw: Record<string, unknown>): { months?: 1 | 2 | 3 } =>
    raw.months === undefined ? {} : { months: parseForecastMonths(raw.months) },
  component: function ForecastRoute() {
    return <ForecastPage months={parseForecastMonths(forecastRoute.useSearch().months)} />;
  },
});
const goalsRoute = createRoute({ getParentRoute: () => appRoute, path: "/goals", component: GoalsPage });
const reportsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/reports",
  validateSearch: (raw: Record<string, unknown>): { year?: number } => {
    const year = Number(raw.year);
    return Number.isInteger(year) && year >= 2000 && year <= 2100 ? { year } : {};
  },
  component: function ReportsRoute() {
    const { year } = reportsRoute.useSearch();
    return <ReportsPage year={year ?? new Date().getFullYear()} />;
  },
});
const categoriesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/categories",
  component: CategoriesPage,
});
const importRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/import",
  validateSearch: (raw: Record<string, unknown>): { account?: string } =>
    typeof raw.account === "string" && raw.account ? { account: raw.account } : {},
  component: function ImportRoute() {
    return <ImportPage account={importRoute.useSearch().account} />;
  },
});
const moreRoute = createRoute({ getParentRoute: () => appRoute, path: "/more", component: MorePage });
const householdRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/household",
  component: HouseholdPage,
});
const securityRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/security",
  component: SecurityPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  inviteRoute,
  appRoute.addChildren([
    dashboardRoute,
    accountsRoute,
    accountDetailRoute,
    transactionsRoute,
    contractsRoute,
    contractDetailRoute,
    budgetsRoute,
    forecastRoute,
    goalsRoute,
    reportsRoute,
    bankRoute,
    categoriesRoute,
    importRoute,
    moreRoute,
    householdRoute,
    securityRoute,
  ]),
]);

export function makeRouter(queryClient: QueryClient) {
  return createRouter({ routeTree, context: { queryClient }, defaultPreload: "intent" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
