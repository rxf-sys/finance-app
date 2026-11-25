import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { useState } from "react";
import { type AppNotification, api, unwrap } from "@/api/client";
import { notificationsQuery, unreadCountQuery } from "@/api/planning-queries";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatRelativeTime } from "@/lib/relative-time";
import { cn } from "@/lib/utils";

/** Only app-internal paths are followed; anything else stays a plain notification. */
function internalLink(link: string | null): string | null {
  return link?.startsWith("/") && !link.startsWith("//") ? link : null;
}

export function NotificationBell() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { data: unread } = useQuery(unreadCountQuery);
  const { data: items = [], isPending } = useQuery({ ...notificationsQuery, enabled: open });
  const count = unread?.count ?? 0;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const markRead = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/notifications/{notification_id}/read", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: refresh,
  });
  const markAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/notifications/read-all")),
    onSuccess: refresh,
  });

  function select(item: AppNotification) {
    if (!item.read_at) markRead.mutate(item.id);
    const link = internalLink(item.link);
    if (link) {
      setOpen(false);
      router.history.push(link);
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={count > 0 ? `Benachrichtigungen, ${count} ungelesen` : "Benachrichtigungen"}
          title="Benachrichtigungen"
        >
          <Bell aria-hidden />
          {count > 0 && (
            <span className="absolute top-1 right-1 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-4 font-semibold text-on-primary">
              {count > 99 ? "99+" : count}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <p className="text-sm font-semibold">Benachrichtigungen</p>
          <Button
            variant="ghost"
            size="sm"
            disabled={count === 0 || markAll.isPending}
            onClick={() => markAll.mutate()}
          >
            Alle als gelesen markieren
          </Button>
        </div>
        <ul className="max-h-96 overflow-y-auto">
          {isPending && <li className="px-3 py-6 text-center text-sm text-text-muted">Lade …</li>}
          {!isPending && items.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-text-muted">Keine Benachrichtigungen.</li>
          )}
          {items.map((item) => (
            <li key={item.id} className="border-b border-border last:border-b-0">
              <button
                type="button"
                onClick={() => select(item)}
                className="flex w-full items-start gap-2 px-3 py-2.5 text-left hover:bg-surface-muted"
              >
                <span
                  className={cn(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    item.read_at ? "bg-transparent" : "bg-primary",
                  )}
                  role="img"
                  aria-label={item.read_at ? "gelesen" : "ungelesen"}
                />
                <span className="min-w-0 flex-1">
                  <span className={cn("block text-sm", !item.read_at && "font-semibold")}>{item.title}</span>
                  {item.body && <span className="mt-0.5 block text-xs text-text-muted">{item.body}</span>}
                  <span className="mt-1 block text-xs text-text-muted">
                    {formatRelativeTime(item.created_at)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
