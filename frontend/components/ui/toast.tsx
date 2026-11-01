"use client";
import * as React from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  description?: string;
}

interface ToastApi {
  toast: (t: Omit<ToastItem, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastCtx = React.createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);
  const nextId = React.useRef(1);
  const dismiss = React.useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const toast = React.useCallback(
    (t: Omit<ToastItem, "id">) => {
      const id = nextId.current++;
      setItems((xs) => [...xs.slice(-3), { ...t, id }]);
      setTimeout(() => dismiss(id), t.kind === "error" ? 8000 : 4500);
    },
    [dismiss],
  );
  const api = React.useMemo<ToastApi>(
    () => ({
      toast,
      success: (title, description) => toast({ kind: "success", title, description }),
      error: (title, description) => toast({ kind: "error", title, description }),
      info: (title, description) => toast({ kind: "info", title, description }),
    }),
    [toast],
  );
  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 left-4 z-50 flex flex-col items-end gap-2 sm:left-auto"
      >
        {items.map((t) => {
          const Icon = t.kind === "success" ? CheckCircle2 : t.kind === "error" ? XCircle : Info;
          return (
            <div
              key={t.id}
              role={t.kind === "error" ? "alert" : "status"}
              className="pointer-events-auto flex w-full max-w-sm gap-3 rounded-lg border bg-card p-3 text-sm shadow-lg"
            >
              <Icon
                aria-hidden
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  t.kind === "success" && "text-success",
                  t.kind === "error" && "text-destructive",
                  t.kind === "info" && "text-info",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{t.title}</div>
                {t.description && <div className="mt-0.5 break-words text-muted-foreground">{t.description}</div>}
              </div>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => dismiss(t.id)}
                className="rounded p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = React.useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
