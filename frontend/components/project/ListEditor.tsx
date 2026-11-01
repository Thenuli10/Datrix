"use client";
import * as React from "react";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

/** Editable list of short strings shown as removable chips (features, metrics, …). */
export function ChipListEditor({
  label,
  values,
  onChange,
  suggestions = [],
  placeholder = "Add…",
  readOnly,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
  readOnly?: boolean;
}) {
  const [draft, setDraft] = React.useState("");
  const id = React.useId();
  const listId = `${id}-suggestions`;
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium" id={`${id}-label`}>
        {label}
      </div>
      <ul className="flex flex-wrap gap-1.5" aria-labelledby={`${id}-label`}>
        {values.length === 0 && <li className="text-sm text-muted-foreground">None</li>}
        {values.map((v) => (
          <li key={v} className="inline-flex max-w-full items-center gap-1 rounded-full border bg-muted/60 py-0.5 pr-1 pl-2.5 text-xs">
            <span className="truncate" title={v}>
              {v}
            </span>
            {!readOnly && (
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                aria-label={`Remove ${v}`}
                className="rounded-full p-0.5 text-muted-foreground hover:bg-card hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {!readOnly && (
        <div className="flex gap-2">
          <label htmlFor={id} className="sr-only">
            Add to {label}
          </label>
          <Input
            id={id}
            list={suggestions.length ? listId : undefined}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            placeholder={placeholder}
            className="h-8 text-xs"
          />
          {suggestions.length > 0 && (
            <datalist id={listId}>
              {suggestions.filter((s) => !values.includes(s)).map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          )}
          <Button variant="outline" size="sm" onClick={add} disabled={!draft.trim()} aria-label={`Add to ${label}`}>
            <Plus />
          </Button>
        </div>
      )}
    </div>
  );
}

/** Editable list of sentences (assumptions, expected outputs). */
export function TextListEditor({
  label,
  values,
  onChange,
  placeholder,
  readOnly,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  readOnly?: boolean;
}) {
  const id = React.useId();
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium" id={id}>
        {label}
      </div>
      <ul className="space-y-2" aria-labelledby={id}>
        {values.map((v, i) => (
          <li key={i} className="flex items-center gap-2">
            {readOnly ? (
              <span className="text-sm">• {v}</span>
            ) : (
              <>
                <Input
                  aria-label={`${label} ${i + 1}`}
                  value={v}
                  onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))}
                  className="h-8 text-sm"
                />
                <Button variant="ghost" size="icon" aria-label={`Remove ${label} ${i + 1}`} onClick={() => onChange(values.filter((_, j) => j !== i))}>
                  <X />
                </Button>
              </>
            )}
          </li>
        ))}
        {values.length === 0 && <li className="text-sm text-muted-foreground">None</li>}
      </ul>
      {!readOnly && (
        <Button variant="outline" size="sm" onClick={() => onChange([...values, ""])}>
          <Plus /> {placeholder ?? "Add"}
        </Button>
      )}
    </div>
  );
}
