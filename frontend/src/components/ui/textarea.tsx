import type { TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-20 w-full rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-text placeholder:text-text-muted",
        "focus:border-primary focus:outline-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
