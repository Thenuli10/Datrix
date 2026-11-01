"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export interface RadioOption<T extends string> {
  value: T;
  label: string;
  description?: string;
}

/** Accessible radio group rendered as selectable cards. No option is preselected unless `value` is set. */
export function RadioCards<T extends string>({
  legend,
  options,
  value,
  onChange,
  disabled,
  required,
}: {
  legend: string;
  options: RadioOption<T>[];
  value: T | null;
  onChange: (v: T) => void;
  disabled?: boolean;
  required?: boolean;
}) {
  const name = React.useId();
  return (
    <fieldset disabled={disabled} className="space-y-2">
      <legend className="mb-2 text-sm font-medium">
        {legend}
        {required && <span className="text-destructive"> *</span>}
      </legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((o) => {
          const checked = value === o.value;
          return (
            <label
              key={o.value}
              className={cn(
                "flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors focus-within:outline-2 focus-within:outline-ring hover:bg-muted/50",
                checked && "border-primary bg-primary/6",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                type="radio"
                name={name}
                value={o.value}
                checked={checked}
                required={required}
                onChange={() => onChange(o.value)}
                className="mt-0.5 accent-[var(--primary)]"
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{o.label}</span>
                {o.description && <span className="block text-xs text-muted-foreground">{o.description}</span>}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
