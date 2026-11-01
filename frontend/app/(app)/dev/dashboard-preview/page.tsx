import { notFound } from "next/navigation";
import { Preview } from "./preview";

export const metadata = { title: "Dashboard preview (dev)" };

/** Dev-only: renders the sample fixture so the dashboard can be checked without a backend. */
export default function DashboardPreviewPage() {
  if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_ENABLE_DEV_ROUTES !== "true") notFound();
  return <Preview />;
}
