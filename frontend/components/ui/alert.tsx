import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const alertVariants = cva("relative flex w-full gap-3 rounded-lg border p-4 text-sm", {
  variants: {
    variant: {
      default: "bg-card",
      info: "border-info/30 bg-info/8",
      success: "border-success/30 bg-success/8",
      warning: "border-warning/35 bg-warning/8",
      destructive: "border-destructive/40 bg-destructive/8",
    },
  },
  defaultVariants: { variant: "default" },
});

const ICONS = { default: Info, info: Info, success: CheckCircle2, warning: AlertTriangle, destructive: XCircle } as const;

const ICON_COLOR = {
  default: "text-muted-foreground",
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
} as const;

export interface AlertProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof alertVariants> {
  title?: React.ReactNode;
  icon?: boolean;
}

export function Alert({ className, variant, title, icon = true, children, ...props }: AlertProps) {
  const v = variant ?? "default";
  const Icon = ICONS[v];
  return (
    <div role={v === "destructive" ? "alert" : "status"} className={cn(alertVariants({ variant }), className)} {...props}>
      {icon && <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", ICON_COLOR[v])} />}
      <div className="min-w-0 flex-1 space-y-1">
        {title && <div className="font-medium leading-tight">{title}</div>}
        {children && <div className="text-foreground/85">{children}</div>}
      </div>
    </div>
  );
}
