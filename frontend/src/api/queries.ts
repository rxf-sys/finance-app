import { queryOptions } from "@tanstack/react-query";
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
