#!/usr/bin/env python3
"""Earthboat multi-location availability checker.

    python check_availability.py --checkin 2026-08-09 --checkout 2026-08-10 --guests 2

See README.md before the first real run: this script's selectors and API
template are unverified against the live site (see README for why) and
should be checked with `--mode inspect` first.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_URL = "https://en.earthboat.jp"

PRICE_RE = re.compile(r"¥\s?[\d,]+|[\d,]+\s?円")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    p = argparse.ArgumentParser(description="Check Earthboat location availability")
    p.add_argument("--checkin", default="2026-08-09", help="Check-in date, YYYY-MM-DD")
    p.add_argument("--checkout", default="2026-08-10", help="Check-out date, YYYY-MM-DD")
    p.add_argument("--guests", type=int, default=2)
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument(
        "--locations",
        nargs="*",
        default=None,
        help="Subset of slugs to check (default: all, in priority order from locations.json)",
    )
    p.add_argument(
        "--mode",
        choices=["browser", "inspect", "api"],
        default="browser",
        help=(
            "browser: drive the real page and read the result off the DOM. "
            "inspect: load each page once and dump network calls + candidate "
            "form elements so you can fill in selectors.json / api_endpoints.json. "
            "api: call the endpoints configured in api_endpoints.json directly."
        ),
    )
    p.add_argument("--headed", dest="headless", action="store_false", default=True)
    p.add_argument("--out", default=str(ROOT / "results" / "availability.md"))
    p.add_argument("--json-out", default=str(ROOT / "results" / "availability.json"))
    p.add_argument("--screenshots-dir", default=str(ROOT / "results" / "screenshots"))
    p.add_argument("--inspect-dir", default=str(ROOT / "results" / "inspect"))
    p.add_argument(
        "--executable-path",
        default=None,
        help="Path to a chromium binary, for sandboxes with a pre-installed browser "
        "outside Playwright's normal cache dir (e.g. /opt/pw-browsers/chromium-*/chrome-linux/chrome)",
    )
    p.add_argument("--timeout", type=int, default=20000, help="Per-action timeout in ms")
    p.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between locations (politeness delay, keep this a single polite pass)",
    )
    return p.parse_args()


def load_locations(args):
    all_locations = load_json(ROOT / "locations.json")
    if args.locations:
        wanted = set(args.locations)
        return [loc for loc in all_locations if loc["slug"] in wanted]
    return all_locations


def try_first(page, selector_list, timeout=3000):
    """Return the first Locator among selector_list that matches >=1 element."""
    for sel in selector_list:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


def any_keyword(text_lower, keywords):
    return any(k.lower() in text_lower for k in keywords)


# ---------------------------------------------------------------------------
# --mode browser
# ---------------------------------------------------------------------------

def check_location_browser(browser, loc, args, selectors):
    slug, name = loc["slug"], loc["name_en"]
    url = f"{args.base_url.rstrip('/')}/{slug}"
    result = {
        "slug": slug,
        "name": name,
        "url": url,
        "available": None,
        "price": None,
        "waitlist": None,
        "note": "",
        "screenshot": None,
    }

    page = browser.new_page()
    try:
        page.goto(url, timeout=args.timeout, wait_until="networkidle")
    except PWTimeout:
        result["note"] = "page load timed out"
        page.close()
        return result
    except Exception as e:
        result["note"] = f"navigation error: {e}"
        page.close()
        return result

    try:
        checkin_el = try_first(page, selectors["checkin_input"])
        checkout_el = try_first(page, selectors["checkout_input"])
        guests_el = try_first(page, selectors["guests_input"])

        if checkin_el:
            checkin_el.fill(args.checkin)
        if checkout_el:
            checkout_el.fill(args.checkout)
        if guests_el:
            try:
                guests_el.select_option(str(args.guests))
            except Exception:
                try:
                    guests_el.fill(str(args.guests))
                except Exception:
                    pass

        search_btn = try_first(page, selectors["search_button"])
        if search_btn:
            search_btn.click()
            page.wait_for_load_state("networkidle", timeout=args.timeout)
        elif not checkin_el and not checkout_el:
            result["note"] = (
                "date inputs not found; selectors.json needs updating "
                "(run --mode inspect once with real network access)"
            )
    except Exception as e:
        result["note"] = (result["note"] + f"; form interaction error: {e}").strip("; ")

    # Screenshot for manual verification regardless of what we parsed.
    shot_path = Path(args.screenshots_dir) / f"{slug}.png"
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(shot_path), full_page=True)
        result["screenshot"] = str(shot_path)
    except Exception:
        pass

    body_text = ""
    try:
        body_text = page.inner_text("body")
    except Exception:
        pass
    body_lower = body_text.lower()

    # Signal 1: explicit book/reserve buttons and whether they're disabled.
    book_btn = try_first(page, selectors["book_button"])
    if book_btn:
        try:
            result["available"] = book_btn.is_enabled()
        except Exception:
            pass

    # Signal 2: sold-out / available keyword scan (overrides an unclear button signal).
    if any_keyword(body_lower, selectors.get("sold_out_keywords", [])):
        result["available"] = False
    elif result["available"] is None and any_keyword(
        body_lower, selectors.get("available_keywords", [])
    ):
        result["available"] = True

    if any_keyword(body_lower, selectors.get("waitlist_keywords", [])):
        result["waitlist"] = True

    price_match = PRICE_RE.search(body_text)
    if price_match:
        result["price"] = price_match.group(0).strip()

    if result["available"] is None and not result["note"]:
        result["note"] = "could not determine availability from page content; check screenshot manually"

    page.close()
    return result


# ---------------------------------------------------------------------------
# --mode inspect
# ---------------------------------------------------------------------------

CANDIDATE_FORM_SELECTORS = [
    "input[type='date']",
    "[class*='calendar' i]",
    "[class*='datepicker' i]",
    "[name*='date' i]",
    "[name*='checkin' i]",
    "[name*='checkout' i]",
    "[class*='guest' i]",
    "[name*='guest' i]",
    "form",
]


def inspect_location(browser, loc, args):
    slug, name = loc["slug"], loc["name_en"]
    url = f"{args.base_url.rstrip('/')}/{slug}"
    network_log = []

    page = browser.new_page()

    def on_response(resp):
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype or resp.request.resource_type in ("xhr", "fetch"):
            entry = {
                "url": resp.url,
                "status": resp.status,
                "content_type": ctype,
                "method": resp.request.method,
            }
            try:
                if "json" in ctype:
                    entry["body_preview"] = json.dumps(resp.json())[:2000]
            except Exception:
                pass
            network_log.append(entry)

    page.on("response", on_response)

    try:
        page.goto(url, timeout=args.timeout, wait_until="networkidle")
    except Exception as e:
        page.close()
        return {"slug": slug, "name": name, "url": url, "error": str(e), "network_log": network_log}

    candidates = []
    for sel in CANDIDATE_FORM_SELECTORS:
        try:
            elements = page.locator(sel)
            n = min(elements.count(), 5)
            for i in range(n):
                try:
                    candidates.append(
                        {"selector": sel, "outer_html": elements.nth(i).evaluate("el => el.outerHTML")[:500]}
                    )
                except Exception:
                    continue
        except Exception:
            continue

    inspect_dir = Path(args.inspect_dir)
    inspect_dir.mkdir(parents=True, exist_ok=True)

    try:
        html = page.content()
        (inspect_dir / f"{slug}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    (inspect_dir / f"{slug}_network.json").write_text(
        json.dumps(network_log, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (inspect_dir / f"{slug}_candidates.json").write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    shot_path = Path(args.screenshots_dir) / f"{slug}_inspect.png"
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(shot_path), full_page=True)
    except Exception:
        pass

    page.close()
    return {
        "slug": slug,
        "name": name,
        "url": url,
        "network_calls_captured": len(network_log),
        "form_candidates_captured": len(candidates),
        "dump_dir": str(inspect_dir),
    }


# ---------------------------------------------------------------------------
# --mode api
# ---------------------------------------------------------------------------

def check_location_api(loc, args, api_config):
    import requests  # imported lazily; not needed for browser/inspect modes

    slug, name = loc["slug"], loc["name_en"]
    result = {"slug": slug, "name": name, "available": None, "price": None, "note": ""}

    endpoint = api_config.get(slug)
    if not endpoint:
        result["note"] = "no endpoint configured in api_endpoints.json; run --mode inspect first"
        return result

    def fmt(v):
        return str(v).format(slug=slug, checkin=args.checkin, checkout=args.checkout, guests=args.guests)

    url = fmt(endpoint["url"])
    params = {k: fmt(v) for k, v in endpoint.get("query_params", {}).items()}
    method = endpoint.get("method", "GET").upper()

    try:
        resp = requests.request(method, url, params=params if method == "GET" else None,
                                 json=params if method != "GET" else None, timeout=args.timeout / 1000)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        result["note"] = f"API call failed: {e}"
        return result

    def dig(obj, path):
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    if endpoint.get("available_path"):
        result["available"] = bool(dig(data, endpoint["available_path"]))
    if endpoint.get("price_path"):
        result["price"] = dig(data, endpoint["price_path"])

    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def render_markdown(results, args):
    lines = [
        f"# Earthboat availability — {args.checkin} → {args.checkout} ({args.guests} guests)",
        "",
        "| 拠点 | 空室 | 料金（2名） | 備考 |",
        "|---|---|---|---|",
    ]
    for r in results:
        if r.get("available") is True:
            avail = "○"
        elif r.get("available") is False:
            avail = "×"
        else:
            avail = "?"
        price = r.get("price") or ""
        note_parts = []
        if r.get("waitlist"):
            note_parts.append("キャンセル待ちあり")
        if r.get("note"):
            note_parts.append(r["note"])
        note = " / ".join(note_parts)
        lines.append(f"| {r['name']} | {avail} | {price} | {note} |")
    lines.append("")
    lines.append(
        "`?` = could not be determined automatically from this run — check the matching "
        "screenshot in `results/screenshots/` before relying on it."
    )
    return "\n".join(lines)


def main():
    args = parse_args()
    locations = load_locations(args)
    if not locations:
        print("No matching locations found in locations.json", file=sys.stderr)
        sys.exit(1)

    results = []

    if args.mode == "api":
        api_config = load_json(ROOT / "api_endpoints.json")
        for i, loc in enumerate(locations):
            print(f"[{i+1}/{len(locations)}] {loc['name_en']} (api)...")
            results.append(check_location_api(loc, args, api_config))
            if i < len(locations) - 1:
                time.sleep(args.delay)
    else:
        selectors = load_json(ROOT / "selectors.json") if args.mode == "browser" else None
        launch_kwargs = {"headless": args.headless}
        if args.executable_path:
            launch_kwargs["executable_path"] = args.executable_path

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            try:
                for i, loc in enumerate(locations):
                    print(f"[{i+1}/{len(locations)}] {loc['name_en']} ({args.mode})...")
                    if args.mode == "inspect":
                        results.append(inspect_location(browser, loc, args))
                    else:
                        results.append(check_location_browser(browser, loc, args, selectors))
                    if i < len(locations) - 1:
                        time.sleep(args.delay)
            finally:
                browser.close()

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRaw results written to {args.json_out}")

    if args.mode != "inspect":
        markdown = render_markdown(results, args)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"Markdown summary written to {args.out}\n")
        print(markdown)
    else:
        print(f"\nInspect dumps written under {args.inspect_dir}/ — read the *_network.json files")
        print("for the real availability API, and *_candidates.json for date/guest form elements.")
        print("Update selectors.json / api_endpoints.json accordingly, then re-run with --mode browser or --mode api.")


if __name__ == "__main__":
    main()
