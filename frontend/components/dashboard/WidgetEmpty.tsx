import { BarChart3 } from "lucide-react";

export function WidgetEmpty({ message = "No data for this widget." }: { message?: string }) {
  return (
    <div className="flex h-full min-h-16 flex-col items-center justify-center gap-1.5 text-center text-sm text-muted-foreground">
      <BarChart3 className="size-5 opacity-60" aria-hidden />
      <span>{message}</span>
    </div>
  );
}
