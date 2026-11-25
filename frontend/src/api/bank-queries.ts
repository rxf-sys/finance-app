import { type QueryClient, queryOptions } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "./client";

export type BankConnections =
  | { configured: false }
  | { configured: true; connections: NonNullable<Awaited<ReturnType<typeof listConnections>>["data"]> };

async function listConnections() {
  return api.GET("/api/bank-connections");
}

/** 503 means bank sync is not set up on the server; that is a state, not an error. */
export const bankConnectionsQuery = queryOptions({
  queryKey: ["bank", "connections"],
  queryFn: async (): Promise<BankConnections> => {
    const result = await listConnections();
    if (result.response.status === 503) return { configured: false };
    return { configured: true, connections: unwrap(result) };
  },
  retry: false,
  staleTime: 30_000,
});

export const aspspsQuery = (country: string) =>
  queryOptions({
    queryKey: ["bank", "aspsps", country],
    queryFn: async () =>
      unwrap(await api.GET("/api/bank-connections/aspsps", { params: { query: { country } } })),
    staleTime: 10 * 60_000,
    retry: false,
  });

export const providerAccountsQuery = (connectionId: string) =>
  queryOptions({
    queryKey: ["bank", "accounts", connectionId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/bank-connections/{connection_id}/accounts", {
          params: { path: { connection_id: connectionId } },
        }),
      ),
    retry: false,
  });

export const syncRunsQuery = (connectionId: string) =>
  queryOptions({
    queryKey: ["bank", "sync-runs", connectionId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/bank-connections/{connection_id}/sync-runs", {
          params: { path: { connection_id: connectionId } },
        }),
      ),
  });

export function invalidateBank(queryClient: QueryClient): Promise<unknown> {
  return queryClient.invalidateQueries({ queryKey: ["bank"] });
}

export { ApiError };
