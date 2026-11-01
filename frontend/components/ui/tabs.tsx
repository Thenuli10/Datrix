"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

interface TabsCtx {
  value: string;
  setValue: (v: string) => void;
  id: string;
}
const Ctx = React.createContext<TabsCtx | null>(null);

function useTabs(): TabsCtx {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("Tabs components must be used inside <Tabs>");
  return ctx;
}

const slug = (v: string) => v.replace(/[^a-zA-Z0-9_-]/g, "_");

export function Tabs({
  value,
  defaultValue,
  onValueChange,
  className,
  children,
}: {
  value?: string;
  defaultValue?: string;
  onValueChange?: (v: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const [inner, setInner] = React.useState(defaultValue ?? "");
  const id = React.useId().replace(/:/g, "");
  const current = value ?? inner;
  const setValue = React.useCallback(
    (v: string) => {
      if (value === undefined) setInner(v);
      onValueChange?.(v);
    },
    [value, onValueChange],
  );
  const ctx = React.useMemo(() => ({ value: current, setValue, id }), [current, setValue, id]);
  return (
    <Ctx.Provider value={ctx}>
      <div className={className}>{children}</div>
    </Ctx.Provider>
  );
}

export function TabsList({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  const ref = React.useRef<HTMLDivElement>(null);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const tabs = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? []);
    const i = tabs.findIndex((t) => t === document.activeElement);
    if (i < 0) return;
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    next.focus();
    next.click();
  };
  return (
    <div
      ref={ref}
      role="tablist"
      onKeyDown={onKeyDown}
      className={cn("inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-lg bg-muted p-1", className)}
      {...props}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
}) {
  const ctx = useTabs();
  const active = ctx.value === value;
  return (
    <button
      type="button"
      role="tab"
      id={`${ctx.id}-tab-${slug(value)}`}
      aria-selected={active}
      aria-controls={`${ctx.id}-panel-${slug(value)}`}
      tabIndex={active ? 0 : -1}
      onClick={() => ctx.setValue(value)}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
        active && "bg-card text-foreground shadow-sm",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  className,
  children,
  forceMount,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
  forceMount?: boolean;
}) {
  const ctx = useTabs();
  const active = ctx.value === value;
  if (!active && !forceMount) return null;
  return (
    <div
      role="tabpanel"
      hidden={!active}
      id={`${ctx.id}-panel-${slug(value)}`}
      aria-labelledby={`${ctx.id}-tab-${slug(value)}`}
      className={className}
    >
      {children}
    </div>
  );
}
