import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const alertVariants = cva("rounded-lg border px-3 py-2 text-sm", {
  variants: {
    tone: {
      error: "border-negative/40 bg-negative/10 text-negative",
      success: "border-positive/40 bg-positive/10 text-positive",
      info: "border-info/40 bg-info/10 text-info",
    },
  },
  defaultVariants: { tone: "info" },
});

type AlertProps = HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>;

export function Alert({ className, tone, ...props }: AlertProps) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(alertVariants({ tone }), className)}
      {...props}
    />
  );
}
