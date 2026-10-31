"""Drive the real dashboard with Chromium: capture screenshots and measure load time on a 10 Mbps link (NFR-02)."""
import json
import os
import subprocess
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screens")
os.makedirs(OUT, exist_ok=True)
PORT = 8790
BASE = f"http://127.0.0.1:{PORT}"
env = {**os.environ, "PYTHONPATH": ROOT, "SIM_TIME_SCALE": "25", "SIM_CRITICAL_AFTER_S": "10"}
env.pop("FIRESIGHT_NO_AUTOAPP", None)
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env)
for _ in range(60):
    try:
        httpx.get(BASE + "/api/v1/health", timeout=1)
        break
    except Exception:
        time.sleep(0.3)

metrics = {}
try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        skip_tiles = lambda route: route.abort() if "openstreetmap" in route.request.url else route.continue_()

        # ---- NFR-02: cold load of the dashboard on a throttled 10 Mbps / 40 ms link (map tiles are third-party, blocked)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.route("**/*", skip_tiles)
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 40,
                                                     "downloadThroughput": 10_000_000 / 8, "uploadThroughput": 10_000_000 / 8})
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        loads = []
        for _ in range(5):
            t0 = time.time()
            page.goto(BASE + "/", wait_until="load")
            page.wait_for_selector("#loginForm")
            loads.append(round(time.time() - t0, 3))
        metrics["dashboard_load_s_10mbps"] = {"runs": loads, "max": max(loads), "median": sorted(loads)[2]}
        page.screenshot(path=f"{OUT}/01_login.png")
        ctx.close()

        # ---- operator session: raise a simulated CAD call
        octx = browser.new_context(viewport={"width": 1440, "height": 900})
        op = octx.new_page()
        op.route("**/*", skip_tiles)
        op.goto(BASE + "/")
        op.fill("#u", "operator1"); op.fill("#p", "firesight123"); op.click("#loginForm button")
        op.wait_for_selector("#login", state="hidden")
        op.wait_for_function("document.getElementById('status').textContent==='live'")
        time.sleep(1.0)
        op.screenshot(path=f"{OUT}/02_dashboard_idle.png")
        op.click("#simBtn")
        op.wait_for_function("document.getElementById('tDrone').textContent!=='-'", timeout=20000)
        time.sleep(3)
        op.screenshot(path=f"{OUT}/03_drone_en_route.png")
        op.wait_for_function("document.getElementById('banner').style.display==='block'", timeout=60000)
        time.sleep(2)
        op.screenshot(path=f"{OUT}/04_critical_detection.png")

        # ---- commander session: message the crew, close incident, read report
        cctx = browser.new_context(viewport={"width": 1440, "height": 900})
        cm = cctx.new_page()
        cm.route("**/*", skip_tiles)
        cm.goto(BASE + "/")
        cm.fill("#u", "commander1"); cm.fill("#p", "firesight123"); cm.click("#loginForm button")
        cm.wait_for_selector("#login", state="hidden")
        cm.wait_for_selector("#incidents div")
        cm.click("#incidents div")
        time.sleep(1.5)
        cm.fill("#msg", "Crew 1: approach from the north side, drone shows two hotspots at the rear")
        cm.click("#send")
        time.sleep(1.0)
        cm.screenshot(path=f"{OUT}/05_commander_message.png")
        cm.click("#closeBtn")
        cm.wait_for_selector("#reportBox", state="visible", timeout=10000)
        cm.evaluate("document.querySelector('aside').scrollTop = 1e6")
        time.sleep(0.5)
        cm.screenshot(path=f"{OUT}/06_report.png")
        metrics["report_text"] = cm.inner_text("#report")

        # ---- crew role sees no telemetry/AI panels (privacy check)
        kctx = browser.new_context(viewport={"width": 1440, "height": 900})
        cr = kctx.new_page()
        cr.route("**/*", skip_tiles)
        cr.goto(BASE + "/")
        cr.fill("#u", "crew1"); cr.fill("#p", "firesight123"); cr.click("#loginForm button")
        cr.wait_for_selector("#login", state="hidden")
        time.sleep(1.0)
        cr.screenshot(path=f"{OUT}/07_crew_view.png")
        browser.close()
finally:
    srv.terminate()
    srv.wait(10)
json.dump(metrics, open(os.path.join(ROOT, "artifacts", "ui_metrics.json"), "w"), indent=2)
print(json.dumps(metrics, indent=2))
