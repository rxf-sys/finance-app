import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";
import { meQuery } from "@/api/queries";
import { AppShell } from "@/components/app-shell";
import { currentMonthKey, isMonthKey } from "@/lib/dates";
import { parseForecastMonths } from "@/lib/forecast";
import { validateTransactionSearch } from "@/lib/transaction-search";
import { AccountDetailPage, AccountsPage } from "@/routes/accounts";
import { BankPage } from "@/routes/bank";
import { BudgetsPage } from "@/routes/budgets";
import { CategoriesPage } from "@/routes/categories";
import { ContractDetailPage } from "@/routes/contract-detail";
import { ContractsPage } from "@/routes/contracts";
import { DashboardPage } from "@/routes/dashboard";
import { ForecastPage } from "@/routes/forecast";
import { GoalsPage } from "@/routes/goals";
import { HouseholdPage } from "@/routes/household";
import { ImportPage } from "@/routes/import";
import { InvitePage } from "@/routes/invite";
import { LoginPage } from "@/routes/login";
import { MorePage } from "@/routes/more";
import { ReportsPage } from "@/routes/reports";
import { SecurityPage } from "@/routes/security";
import { TransactionsPage } from "@/routes/transactions";

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
