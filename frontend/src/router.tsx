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
import { DashboardPage } from "@/routes/dashboard";
import { HouseholdPage } from "@/routes/household";
import { InvitePage } from "@/routes/invite";
import { LoginPage } from "@/routes/login";
import { SecurityPage } from "@/routes/security";

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

const dashboardRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: DashboardPage });
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
  appRoute.addChildren([dashboardRoute, householdRoute, securityRoute]),
]);

export function makeRouter(queryClient: QueryClient) {
  return createRouter({ routeTree, context: { queryClient }, defaultPreload: "intent" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
