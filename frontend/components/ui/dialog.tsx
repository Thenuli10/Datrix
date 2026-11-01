"use client";
import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/** Modal dialog built on the native dialog element (focus trap and Esc handling built in). */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}) {
  const ref = React.useRef<HTMLDialogElement>(null);
  React.useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={() => onOpenChange(false)}
      onClick={(e) => {
        if (e.target === ref.current) onOpenChange(false);
      }}
      className={cn(
        "m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border bg-card p-0 text-card-foreground shadow-xl backdrop:bg-black/50",
        className,
      )}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <div className="flex items-start justify-between gap-4 border-b p-5">
            <div className="space-y-1">
              <h2 className="text-base font-semibold">{title}</h2>
              {description && <p className="text-sm text-muted-foreground">{description}</p>}
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => onOpenChange(false)}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="overflow-auto p-5">{children}</div>
          {footer && <div className="flex flex-wrap justify-end gap-2 border-t p-4">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}
