import { type QueryClient, queryOptions } from "@tanstack/react-query";
import type { TransactionQuery } from "@/lib/transaction-search";
import { api, fetchMe, meQueryKey, unwrap } from "./client";

export const meQuery = queryOptions({
  queryKey: meQueryKey,
  queryFn: fetchMe,
  staleTime: 60_000,
});

export const householdQuery = queryOptions({
  queryKey: ["household"],
  queryFn: async () => unwrap(await api.GET("/api/household")),
});

export const invitesQuery = queryOptions({
  queryKey: ["household", "invites"],
  queryFn: async () => unwrap(await api.GET("/api/household/invites")),
});

export const passkeysQuery = queryOptions({
  queryKey: ["passkeys"],
  queryFn: async () => unwrap(await api.GET("/api/auth/passkeys")),
});

export const accountsQuery = queryOptions({
  queryKey: ["accounts"],
  queryFn: async () => unwrap(await api.GET("/api/accounts")),
});

export const categoriesQuery = queryOptions({
  queryKey: ["categories"],
  queryFn: async () => unwrap(await api.GET("/api/categories")),
});

export const tagsQuery = queryOptions({
  queryKey: ["tags"],
  queryFn: async () => unwrap(await api.GET("/api/tags")),
});

export const rulesQuery = queryOptions({
  queryKey: ["rules"],
  queryFn: async () => unwrap(await api.GET("/api/rules")),
});

export const dashboardQuery = (month: string) =>
  queryOptions({
    queryKey: ["dashboard", month],
    queryFn: async () => unwrap(await api.GET("/api/dashboard", { params: { query: { month } } })),
  });

export const balanceHistoryQuery = (accountId: string, months = 12) =>
  queryOptions({
    queryKey: ["accounts", accountId, "balance-history", months],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/accounts/{account_id}/balance-history", {
          params: { path: { account_id: accountId }, query: { months } },
        }),
      ),
  });

export const transactionsQuery = (query: TransactionQuery) =>
  queryOptions({
    queryKey: ["transactions", "list", query],
    queryFn: async () => unwrap(await api.GET("/api/transactions", { params: { query } })),
    placeholderData: (previous) => previous,
  });

export const transactionQuery = (id: string) =>
  queryOptions({
    queryKey: ["transactions", "detail", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/transactions/{transaction_id}", { params: { path: { transaction_id: id } } }),
      ),
  });

export const transferCandidatesQuery = (id: string) =>
  queryOptions({
    queryKey: ["transactions", "candidates", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/transactions/{transaction_id}/transfer-candidates", {
          params: { path: { transaction_id: id } },
        }),
      ),
  });

export const importPresetsQuery = queryOptions({
  queryKey: ["imports", "presets"],
  queryFn: async () => unwrap(await api.GET("/api/imports/presets")),
  staleTime: Number.POSITIVE_INFINITY,
});

export const importProfilesQuery = queryOptions({
  queryKey: ["imports", "profiles"],
  queryFn: async () => unwrap(await api.GET("/api/imports/profiles")),
});

export const importRunsQuery = (accountId: string) =>
  queryOptions({
    queryKey: ["imports", "runs", accountId],
    queryFn: async () =>
      unwrap(await api.GET("/api/imports", { params: { query: { account_id: accountId } } })),
  });

/** Everything derived from transactions: lists, balances, dashboard numbers and category counts. */
export function invalidateLedger(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(
    [
      "transactions",
      "accounts",
      "dashboard",
      "categories",
      "imports",
      "budgets",
      "available",
      "forecast",
      "goals",
      "reports",
    ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
  );
}
