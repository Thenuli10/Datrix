"use client";
import * as React from "react";
import { Monitor, Moon, Sun } from "lucide-react";

export type ThemePref = "light" | "dark" | "system";
export const THEME_KEY = "datrix-theme";

/**
 * Inline script run before paint. Order: `?theme=light|dark` URL param (used by the
 * Playwright screenshot service, not persisted) → saved preference → system preference.
 */
export const themeInitScript = `(function(){try{var q=new URLSearchParams(location.search).get('theme');var s=(q==='light'||q==='dark')?q:localStorage.getItem('${THEME_KEY}');var d=s==='dark'||((!s||s==='system')&&window.matchMedia('(prefers-color-scheme: dark)').matches);var r=document.documentElement;r.classList.toggle('dark',d);r.style.colorScheme=d?'dark':'light';}catch(e){}})();`;

export function applyTheme(pref: ThemePref) {
  const dark =
    pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

/** Observe the `dark` class on <html> (charts re-theme when it changes). */
export function useIsDark(): boolean {
  const [dark, setDark] = React.useState(false);
  React.useEffect(() => {
    const root = document.documentElement;
    const update = () => setDark(root.classList.contains("dark"));
    update();
    const obs = new MutationObserver(update);
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

export function ThemeToggle() {
  const [pref, setPref] = React.useState<ThemePref>("system");
  React.useEffect(() => setPref(readPref()), []);

  React.useEffect(() => {
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [pref]);

  const cycle = () => {
    const next: ThemePref = pref === "system" ? "light" : pref === "light" ? "dark" : "system";
    setPref(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* ignore */
    }
    applyTheme(next);
  };

  const Icon = pref === "light" ? Sun : pref === "dark" ? Moon : Monitor;
  const label = pref === "system" ? "System theme" : pref === "light" ? "Light theme" : "Dark theme";
  return (
    <button
      type="button"
      onClick={cycle}
      title={`${label} (click to change)`}
      aria-label={`${label}. Click to change theme`}
      className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <Icon className="size-4" />
    </button>
  );
}
