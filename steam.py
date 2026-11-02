"""Steam specials (discounts) collector -> the site's Weekly Discounts section.

Primary source: Steam's public search-results JSON API with the specials
filter (no key needed):
    https://store.steampowered.com/search/results/?...&specials=1
It returns up to 50 discounted games per page with prices baked into
data attributes (data-price-final in cents, data-discount in %).
We pull 2 pages (100 games); main.py's limits then keep the 50 biggest
discounts under the $30 price cap.

Fallback: the smaller featured-categories API (10 curated specials).

status='live' (official Steam data, auto-publishes). expiresAt = now + 7d
fallback — Steam gives no end date and specials refresh weekly.
A $0.00 final price (rare freebie) goes to Weekly Free Games instead.
Polite: 2-3 requests per run.
"""

import re
import sys
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}
SEARCH_URL = "https://store.steampowered.com/search/results/"
FEATURED_URL = "https://store.steampowered.com/api/featuredcategories/?cc=US&l=en"
PAGES = 5
PER_PAGE = 50


def _usd(cents):
    return f"{cents / 100:.2f}"


def _parse_search_page(html):
    """Parse one search-results page. Returns list of (appid, name, img, final_c, pct, reviews)."""
    out = []
    rows = re.findall(
        r'<a href="https://store\.steampowered\.com/app/(\d+)/[^"]*"[^>]*data-ds-appid="\d+"[^>]*>(.*?)</a>',
        html, re.S,
    )
    for appid, body in rows:
        try:
            m_name = re.search(r'<span class="title">(.*?)</span>', body, re.S)
            m_img = re.search(r'search_capsule"><img src="([^"]+)"', body)
            m_final = re.search(r'data-price-final="(\d+)"', body)
            m_pct = re.search(r'data-discount="(\d+)"', body)
            m_orig = re.search(r'discount_original_price">\$([\d.,]+)<', body)
            m_rev = re.search(r'([\d,]+) user reviews', body)
            if not (m_name and m_final and m_pct):
                continue
            name = re.sub(r"\s+", " ", m_name.group(1)).strip()
            final_c = int(m_final.group(1))
            pct = int(m_pct.group(1))
            reviews = int(m_rev.group(1).replace(",", "")) if m_rev else 0
            if m_orig:
                orig_c = int(round(float(m_orig.group(1).replace(",", "")) * 100))
            elif pct < 100:
                orig_c = int(round(final_c / (1 - pct / 100))) if pct else final_c
            else:
                orig_c = final_c
            img = m_img.group(1) if m_img else ""
            if name:
                out.append((appid, name, img, final_c, orig_c, pct, reviews))
        except Exception:
            continue
    return out


def _from_search():
    # Two pools: (1) top-selling discounted games = the popular titles,
    # (2) cheapest-first specials = volume. Combined, main.py keeps the
    # 50 biggest/most-popular discounts under the $30 cap.
    pools = [
        ({"specials": 1, "filter": "topsellers", "sort_by": "_ASC"}, 2),
        ({"specials": 1, "sort_by": "Price_ASC"}, 3),
    ]
    items, seen = [], set()
    for extra, pages in pools:
        for page in range(pages):
            params = {
                "query": "", "start": page * PER_PAGE, "count": PER_PAGE,
                "dynamic_data": "", "infinite": 1, "cc": "US", "l": "en",
                "category1": "998",  # games only — no DLCs/soundtracks/bundles
            }
            params.update(extra)
            r = requests.get(SEARCH_URL, params=params, headers=UA, timeout=25)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise ValueError("Steam search API success=false")
            for appid, name, img, final_c, orig_c, pct, reviews in _parse_search_page(data.get("results_html", "")):
                if appid in seen:
                    continue
                seen.add(appid)
                items.append((appid, name, img, final_c, orig_c, pct, reviews))
    if not items:
        raise ValueError("Steam search API returned no parseable items")
    return items


def _from_featured():
    r = requests.get(FEATURED_URL, headers=UA, timeout=20)
    r.raise_for_status()
    found = (r.json().get("specials") or {}).get("items") or []
    out = []
    for it in found:
        appid = it.get("id")
        name = (it.get("name") or "").strip()
        if not appid or not name:
            continue
        out.append((str(appid), name, it.get("header_image") or "",
                    it.get("final_price") or 0, it.get("original_price") or 0,
                    it.get("discount_percent") or 0, 0))
    return out


def _verify_free(appid):
    """Confirm a $0 candidate is genuinely a free GAME (not a paid DLC with
    broken price HTML). Returns True only if appdetails says so."""
    try:
        r = requests.get(
            "https://store.steampowered.com/api/appdetails/",
            params={"appids": appid, "cc": "US", "l": "en"},
            headers=UA, timeout=15)
        d = r.json().get(str(appid), {})
        if not d.get("success"):
            return False
        info = d["data"]
        if info.get("type") != "game":
            return False
        if info.get("is_free"):
            return True
        po = info.get("price_overview") or {}
        return po.get("final") == 0
    except Exception:
        return False


def fetch():
    """Return list of deal dicts. Never raises — returns [] on any failure."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        raw = _from_search()
        print(f"[steam] search API: {len(raw)} specials parsed", file=sys.stderr)
    except Exception as ex:
        print(f"[steam] search API failed ({ex}); trying featured API", file=sys.stderr)
        try:
            raw = _from_featured()
        except Exception as ex2:
            print(f"[steam] featured API also failed: {ex2}", file=sys.stderr)
            return []

    deals = []
    for appid, name, img, final_c, orig_c, pct, reviews in raw:
        try:
            free = final_c == 0
            if free and not _verify_free(appid):
                print(f"[steam] ${name[:40]}: $0 in search but not a free game — skipped",
                      file=sys.stderr)
                continue
            deals.append(
                {
                    "title": name,
                    "desc": "Free on Steam." if free else f"Save {pct}% on Steam — limited-time discount.",
                    "url": f"https://store.steampowered.com/app/{appid}/",
                    "img": img,
                    "images": [],
                    "sub": "games" if free else "discount",
                    "price": _usd(orig_c) if orig_c else "",
                    "sale": "" if free else _usd(final_c),
                    "reviews": reviews,
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
