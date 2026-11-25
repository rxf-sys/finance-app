import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Me = components["schemas"]["Me"];
export type LoginResponse = components["schemas"]["LoginResponse"];
export type Household = components["schemas"]["HouseholdOut"];
export type Invite = components["schemas"]["InviteOut"];
export type InviteCreated = components["schemas"]["InviteCreated"];
export type Passkey = components["schemas"]["Passkey"];

type Schemas = components["schemas"];
export type Account = Schemas["AccountOut"];
export type AccountInput = Schemas["AccountCreate"];
export type AccountKind = Account["kind"];
export type AccountVisibility = Account["visibility"];
export type BalancePoint = Schemas["BalancePoint"];
export type Category = Schemas["CategoryOut"];
export type CategoryKind = Category["kind"];
export type Rule = Schemas["RuleOut"];
export type RuleConditions = Schemas["RuleConditions"];
export type Tag = Schemas["TagOut"];
export type Transaction = Schemas["TransactionOut"];
export type TransactionDetail = Schemas["TransactionDetail"];
export type TransactionCreate = Schemas["TransactionCreate"];
export type Dashboard = Schemas["DashboardOut"];
export type Contract = Schemas["ContractOut"];
export type ContractDetail = Schemas["ContractDetail"];
export type ContractCreate = Schemas["ContractCreate"];
export type ContractUpdate = Schemas["ContractUpdate"];
export type ContractKind = Contract["kind"];
export type ContractInterval = Contract["interval"];
export type ContractStatus = Contract["status"];
export type ContractSummary = Schemas["ContractSummary"];
export type PriceChange = Schemas["PriceChangeOut"];
export type BudgetStatus = Schemas["BudgetStatusOut"];
export type Available = Schemas["AvailableOut"];
export type AppNotification = Schemas["NotificationOut"];

export const api = createClient<paths>({ baseUrl: "/", credentials: "same-origin" });

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(errorMessage(status));
    this.status = status;
  }
}

/** Throws ApiError for non-2xx responses, otherwise returns the parsed body. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) {
    throw new ApiError(result.response.status);
  }
  return result.data as T;
}

/** German, user-facing message for an HTTP status. Endpoint-specific wording lives in the pages. */
export function errorMessage(status: number): string {
  switch (status) {
    case 400:
      return "Die Eingabe wurde nicht akzeptiert.";
    case 401:
      return "Nicht angemeldet oder Anmeldung abgelaufen.";
    case 403:
      return "Dafür fehlt die Berechtigung.";
    case 404:
      return "Nicht gefunden oder abgelaufen.";
    case 409:
      return "Das gibt es bereits.";
    case 422:
      return "Bitte die Eingaben prüfen.";
    case 429:
      return "Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.";
    default:
      return "Etwas ist schiefgelaufen. Bitte später erneut versuchen.";
  }
}

/** German message for a failed mutation, or null while there is no error. */
export function mutationErrorMessage(
  error: unknown,
  overrides: Partial<Record<number, string>> = {},
): string | null {
  if (!error) return null;
  if (error instanceof ApiError) return overrides[error.status] ?? error.message;
  return errorMessage(0);
}

export const meQueryKey = ["me"] as const;

export async function fetchMe(): Promise<Me | null> {
  const result = await api.GET("/api/auth/me");
  if (result.response.status === 401) {
    return null;
  }
  return unwrap(result);
}
