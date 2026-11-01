"""The rendered-page DOM checks must ignore visually hidden text (sr-only labels): a live run flagged one as
'cut off' and spent two composer rounds on it. Real text clipping must still be caught."""
import pytest

from app.services.screenshot import DOM_CHECKS_JS

PAGE = """
<div data-widget-id="w1" style="width:300px;height:200px">
  <label style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
                clip:rect(0,0,0,0);white-space:nowrap;border:0">Search Top 10 Products by Revenue</label>
  <p style="color:#111;background:#fff;font-size:14px">Fine text</p>
</div>
<div data-widget-id="w2" style="width:300px;height:200px">
  <div style="width:60px;overflow:hidden;white-space:nowrap;color:#111;background:#fff;font-size:14px">
    A very long label that is clipped</div>
</div>
"""


def _run_checks() -> list[dict]:
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.set_content(PAGE)
            issues = page.evaluate(DOM_CHECKS_JS)
            browser.close()
            return issues
    except Exception as e:  # noqa: BLE001 - browser not installed
        pytest.skip(f"Chromium unavailable: {e}")


def test_dom_checks_ignore_sr_only_but_catch_clipping():
    issues = _run_checks()
    assert not [i for i in issues if i["widget_id"] == "w1"], issues
    assert any(i["widget_id"] == "w2" and i["rule"] == "cutoff" for i in issues), issues
