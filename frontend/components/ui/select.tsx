import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/** Native select styled like the other inputs (accessible, works well on mobile). */
export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement> & { wrapperClassName?: string }
>(({ className, wrapperClassName, children, ...props }, ref) => (
  <div className={cn("relative", wrapperClassName)}>
    <select
      ref={ref}
      className={cn(
        "h-9 w-full appearance-none truncate rounded-md border border-input bg-card py-1 pl-3 pr-8 text-sm shadow-xs focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown
      aria-hidden
      className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
    />
  </div>
));
Select.displayName = "Select";
