"""Epic Games free-to-play collector (Long-Term Free section).

There is no public feed for Epic's permanently-free games, so this source
uses a curated list of major F2P titles and VERIFIES each game's real
store page on every run (HTTP 200 + og:title present). A game whose page
disappears is skipped and logged — never published blind.

Contract: returns a list of deal dicts (see main.py CONTRACT).
sub='longterm', status='live', price='' (shows "Free" with no struck price),
expiresAt=None (the site treats missing expiry as live forever).
Dedup via srcId='f2p:<slug>' means each game is pushed once ever.
"""

import re
import sys
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}

# (display title, epic store slug) — every slug verified 200 + og tags 2026-11-02.
GAMES = [
    ("Fortnite", "fortnite"),
    ("Rocket League", "rocket-league"),
    ("Fall Guys", "fall-guys"),
    ("Genshin Impact", "genshin-impact"),
    ("Honkai: Star Rail", "honkai-star-rail"),
    ("Warframe", "warframe"),
    ("Path of Exile", "path-of-exile"),
    ("Brawlhalla", "brawlhalla"),
    ("SMITE", "smite"),
    ("Paladins", "paladins"),
]


def _og(html, prop):
    m = re.search(
        r'<meta[^>]*property="%s"[^>]*>' % re.escape(prop), html
    )
    if not m:
        return ""
    c = re.search(r'content="([^"]*)"', m.group(0))
    return c.group(1) if c else ""


def fetch():
    """Return list of deal dicts. Never raises — returns [] on failure."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    deals = []
    for title, slug in GAMES:
        url = f"https://store.epicgames.com/en-US/p/{slug}"
        try:
            r = requests.get(url, headers=UA, timeout=40, allow_redirects=True)
            if r.status_code != 200:
                print(f"[f2p] skip {title}: HTTP {r.status_code}", file=sys.stderr)
                continue
            og_title = _og(r.text, "og:title")
            og_image = _og(r.text, "og:image")
            if not og_title:
                print(f"[f2p] skip {title}: no og:title (page changed?)", file=sys.stderr)
                continue
            deals.append(
                {
                    "title": title,
                    "desc": "Permanently free-to-play on the Epic Games Store.",
                    "url": url,
                    "img": og_image,
                    "images": [],
                    "sub": "longterm",
                    "price": "",
                    "sale": "",
                    "expiresAt": None,
                    "src": "f2p",
                    "srcId": f"f2p:{slug}",
                    "status": "live",
                    "ts": now_ms,
                }
            )
        except Exception as ex:
            print(f"[f2p] skip {title}: {ex}", file=sys.stderr)
    return deals
