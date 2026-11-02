"""Steam specials (discounts) collector -> the site's Weekly Discounts section.

Source: https://store.steampowered.com/api/featuredcategories/?cc=US&l=en
(Steam's public JSON API, no key needed). The 'specials' section lists
currently-discounted games with final/original prices and discount %.
Polite: one request per run.

Contract: returns a list of deal dicts (see main.py CONTRACT).
status='live' (official Steam data, auto-publishes). expiresAt = now + 7d
fallback — the API gives no end date and Steam's specials refresh weekly.
If final_price is 0 (rare freebie), the item goes to Weekly Free Games.
"""

import sys
from datetime import datetime, timezone

import requests

STEAM_URL = "https://store.steampowered.com/api/featuredcategories/?cc=US&l=en"
UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}


def _usd(cents):
    return f"{cents / 100:.2f}"


def fetch():
    """Return list of deal dicts. Never raises — returns [] on any failure."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        r = requests.get(STEAM_URL, headers=UA, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as ex:
        print(f"[steam] fetch failed: {ex}", file=sys.stderr)
        return []

    try:
        items = (data.get("specials") or {}).get("items") or []
        deals = []
        for it in items:
            try:
                appid = it.get("id")
                name = (it.get("name") or "").strip()
                if not appid or not name:
                    continue
                final_c = it.get("final_price") or 0
                orig_c = it.get("original_price") or 0
                dp = it.get("discount_percent") or 0
                free = final_c == 0
                deals.append(
                    {
                        "title": name,
                        "desc": (
                            "Free on Steam."
                            if free
                            else f"Save {dp}% on Steam — limited-time discount."
                        ),
                        "url": f"https://store.steampowered.com/app/{appid}/",
                        "img": it.get("header_image") or "",
                        "images": [],
                        "sub": "games" if free else "discount",
                        "price": _usd(orig_c) if orig_c else "",
                        "sale": "" if free else _usd(final_c),
                        "expiresAt": now_ms + 7 * 24 * 3600 * 1000,
                        "src": "steam",
                        "srcId": f"steam:{appid}",
                        "status": "live",
                        "ts": now_ms,
                    }
                )
            except Exception as ex:
                print(f"[steam] skip item: {ex}", file=sys.stderr)
        return deals
    except Exception as ex:
        print(f"[steam] parse failed: {ex}", file=sys.stderr)
        return []
