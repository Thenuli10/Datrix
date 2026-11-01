"use client";
import * as React from "react";
import { FileSpreadsheet, UploadCloud, X } from "lucide-react";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

export function validateFiles(files: File[]): { ok: File[]; errors: string[] } {
  const ok: File[] = [];
  const errors: string[] = [];
  for (const f of files) {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) errors.push(`${f.name}: unsupported type (use CSV, Excel, Parquet or JSON).`);
    else if (f.size > MAX_UPLOAD_BYTES) errors.push(`${f.name} is ${formatBytes(f.size)}; the limit is ${MAX_UPLOAD_MB} MB.`);
    else if (f.size === 0) errors.push(`${f.name} is empty.`);
    else ok.push(f);
  }
  return { ok, errors };
}

/** Multi-file drag & drop picker with client-side type and 200 MB size validation. */
export function FileDropzone({
  files,
  onChange,
  disabled,
  label = "Drop data files here",
}: {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
  label?: string;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [drag, setDrag] = React.useState(false);
  const [errors, setErrors] = React.useState<string[]>([]);
  const inputId = React.useId();

  const add = (list: FileList | null) => {
    if (!list) return;
    const { ok, errors } = validateFiles(Array.from(list));
    setErrors(errors);
    const names = new Set(files.map((f) => `${f.name}:${f.size}`));
    onChange([...files, ...ok.filter((f) => !names.has(`${f.name}:${f.size}`))]);
  };

  return (
    <div className="space-y-3">
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (!disabled) add(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors focus-within:outline-2 focus-within:outline-ring",
          drag ? "border-primary bg-primary/6" : "hover:border-primary/50 hover:bg-muted/40",
          disabled && "pointer-events-none opacity-60",
        )}
      >
        <UploadCloud className="size-7 text-muted-foreground" aria-hidden />
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">
          or <span className="text-primary underline">browse</span> · CSV, Excel, Parquet, JSON · up to {MAX_UPLOAD_MB} MB each · several files allowed
        </div>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="sr-only"
          disabled={disabled}
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
      </label>
      {errors.length > 0 && (
        <ul role="alert" className="space-y-1 text-sm text-destructive">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {files.length > 0 && (
        <ul className="divide-y rounded-lg border" aria-label="Selected files">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-3 px-3 py-2 text-sm">
              <FileSpreadsheet className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate" title={f.name}>
                {f.name}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(f.size)}</span>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(files.filter((_, j) => j !== i))}
                aria-label={`Remove ${f.name}`}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
