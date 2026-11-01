import type { Metadata } from "next";

export const metadata: Metadata = { title: "Dashboard render", robots: { index: false } };

/** No app chrome: these pages are screenshotted by the backend. */
export default function RenderLayout({ children }: { children: React.ReactNode }) {
  return children;
}
