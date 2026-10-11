"""UI smoke test + README screenshots, driving the real page in the installed Microsoft Edge.

    pip install playwright      (no browser download needed; uses installed Edge)
    python -m app.server        then, in another window:  python tools/ui_smoke.py

Makes about 5 AI calls (1-2 minutes). Also saves docs/sample-report.pdf. Fails loudly if a check does not hold.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(__file__).resolve().parent.parent / "docs"
OUT.mkdir(exist_ok=True)
AI = 120_000  # ms to wait for an AI answer


def check(cond, msg):
    if not cond:
        raise SystemExit("FAILED: " + msg)
    print("  ok -", msg)


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))

    print("Page layout")
    pg.goto(BASE + "/")
    pg.click(".lang button[data-l=en]")
    check(pg.locator("#go-fastmode, #p-fast").count() == 0, "Fast Mode removed")
    check(pg.locator("#legend").count() == 0 and "Answer states" not in pg.inner_text("body"), "'Answer states' legend removed")
    check(pg.locator("#tab-case").count() == 0 and pg.locator("#dl").is_visible(), "no Case summary tab; Download report button at the top")

    print("English question + follow-up")
    pg.fill("#q", "My plot is 200 sq m on a 9 m road. How much gap do I leave at the front, how many floors can I build, and what fee do I pay?")
    pg.click("#go")
    pg.wait_for_selector("#result .ans .badge", timeout=AI)
    text = pg.inner_text("#result")
    check("**" not in text, "answer formatting rendered (no raw ** markers)")
    check(pg.locator("#result .cite .v.y").count() >= 1, "at least one verified quote")
    check(pg.locator("#result .amend").count() >= 1, "28 Aug 2026 amendment warning shown for a 200 sq m plot")
    check(pg.locator("#fq").count() == 1, "follow-up box offered")
    meta = pg.inner_text("#result .meta")
    check("1 AI request" in meta or "saved answer" in meta, "setback + floors + fee question answered with a single AI request")
    pg.wait_for_timeout(400)  # let the fade-in finish
    pg.screenshot(path=OUT / "screenshot-english.png", full_page=True)

    pg.fill("#fq", "And if the road were 12 m wide instead?")
    pg.click("#go-follow")
    pg.wait_for_function("document.querySelectorAll('#result details.turn').length === 1 && document.querySelector('#fq')", timeout=AI)
    latest = pg.inner_text("#result .ans:not(details .ans)")
    check("3.6" in latest, "follow-up keeps the 200 sq m plot and answers 3.6 m front for a 12 m road")
    check(pg.locator("#result details.turn").count() == 1, "earlier question kept (collapsed) in the thread")
    pg.click("#result details.turn > summary")
    pg.wait_for_selector("#result details.turn > .close-d")
    pg.click("#result details.turn > .close-d")
    check(not pg.eval_on_selector("#result details.turn", "d => d.open"), "an opened panel has a Close button that closes it")
    pg.click("#result details.turn > summary")
    pg.wait_for_timeout(150)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(150)
    check(not pg.eval_on_selector("#result details.turn", "d => d.open"), "Esc closes the last opened panel")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT / "screenshot-followup.png", full_page=True)

    pg.click("#b-new")
    check(pg.inner_text("#result").strip() == "", "New question clears the conversation")

    print("Hindi question")
    pg.click(".lang button[data-l=hi]")
    pg.fill("#q", "मेरा प्लॉट 200 वर्ग मीटर का है और सामने 9 मीटर चौड़ी सड़क है। आगे कितनी जगह खाली छोड़नी होगी?")
    pg.click("#go")
    pg.wait_for_selector("#result .ans .badge", timeout=AI)
    check(any("ऀ" <= ch <= "ॿ" for ch in pg.inner_text("#result .answer")), "Hindi answer in Devanagari")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT / "screenshot-hindi.png", full_page=True)
    pg.click(".lang button[data-l=en]")

    print("Out-of-scope question + answer cache")
    pg.fill("#q", "How do I pay my property tax online?")
    pg.click("#go")
    pg.wait_for_selector("#result .badge.nf", timeout=AI)
    check(True, "property tax answered 'Not found in the rules'")
    nf_style = pg.eval_on_selector("#result .ans.nf", "e => getComputedStyle(e).borderLeftStyle")
    check(nf_style == "dashed", "'not found' card is visually distinct (dashed border, own colour and icon)")
    check(pg.locator("#result .ans.nf .cite").count() == 0, "'not found' answer shows no rule citations")
    check("general knowledge" in pg.inner_text("#result .state-x.nf"), "'not found' explains nothing was filled in from general knowledge")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT / "screenshot-not-found.png", full_page=True)
    pg.fill("#q", "How do I pay my property tax online?")
    pg.click("#go")
    pg.wait_for_function("document.querySelector('#result .meta') && document.querySelector('#result .meta').innerText.includes('saved answer')", timeout=AI)
    check(True, "asking the same question again returns the saved answer instantly")

    print("Setback & FAR: validation, calculation, compare")
    pg.click("#tab-plot")
    pg.fill("#ph", "15")
    pg.wait_for_function("document.querySelector('#go-plot').disabled")
    err = pg.inner_text("#sc-a [data-err=proposed_height_m]")
    check("12.5" in err and "Rule" in err and pg.eval_on_selector("#ph", "e => e.classList.contains('invalid')"),
          "height above the Rule 42 limit is highlighted with the rule, and Calculate is disabled")
    pg.select_option("#pt", "detached")
    pg.wait_for_function("document.querySelector('#sc-a [data-err=building_type]').textContent.includes('Rule 53')")
    check(True, "building type that does not fit the plot (Rule 53) is highlighted")
    pg.fill("#ph", "")
    pg.select_option("#pt", "")
    pg.fill("#pa", "-5")
    pg.wait_for_function("document.querySelector('#sc-a [data-err=plot_area_sqm]').textContent.length > 0")
    check(pg.is_disabled("#go-plot"), "negative plot area is rejected")
    pg.fill("#pa", "200")
    pg.fill("#pf", "10")
    pg.wait_for_function("!document.querySelector('#go-plot').disabled")
    pg.click("#go-plot")
    pg.wait_for_selector("#res-plot table.calc")
    plot = pg.inner_text("#res-plot")
    check("Front open space" in plot and "2.5 m" in plot and "250.0 sq m" in plot, "200 sq m / 9 m road: rear 2.5 m, max built-up 250 sq m")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT / "screenshot-calculator.png", full_page=True)
    pg.click("#go-compare")
    pg.fill("#cb-road", "12")
    pg.fill("#cb-area", "250")
    pg.fill("#cb-front", "")
    pg.wait_for_timeout(500)
    pg.wait_for_function("!document.querySelector('#go-plot').disabled")
    pg.click("#go-plot")
    pg.wait_for_selector("#res-plot table.cmp")
    changed = pg.locator("#res-plot table.cmp tr.chg").all_inner_texts()
    check(any("Front open space" in r and "3 m" in r and "3.6 m" in r for r in changed), "compare: road 9 m -> 12 m changes front space 3 m -> 3.6 m")
    check(any("Rear open space" in r and "2.5 m" in r and "3 m" in r for r in changed), "compare: plot 200 -> 250 sq m changes rear space 2.5 m -> 3 m")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT / "screenshot-compare.png", full_page=True)

    print("Fee: validation, building and development fee")
    pg.click("#tab-fee")
    pg.fill("#ba", "0")
    pg.wait_for_function("document.querySelector('#go-fee').disabled")
    check(pg.inner_text("#fee-b [data-err=built_up_area_sqm]") != "", "zero built-up area is rejected")
    pg.fill("#ba", "250")
    pg.wait_for_function("!document.querySelector('#go-fee').disabled")
    pg.click("#go-fee")
    pg.wait_for_selector("#res-fee table.calc")
    check("3,250" in pg.inner_text("#res-fee"), "fee for 250 sq m residential totals Rs 3,250")
    pg.click("#m-development")
    check(pg.locator("#fee-b").is_hidden() and pg.locator("#fee-d").is_visible(), "fee toggle switches to development permission inputs")
    pg.fill("#da", "1.2")
    pg.select_option("#du", "ha")
    pg.wait_for_function("!document.querySelector('#go-fee').disabled")
    pg.click("#go-fee")
    pg.wait_for_selector("#res-fee table.calc")
    dev = pg.inner_text("#res-fee")
    check("10,000" in dev and "90,000" in dev and "1,00,000" in dev, "1.2 ha residential (Bhopal): Rs 10,000 + Rs 90,000 = Rs 1,00,000")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT / "screenshot-devfee.png", full_page=True)
    check("computed in code" not in pg.inner_text("body").lower(), "no 'computed in code' text anywhere on the page")

    print("Download report (PDF)")
    check(pg.inner_text("#dl-n").strip() not in ("", "0"), "download button counts the items done this session")
    with pg.expect_download() as dl:
        pg.click("#dl")
    data = Path(dl.value.path()).read_bytes()
    check(data[:5] == b"%PDF-" and len(data) > 30000 and dl.value.suggested_filename.endswith(".pdf"),
          f"one PDF downloaded with everything from the session ({len(data) // 1024} KB, {dl.value.suggested_filename})")
    (OUT / "sample-report.pdf").write_bytes(data)

    print("Rules browser (offline)")
    pg.click("#tab-rules")
    pg.wait_for_selector("#rule-list details")
    check(pg.locator("#rule-list details").count() >= 5, "rules grouped by part for browsing")
    pg.click("#rule-list details > summary")
    pg.click("#collapse-all")
    check(pg.locator("#rule-list details[open]").count() == 0, "'Close all' closes the opened rule groups")
    pg.fill("#rs", "balcony electric")
    pg.click("#go-search")
    pg.wait_for_selector("#res-search .hit")
    check("Rule 52" in pg.inner_text("#res-search"), "search 'balcony electric' finds Rule 52")
    pg.click("#res-search .hit button")
    pg.wait_for_selector("#rule-view blockquote")
    check("2.5" in pg.inner_text("#rule-view"), "clicking a result shows the full rule text")
    pg.click("#rule-view .close-d")
    check(pg.inner_text("#rule-view").strip() == "", "the opened rule text can be closed")

    check(not errors, "no JavaScript errors on the page" + (f": {errors}" if errors else ""))

    # Offline reference mode: a second server whose AI connection is unreachable
    # (start it with: ANTHROPIC_BASE_URL=http://127.0.0.1:9 PORT=8001 python -m app.server)
    OFF = BASE.rsplit(":", 1)[0] + ":8001"
    try:
        pg.goto(OFF + "/")
        print("Offline reference mode (" + OFF + ")")
        pg.click(".lang button[data-l=en]")
        pg.wait_for_selector("#offline:not([hidden])", timeout=15_000)
        check(True, "offline banner shown when the AI cannot be reached")
        pg.fill("#q", "What is the front setback?")
        pg.click("#go")
        pg.wait_for_selector("#result .ans.nf")
        check("offline" in pg.inner_text("#result").lower(), "Ask explains offline mode instead of failing")
        pg.click("#tab-plot")
        pg.wait_for_function("!document.querySelector('#go-plot').disabled")
        pg.click("#go-plot")
        pg.wait_for_selector("#res-plot table.calc")
        check("Front open space" in pg.inner_text("#res-plot"), "Setback & FAR works offline")
        pg.click("#tab-rules")
        pg.fill("#rs", "lift")
        pg.click("#go-search")
        pg.wait_for_selector("#res-search .hit")
        check("Rule 83" in pg.inner_text("#res-search"), "rule search works offline")
        pg.wait_for_timeout(400)
        pg.screenshot(path=OUT / "screenshot-offline.png", full_page=True)
    except Exception as e:
        if "ERR_CONNECTION_REFUSED" in str(e):
            print("  (skipped offline checks: no server on " + OFF + ")")
        else:
            raise
    b.close()
print("UI smoke test passed; screenshots in docs/")
