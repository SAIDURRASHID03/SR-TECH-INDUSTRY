"""Defensive HTML scrapers for Giveaway of the Day and WinningPC.

stdlib + requests only (no bs4). Strategy: read Open Graph meta tags
(og:title / og:description / og:image) — the most stable part of these pages —
plus a regex price hunt. If anything looks unfamiliar, return [] and log why.

NOTE (2026-11-03): per his direct order, GOTD/WinningPC now auto-publish
as live. The 24h freshness filter below is the quality gate instead.
by a human in the admin panel before going live. The bot must NEVER
auto-publish scraped items.
"""

import re
import sys
from datetime import datetime, timezone
import time
from html.parser import HTMLParser

import requests

UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}
TIMEOUT = 15


class _MetaParser(HTMLParser):
    """Collects og: meta tags, <title>, h1 text, and img srcs."""

    def __init__(self):
        super().__init__()
        self.meta = {}
        self.title_tag = ""
        self.h1s = []
        self.imgs = []
        self._in_title = False
        self._in_h1 = False
        self._h1_buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("property", "").startswith("og:"):
            self.meta[a["property"][3:]] = a.get("content", "")
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self._h1_buf = ""
        elif tag == "img" and a.get("src"):
            s = a["src"]
            if s.startswith("http") and not s.endswith(".svg"):
                self.imgs.append(s)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
            t = self._h1_buf.strip()
            if t:
                self.h1s.append(t)

    def handle_data(self, data):
        if self._in_title:
            self.title_tag += data
        if self._in_h1:
            self._h1_buf += data


def _parse_meta(html):
    p = _MetaParser()
    p.feed(html)
    return p


def _find_price(html):
    """First plausible $X.XX price in the page. Returns numbers-only string or ''."""
    for m in re.finditer(r"\$\s?([\d,]+\.\d{2})", html):
        val = m.group(1).replace(",", "")
        try:
            if 0.99 <= float(val) <= 500:
                return val
        except ValueError:
            pass
    return ""


