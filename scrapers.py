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
    """Today's Giveaway of the Day, via their RSS feed (stable) + the post page
    for image/description/price. Returns [item] or []."""
    try:
        xml = _get("https://www.giveawayoftheday.com/feed/")
    except Exception as ex:
        print(f"[gotd] feed fetch failed: {ex}", file=sys.stderr)
        return []
    try:
        m = re.search(r"<item>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>", xml, re.S)
        if not m:
            print("[gotd] feed structure unrecognized: no items", file=sys.stderr)
            return []
        post_url = m.group(1).strip()
        # 24h freshness filter
        try:
            from email.utils import parsedate_to_datetime
            pub = parsedate_to_datetime(m.group(2).strip())
            age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
            if age_h > 24:
                print(f"[gotd] skip: post is {age_h:.1f}h old (>24h)", file=sys.stderr)
                return []
        except Exception as ex:
            print(f"[gotd] pubDate parse failed ({ex}), including anyway", file=sys.stderr)
        html = _get(post_url)
        p = _parse_meta(html)
        title = p.meta.get("title", "")
        title = re.sub(r"(?i)^giveaway of the day\s*[—–-]\s*", "", title).strip()
        if not title or len(title) < 3:
            print("[gotd] post structure unrecognized: no title", file=sys.stderr)
            return []
        desc = p.meta.get("description", "")
        img = p.meta.get("image", "") or (p.imgs[0] if p.imgs else "")
        price = _find_price(html)
        # GOTD giveaways run ~24h from post time; documented fallback.
        return [_mk_item(title, desc, post_url, img, price, "daily", "gotd", 24)]
    except Exception as ex:
        print(f"[gotd] parse failed: {ex}", file=sys.stderr)
        return []


def _classify_wpc(url, title):
    """WinningPC posts: coupon/discount/deal posts -> 'discount' (Weekly Discounts);
    giveaway/free-license posts -> 'daily' (Daily Free Software)."""
    t = (url + " " + title).lower()
    if re.search(r"(coupon|discount|[^a-z]deal[^a-z]|promo|% ?off|sale)", t) \
       and not re.search(r"(giveaway|free-key|free-download)", t):
        return "discount"
    return "daily"


def winningpc():
    """1-3 latest WinningPC posts: giveaways -> Daily Free Software, coupons/discounts -> Weekly Discounts. Returns list (may be [])."""
    try:
        html = _get("https://winningpc.com/")
    except Exception as ex:
        print(f"[winningpc] fetch failed: {ex}", file=sys.stderr)
        return []
    try:
        # Find post links that look like giveaways/coupons.
        links = []
        for m in re.finditer(r'href="(https://winningpc\.com/[^"]+?)"', html):
            u = m.group(1).rstrip("/")
            if "/giveaway/" in u:
                continue  # category archive page, not an individual post
            if re.search(r"(giveaway|coupon-code|free-key|free-download|deal)", u, re.I):
                if u not in links:
                    links.append(u)
            if len(links) >= 3:
                break
        if not links:
            print("[winningpc] page structure unrecognized: no giveaway links found", file=sys.stderr)
            return []
        items = []
        for u in links:
            try:
                ph = _get(u)
                p = _parse_meta(ph)
                if p.meta.get("type", "") != "article":
                    # Category/section page, not an individual giveaway post — skip.
                    print(f"[winningpc] skip {u}: not an article page", file=sys.stderr)
                    continue
                title = p.meta.get("title") or (p.h1s[0] if p.h1s else "")
                title = re.sub(r"(?i)\s*[-|]\s*winningpc.*$", "", title).strip()
                if not title or len(title) < 3:
                    print(f"[winningpc] skip {u}: no title", file=sys.stderr)
                    continue
                desc = p.meta.get("description", "")
                img = p.meta.get("image", "") or (p.imgs[0] if p.imgs else "")
                price = _find_price(ph)
                # 24h freshness filter (article:published_time meta)
                pub_raw = p.meta.get("article:published_time", "") or p.meta.get("publish_date", "")
                if pub_raw:
                    try:
                        pub = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                        age_h = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
                        if age_h > 24:
                            print(f"[winningpc] skip {u}: {age_h:.1f}h old (>24h)", file=sys.stderr)
                            continue
                    except Exception:
                        pass  # unparseable date -> include anyway
                # WinningPC giveaways usually run several days; documented fallback.
                sub = _classify_wpc(u, title)
                items.append(_mk_item(title, desc, u, img, price, sub, "winningpc", 72))
                time.sleep(1)  # be polite between requests
            except Exception as ex:
                print(f"[winningpc] skip {u}: {ex}", file=sys.stderr)
        return items
    except Exception as ex:
        print(f"[winningpc] parse failed: {ex}", file=sys.stderr)
        return []
