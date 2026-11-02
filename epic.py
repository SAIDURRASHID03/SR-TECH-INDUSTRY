"""Epic Games free-games collector.

Source: https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions
(unofficial but stable endpoint; widely used.)

Contract: returns a list of deal dicts (see main.py CONTRACT).
Only items that are ACTUALLY free right now (discountPrice == 0) become
sub='games' (Weekly Free Games). Items with a real discount
(0 < discountPrice < originalPrice) become sub='discount'
(Weekly Discounts) with a 'sale' field (numbers-only sale price).
Everything else is skipped and logged. Epic items are status='live' —
the API data is structured and trustworthy, so they auto-publish.
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

        # v1.1: only discountPrice == 0 is truly FREE. Anything else with a
        # real discount is a sale (Weekly Discounts), never a free game.
        tp = e.get("price", {}).get("totalPrice", {}) or {}
        discount_cents = tp.get("discountPrice") or 0
        orig_cents = tp.get("originalPrice") or 0
        if discount_cents == 0:
            sub, sale = "games", ""
        elif orig_cents and 0 < discount_cents < orig_cents:
            sub = "discount"
            sale = f"{discount_cents / 100:.2f}"
            print(f"[epic] on sale (not free): {e.get('title')} -> ${sale}", file=sys.stderr)
        else:
            print(f"[epic] skip '{e.get('title')}': no free/sale price signal", file=sys.stderr)
            continue

        raw_price = tp.get("fmtPrice", {}).get("originalPrice", "")
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
                "sub": sub,
                "price": price,
                "sale": sale,  # numbers-only sale price; "" for free games
                "expiresAt": end_ms,
                "src": "epic",
                "srcId": str(e.get("id", "")),
                "status": "live",
                "ts": now_ms,
            }
        )
    return deals