def _get(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def _mk_item(title, desc, url, img, price, sub, src, ttl_hours, status="live"):
    now_ms = int(time.time() * 1000)
    desc = (desc or "").strip()
    if len(desc) > 400:
        desc = desc[:397].rstrip() + "..."
    return {
        "title": (title or "Untitled").strip(),
        "desc": desc,
        "url": url,
        "img": img or "",
        "images": [],  # filled after Cloudinary upload
        "sub": sub,
        "price": price or "",
        "expiresAt": now_ms + ttl_hours * 3600 * 1000,
        "src": src,
        "srcId": url,
        "status": status,
        "ts": now_ms,
    }


def gotd():
    """All 4 Giveaway of the Day sections, via RSS feeds.
    Returns list of items (one per section) posted within 36h."""
    feeds = [
        ("http://feeds.feedburner.com/giveawayoftheday/feed", "gotd", "daily"),
        ("https://game.giveawayoftheday.com/feed/", "gotd-game", "games"),
        ("https://android.giveawayoftheday.com/feed/", "gotd-android", "daily"),
        ("https://iphone.giveawayoftheday.com/feed/", "gotd-iphone", "daily"),
    ]
    items = []
    for feed_url, src_name, sub in feeds:
        try:
            xml = _get(feed_url)
        except Exception as ex:
            print(f"[gotd] {src_name} feed failed: {ex}", file=sys.stderr)
            continue
        try:
            # Get the latest item
            im = re.search(r"<item>(.*?)</item>", xml, re.S)
            if not im:
                continue
            item_xml = im.group(1)
            lm = re.search(r"<link>(.*?)</link>", item_xml, re.S)
            pm = re.search(r"<pubDate>(.*?)</pubDate>", item_xml)
            if not lm:
                continue
            post_url = re.sub(r"<[^>]+>", "", lm.group(1)).strip()
            # 36h freshness filter
            if pm:
                try:
                    from email.utils import parsedate_to_datetime
                    pub = parsedate_to_datetime(pm.group(1).strip())
                    age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
                    if age_h > 36:
                        print(f"[gotd] {src_name} skip: {age_h:.1f}h old", file=sys.stderr)
                        continue
                except Exception:
                    pass
            # Fetch post page for details
            html = _get(post_url)
            meta = _parse_meta(html)
            title = meta.meta.get("og:title", "") or meta.meta.get("title", "")
            title = re.sub(r"(?i)^giveaway of the day\s*[—–-]?\s*", "", title).strip()
            title = re.sub(r"\s*[—–-]\s*giveaway of the day.*$", "", title, flags=re.I).strip()
            # Section label from src_name
            section = {"gotd": "Windows", "gotd-game": "Game",
                       "gotd-android": "Android", "gotd-iphone": "iPhone"}.get(src_name, "")
            if not title or len(title) < 3 or title.lower() in ("android", "iphone", "game"):
                # Fallback: derive from URL slug
                slug = post_url.rstrip("/").split("/")[-1].replace("-", " ").title()
                title = slug
            if section and section.lower() not in title.lower():
                title = f"{title} ({section})"
            if not title or len(title) < 3:
                continue
            desc = meta.meta.get("description", "")
            img = meta.meta.get("image", "") or (meta.imgs[0] if meta.imgs else "")
            price = _find_price(html)
            items.append(_mk_item(title, desc, post_url, img, price, sub, src_name, 24))
            print(f"[gotd] {src_name}: {title[:45]}", file=sys.stderr)
        except Exception as ex:
            print(f"[gotd] {src_name} parse failed: {ex}", file=sys.stderr)
            continue
    return items

def _classify_wpc(url, title):
    """WinningPC posts: coupon/discount/deal posts -> 'discount' (Weekly Discounts);
    giveaway/free-license posts -> 'daily' (Daily Free Software)."""
    t = (url + " " + title).lower()
    if re.search(r"(coupon|discount|[^a-z]deal[^a-z]|promo|% ?off|sale)", t) \
       and not re.search(r"(giveaway|free-key|free-download)", t):
        return "discount"
    return "daily"


def _fresh_hours(txt):
    """Parse '1 hour ago', '4 days ago', '7 minutes ago' -> hours float. None if unknown."""
    t = (txt or "").lower().strip()
    m = re.match(r"(\d+)\s*(minute|hour|day|week)s?\s*ago", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n / 60 if unit == "minute" else n if unit == "hour" else n * 24 if unit == "day" else n * 168


def winningpc():
    """Scrape all 3 WinningPC giveaway sections. Returns list of fresh (<36h) items."""
    sections = [
        ("https://winningpc.com/giveaway/software-giveaway/", "daily"),
        ("https://winningpc.com/giveaway/android-ios-apps-giveaway/", "daily"),
        ("https://winningpc.com/giveaway/game-giveaway-for-pc-and-ios-android/", "games"),
    ]
    items = []
    for page_url, sub in sections:
        try:
            html = _get(page_url)
        except Exception as ex:
            print(f"[winningpc] section failed {page_url}: {ex}", file=sys.stderr)
            continue
        cards = re.findall(r"<article.*?</article>", html, re.S)
        for card in cards[:12]:  # latest 12 per section
            try:
                lm = re.search(r'<h3 class="pbox-name"><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', card, re.S)
                if not lm:
                    continue
                url = lm.group(1).strip()
                title = re.sub(r"<[^>]+>", "", lm.group(2)).strip()
                if not title or len(title) < 3:
                    continue
                # Freshness: pbox-fresh "X hours ago"
                fm = re.search(r'<span class="pbox-fresh">(.*?)</span>', card)
                age_h = _fresh_hours(fm.group(1)) if fm else None
                if age_h is not None and age_h > 36:
                    continue  # stale
                # Price
                was = re.search(r'<span class="pbox-was">([^<]+)</span>', card)
                price = (was.group(1).strip().lstrip("$") if was else "")
                # Image
                im = re.search(r'<img[^>]*src="([^"]+)"', card)
                img = im.group(1) if im else ""
                # Skip if already have this URL
                if any(i["url"] == url for i in items):
                    continue
                items.append(_mk_item(title, "", url, img, price, sub, "winningpc", 24))
                print(f"[winningpc] {title[:45]} ({fm.group(1) if fm else 'no date'})", file=sys.stderr)
            except Exception as ex:
                continue
        time.sleep(1)
    return items


def creativemarket():
    """Scrape Creative Market's 4 weekly free design assets.
    Returns list of items for the Presets section."""
    url = "https://creativemarket.com/free-goods"
    try:
        html = _get(url)
    except Exception as ex:
        print(f"[creativemarket] fetch failed: {ex}", file=sys.stderr)
        return []
    items = []
    # Find the "Free design asset downloads" section and extract products
    m = re.search(r"Free design asset downloads(.*?)(?:<h[12]|Unlock the full Drop)", html, re.S | re.I)
    section = m.group(1) if m else html
    # Product URLs: /username/123456-Product-Name
    seen_urls = set()
    for pm in re.finditer(r'href="(/[A-Za-z0-9._]+/\d+-[^"\s]+)"', section):
        purl = "https://creativemarket.com" + pm.group(1)
        if purl in seen_urls:
            continue
        seen_urls.add(purl)
        if len(items) >= 4:
            break
        try:
            # Extract title from URL slug
            slug = pm.group(1).split("/")[-1]
            # Remove leading ID: 123456-Product-Name -> Product-Name
            slug = re.sub(r"^\d+-", "", slug)
            title = slug.replace("-", " ").strip()
            if not title or len(title) < 3:
                continue
            # Try to get image from nearby img tag
            # Find the card containing this link
            card_start = max(0, pm.start() - 2000)
            card = html[card_start:pm.start() + 500]
            im = re.search(r'<img[^>]*src="([^"]+)"', card)
            img = im.group(1) if im else ""
            # Skip tiny icons, prefer product images
            if img and ("icon" in img.lower() or "avatar" in img.lower()):
                img = ""
            items.append(_mk_item(
                title=title,
                desc="Free design asset from Creative Market's weekly freebies — fonts, brushes, templates, graphics.",
                url=purl,
                img=img,
                price="",
                sub="preset",
                src="creativemarket",
                ttl_hours=7 * 24,  # Weekly refresh
            ))
            print(f"[creativemarket] {title[:45]}", file=sys.stderr)
        except Exception as ex:
            continue
    return items


