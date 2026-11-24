const dateFormat = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const dateTimeFormat = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** TT.MM.JJJJ */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

/** TT.MM.JJJJ, HH:MM */
export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}

export const roleLabel: Record<"owner" | "member", string> = {
  owner: "Verwaltung",
  member: "Mitglied",
};
