"""Dashboard screenshots + rendered-page checks with headless Chromium (PLAN.md §7b step 2).

Opens `{frontend_url}/render/runs/{id}` at desktop and mobile widths in light and dark mode.
Never raises: if Playwright, the browser or the frontend is unavailable it returns no
screenshots, and QA falls back to the rule checks.
"""
import logging
from pathlib import Path

from app.core.config import settings
from app.schemas import DashboardIssue

log = logging.getLogger(__name__)

VIEWPORTS = [("desktop", 1440, 900), ("mobile", 390, 844)]
THEMES = ["light", "dark"]

# Runs in the page. Widgets carry data-widget-id (set by the frontend SpecRenderer).
DOM_CHECKS_JS = """
() => {
  const issues = [];
  const lum = (c) => {
    const m = c.match(/\\d+(\\.\\d+)?/g); if (!m) return null;
    const [r, g, b] = m.slice(0, 3).map(v => { v = v / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const bgOf = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const bg = getComputedStyle(e).backgroundColor;
      if (bg && !bg.startsWith('rgba(0, 0, 0, 0)') && bg !== 'transparent') return bg;
    }
    return 'rgb(255,255,255)';
  };
  const seen = new Set();
  const add = (id, rule, severity, message) => {
    const k = id + rule; if (seen.has(k)) return; seen.add(k);
    issues.push({ widget_id: id, rule, severity, message });
  };
  document.querySelectorAll('[data-widget-id]').forEach(card => {
    const id = card.getAttribute('data-widget-id');
    if (card.scrollWidth > card.clientWidth + 2 || card.scrollHeight > card.clientHeight + 2)
      add(id, 'overflow', 'medium', 'Content overflows its card');
    card.querySelectorAll('*').forEach(el => {
      if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') return;
      // Visually hidden on purpose (e.g. sr-only labels for screen readers): not cut off.
      const box = el.getBoundingClientRect();
      if (box.width <= 1 || box.height <= 1 || cs.clip === 'rect(0px, 0px, 0px, 0px)') return;
      const size = parseFloat(cs.fontSize);
      if (size && size < 11) add(id, 'small_text', 'low', `Text is ${size}px (< 11px)`);
      if (cs.textOverflow !== 'ellipsis' && el.scrollWidth > el.clientWidth + 2 && cs.overflow === 'hidden')
        add(id, 'cutoff', 'medium', 'Text is cut off');
      const l1 = lum(cs.color), l2 = lum(bgOf(el));
      if (l1 !== null && l2 !== null) {
        const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        if (ratio < 4.5 && size < 24) add(id, 'contrast', 'medium', `Low contrast ${ratio.toFixed(2)}:1 (WCAG AA needs 4.5:1)`);
      }
    });
  });
  return issues;
}
"""


def capture(run_id: int, out_dir: Path) -> tuple[list[Path], list[DashboardIssue]]:
    """Return (screenshot paths, DOM issues). Desktop-light first (used as the thumbnail)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info("playwright not installed; skipping screenshots")
        return [], []
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    issues: dict[tuple[str | None, str], DashboardIssue] = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for name, width, height in VIEWPORTS:
                    for theme in THEMES:
                        page = browser.new_page(viewport={"width": width, "height": height},
                                                color_scheme=theme)  # type: ignore[arg-type]
                        url = f"{settings.frontend_url}/render/runs/{run_id}?theme={theme}"
                        page.goto(url, wait_until="networkidle", timeout=30_000)
                        try:
                            page.wait_for_selector("[data-ready='true']", timeout=20_000)
                        except Exception:
                            log.warning("render page for run %s never signalled ready", run_id)
                        path = out_dir / f"{name}-{theme}.png"
                        page.screenshot(path=str(path), full_page=True)
                        paths.append(path)
                        for raw in page.evaluate(DOM_CHECKS_JS):
                            raw["message"] = f"[{name}/{theme}] {raw['message']}"
                            issues.setdefault((raw["widget_id"], raw["rule"]), DashboardIssue(**raw))
                        page.close()
            finally:
                browser.close()
    except Exception as e:  # QA failure never blocks the dashboard (§13)
        log.warning("screenshot capture failed: %s", e)
        return paths, list(issues.values())
    return paths, list(issues.values())
