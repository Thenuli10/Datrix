import { Sparkles } from "lucide-react";
import { Markdown } from "@/components/layout/common";

/** "Key insights" narrative (Insight Writer markdown, or the raw insights as bullets). */
export function InsightsPanel({ markdown, fallback }: { markdown: string | null | undefined; fallback?: string[] }) {
  // The panel has its own title, so drop the Insight Writer's leading "## Key insights" heading.
  const body = (markdown?.trim().replace(/^#{1,3}\s*key insights\s*\n+/i, "") ||
    (fallback?.length ? fallback.map((i) => `- ${i}`).join("\n") : ""));
  if (!body) return null;
  return (
    <section aria-labelledby="insights-heading" className="rounded-xl border bg-card p-5 shadow-sm">
      <h2 id="insights-heading" className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Sparkles className="size-4 text-primary" aria-hidden /> Key insights
      </h2>
      <Markdown>{body}</Markdown>
    </section>
  );
}
