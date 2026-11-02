"""Fab (Epic's 3D marketplace) limited-time free assets collector.

Source: https://www.fab.com/i/blades/free_content_blade (Fab's own internal
JSON API, used by fab.com itself — stable enough, and fully defensive:
any failure returns [].)

Contract: returns a list of deal dicts (see main.py CONTRACT).
Fab items are status='live' — the data comes from Epic's own marketplace,
so they auto-publish. sub='preset' (the site's Presets section).

The free-until date is parsed from the block title, e.g.
"Limited-Time Free (Until November 3 at 9:59 AM ET)". ET is treated as
UTC-5 (EST; correct Oct-Mar). If the date can't be parsed, expiresAt
falls back to now + 48h and the item is still published (logged).
"""

import re
import sys
from datetime import datetime, timezone, timedelta

import requests

FAB_URL = "https://www.fab.com/i/blades/free_content_blade"
UA = {
    "User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)",
    "Accept": "application/json",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_until(title, now):
    """'Limited-Time Free (Until November 3 at 9:59 AM ET)' -> epoch ms (ET=UTC-5)."""
    m = re.search(
        r"until\s+([A-Za-z]+)\s+(\d{1,2})\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET",
        title or "",
        re.I,
    )
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    day = int(m.group(2))
    hh, mm, ap = int(m.group(3)), int(m.group(4)), m.group(5).upper()
    if ap == "PM" and hh != 12:
        hh += 12
    if ap == "AM" and hh == 12:
        hh = 0
    year = now.year
    dt = datetime(year, mon, day, hh, mm, tzinfo=timezone(timedelta(hours=-5)))
    if dt <= now:
        dt = datetime(year + 1, mon, day, hh, mm, tzinfo=timezone(timedelta(hours=-5)))
    return int(dt.timestamp() * 1000)


def _best_thumb(listing):
    best, best_w = "", 0
    for th in listing.get("thumbnails") or []:
        for im in th.get("images") or []:
            w = im.get("width") or 0
            if im.get("url") and w >= best_w:
                best, best_w = im["url"], w
    return best


def _price(listing):
    for lic in listing.get("licenses") or []:
        if (lic.get("name") or "").lower() == "personal":
            p = (lic.get("priceTier") or {}).get("price")
            if p:
                return f"{float(p):.2f}".rstrip("0").rstrip(".")
    return ""


def fetch():
    """Return list of deal dicts. Never raises — returns [] on any failure."""
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    try:
        r = requests.get(FAB_URL, headers=UA, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as ex:
        print(f"[fab] fetch failed: {ex}", file=sys.stderr)
        return []

    try:
        until_ms = _parse_until(data.get("title", ""), now)
        if not until_ms:
            print("[fab] could not parse free-until date; using +48h fallback", file=sys.stderr)
            until_ms = now_ms + 48 * 3600 * 1000

        deals = []
        for t in data.get("tiles") or []:
            try:
                l = t.get("listing") or {}
                title = (l.get("title") or "").strip()
                uid = l.get("uid") or ""
                if not title or not uid:
                    continue
                deals.append(
                    {
                        "title": title,
                        "desc": "Limited-time free 3D asset on Fab (Epic's marketplace) — claim it before the timer runs out.",
                        "url": f"https://www.fab.com/listings/{uid}",
                        "img": _best_thumb(l),
                        "images": [],
                        "sub": "preset",
                        "price": _price(l),
                        "sale": "",
                        "expiresAt": until_ms,
                        "src": "fab",
                        "srcId": uid,
                        "status": "live",
                        "ts": now_ms,
                    }
                )
            except Exception as ex:
                print(f"[fab] skip tile: {ex}", file=sys.stderr)
        return deals
    except Exception as ex:
        print(f"[fab] parse failed: {ex}", file=sys.stderr)
        return []
