"""Epic Games free-games collector.

Source: https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions
(unofficial but stable endpoint; widely used.)

Contract: returns a list of deal dicts (see main.py CONTRACT).
Epic items are status='live' — the API data is structured and trustworthy,
so they auto-publish. sub='games' (Weekly Free Games on the site).
"""

import sys
from datetime import datetime, timezone

import requests

EPIC_URL = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    "?locale=en-US&country=US"
)

UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}


def _ms(iso):
    """'2026-11-05T22:00:00.000Z' -> epoch ms."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _pick_image(element):
    imgs = element.get("keyImages") or []
    pref = ("OfferImageWide", "DieselStoreFrontWide", "DieselGameBoxWide", "Thumbnail")
    by_type = {i.get("type"): i.get("url") for i in imgs if i.get("url")}
    for t in pref:
        if by_type.get(t):
            return by_type[t]
    return imgs[0]["url"] if imgs else ""


def _page_slug(element):
    for src in ("catalogNs",):
        ns = element.get(src) or {}
        for m in ns.get("mappings") or []:
            if m.get("pageSlug"):
                return m["pageSlug"]
    for m in element.get("offerMappings") or []:
        if m.get("pageSlug"):
            return m["pageSlug"]
    return ""


def fetch():
    """Return list of deal dicts. Never raises for HTTP-level success; raises on network failure."""
    deals = []
    r = requests.get(EPIC_URL, headers=UA, timeout=20)
    r.raise_for_status()
    data = r.json()
    elements = (
        data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
    )
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    for e in elements:
        promos = (e.get("promotions") or {}).get("promotionalOffers") or []
        if not promos or not promos[0].get("promotionalOffers"):
            continue
        offer = promos[0]["promotionalOffers"][0]
        try:
            start_ms = _ms(offer["startDate"])
            end_ms = _ms(offer["endDate"])
        except (KeyError, ValueError, TypeError):
            print(f"[epic] skip '{e.get('title')}': bad dates", file=sys.stderr)
            continue
        if start_ms > now_ms:
            # Upcoming freebie, not claimable yet — log and skip.
            print(f"[epic] upcoming (skipped): {e.get('title')} from {offer['startDate']}", file=sys.stderr)
            continue

        raw_price = (
            e.get("price", {}).get("totalPrice", {}).get("fmtPrice", {}).get("originalPrice", "")
        )
        price = str(raw_price).replace("$", "").replace(",", "").strip()

        slug = _page_slug(e)
        url = (
            f"https://store.epicgames.com/en-US/p/{slug}"
            if slug
            else "https://store.epicgames.com/en-US/free-games"
        )
        desc = (e.get("description") or "").strip()
        if len(desc) > 400:
            desc = desc[:397].rstrip() + "..."

        deals.append(
            {
                "title": (e.get("title") or "Untitled").strip(),
                "desc": desc,
                "url": url,
                "img": _pick_image(e),
                "images": [],  # filled after Cloudinary upload
                "sub": "games",
                "price": price,
                "expiresAt": end_ms,
                "src": "epic",
                "srcId": str(e.get("id", "")),
                "status": "live",
                "ts": now_ms,
            }
        )
    return deals
