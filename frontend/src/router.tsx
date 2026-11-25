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
import { validateTransactionSearch } from "@/lib/transaction-search";
import { AccountDetailPage, AccountsPage } from "@/routes/accounts";
import { CategoriesPage } from "@/routes/categories";
import { DashboardPage } from "@/routes/dashboard";
import { HouseholdPage } from "@/routes/household";
import { ImportPage } from "@/routes/import";
import { InvitePage } from "@/routes/invite";
import { LoginPage } from "@/routes/login";
import { MorePage } from "@/routes/more";
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
