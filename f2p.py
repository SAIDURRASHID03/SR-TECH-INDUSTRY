"""Epic Games free-to-play collector -> the site's Long-Term Free section.

There is no public feed for Epic's permanently-free games, so this source
uses a curated list of 30 major F2P titles.

LESSON (2026-11-02): Epic's HTML storefront pages are bot-walled for
GitHub Actions runner IPs — the live page check returned zero items from
the runner while the JSON APIs (Epic promotions, Fab, Steam) worked fine.
So the list below is a VERIFIED SNAPSHOT (every page checked live:
HTTP 200 + og tags, 2026-11-02). The per-run page check is best-effort:
when it succeeds we use fresh data; when the bot wall blocks it we fall
back to the snapshot instead of publishing nothing.

Contract: returns a list of deal dicts (see main.py CONTRACT).
sub='longterm', status='live', price='' (shows "Free"), expiresAt=None
(the site treats missing expiry as live forever).
Dedup via srcId='f2p:<slug>' means each game is pushed once ever.
"""

import re
import sys
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "SRTechIndustryDealBot/1.0 (+https://srtechindustry03.blogspot.com)"}

# (display title, epic store slug, og:image) — all 30 verified live 2026-11-02.
GAMES = [
    ("Fortnite", "fortnite",
     "https://cdn1.epicgames.com/offer/fn/FNBR_43-00_MSEE_KeyArt_FN_Logo_EGS_Launcher_Blade_2560x1440_2560x1440-b575b2bd2d0d4892b520b4262617de93"),
    ("Rocket League", "rocket-league",
     "https://cdn1.epicgames.com/offer/9773aa1aa54f4f7b80e44bef04986cea/EGS_RocketLeague_PsyonixLLC_S1_2560x1440-636e2be15bbf463abd0c4d92fb7871a5"),
    ("Fall Guys", "fall-guys",
     "https://cdn1.epicgames.com/offer/50118b7f954e450f8823df1614b24e80/FGSS04_KeyArt_OfferImageLandscape_2560x1440_2560x1440-89c8edd4ffe307f5d760f286a28c3404"),
    ("Genshin Impact", "genshin-impact",
     "https://cdn1.epicgames.com/spt-assets/99dc46c68ea14324964a856d18dcac5b/genshin-impact-1hm6x.jpg"),
    ("Honkai: Star Rail", "honkai-star-rail",
     "https://cdn1.epicgames.com/spt-assets/6f3979ff608f42e286c83507a69b27f5/honkai-star-rail-x5aaz.jpg"),
    ("Warframe", "warframe",
     "https://cdn1.epicgames.com/spt-assets/9cd9aa0477474023a6cdf18823e481c6/warframe-m1ti9.jpg"),
    ("Path of Exile", "path-of-exile",
     "https://cdn1.epicgames.com/offer/7ad5508d382e46228056f1d1a0189ae2/EGS_PathofExile_GrindingGearGames_S1_2560x1440-2fa07951f481473aab64c9b2efc61d09"),
    ("Brawlhalla", "brawlhalla",
     "https://cdn2.unrealengine.com/atla-productart-1920x1080-1920x1080-477cda5a5a30.jpg"),
    ("SMITE", "smite",
     "https://cdn1.epicgames.com/offer/076207fa2b5c4803a636af606c3c28b7/SMITE-Hero-1920x1080_jan25_1920x1080-8298c71910dfb6659d18046770ac29a8"),
    ("Paladins", "paladins",
     "https://cdn1.epicgames.com/offer/badb0ee71b474ed591ec43212547cfc8/Paladins_EGS_BaseGame_2560x1440_2560x1440-99d0ed45c628c499ad600a52217b4123"),
    ("The Sims 4", "the-sims-4",
     "https://cdn1.epicgames.com/offer/2a14cf8a83b149919a2399504e5686a6/EGS_TheSims4_ElectronicArts_S1_2560x1440-330b00849edfdacc61578d1486f47b31"),
    ("Destiny 2", "destiny-2",
     "https://cdn1.epicgames.com/offer/428115def4ca4deea9d69c99c5a5a99e/EN_Bungie_D2_v950_OfferLandscape_S1_2560x1440_2560x1440-61cd46cb2d27e41f358293225ec354c8"),
    ("SMITE 2", "smite-2",
     "https://cdn1.epicgames.com/offer/16ed9f15b1b449ccb59cb610b13df5b8/SMITE2-LandscapeImage-F2P-2560x1440_2560x1440-fcfcbb2a6ea7088b16f5020c3eababfa"),
    ("Trackmania", "trackmania",
     "https://cdn1.epicgames.com/salesEvent/salesEvent/TM_StarterEd_Store_Landscape_2560x1440_2560x1440-0208bfc8d824b707130420b61249d4f5"),
    ("Apex Legends", "apex-legends-006cde",
     "https://cdn1.epicgames.com/spt-assets/5dcd88f4e2094a698ebffa43438edc33/apex-legends-nve1y.jpg"),
    ("Marvel Rivals", "marvel-rivals-182004",
     "https://cdn1.epicgames.com/spt-assets/eb15454c010f4a748498cd3a62096a52/marvel-rivals-1ywtf.png"),
    ("Delta Force", "delta-force-acea48",
     "https://cdn1.epicgames.com/spt-assets/5e13bf477ca8474e9bd01ae88d6710e7/delta-force-1scg7.png"),
    ("PUBG Battlegrounds", "pubg-59c1d9",
     "https://cdn1.epicgames.com/spt-assets/53ec4985296b4facbe3a8d8d019afba9/pubg-battlegrounds-19vwb.jpg"),
    ("Zenless Zone Zero", "zenless-zone-zero-c7c151",
     "https://cdn1.epicgames.com/spt-assets/dcd83ace86fb4501bde1316ca03e29ad/zenless-zone-zero-11vq2.jpg"),
    ("Once Human", "once-human-b5c576",
     "https://cdn1.epicgames.com/spt-assets/36c309a879c547efa4b8cdd76955a5f0/once-human-5f26s.jpg"),
    ("Infinity Nikki", "infinity-nikki-71fc64",
     "https://cdn1.epicgames.com/spt-assets/8d6db22e08f34ac29247bfbef5ba97a9/infinity-nikki-v6fal.jpg"),
    ("Arena Breakout: Infinite", "arena-breakout-infinite-cc318b",
     "https://cdn1.epicgames.com/spt-assets/051d38139880491e86b4ed665d3493de/arena-breakout-infinite-rlh2u.jpg"),
    ("Asphalt Legends Unite", "asphalt-legends-unite-4db4c6",
     "https://cdn1.epicgames.com/spt-assets/d8ab81c396c540228dbbfdfbff3369c6/asphalt-legends-8wyrj.jpg"),
    ("Fishing Planet", "fishing-planet-87df68",
     "https://cdn1.epicgames.com/spt-assets/69c4c77e43fb4773b3c13b376c231ddd/fishing-planet-10tcn.jpg"),
    ("NTE: Neverness to Everness", "nte-neverness-to-everness-965a32",
     "https://cdn1.epicgames.com/spt-assets/fb7cc56133de4df99b6a95d0a6b35d56/nte-neverness-to-everness-s4a4c.jpg"),
    ("Shadowverse: Worlds Beyond", "shadowverse-worlds-beyond-645ec6",
     "https://cdn1.epicgames.com/spt-assets/74c0be6a2f014655b72bd0dd66497742/shadowverse-worlds-beyond-fce9r.jpg"),
    ("Where Winds Meet", "where-winds-meet-58a176",
     "https://cdn1.epicgames.com/spt-assets/a55e4c8b015d445195aab2f028deace6/where-winds-meet-goctg.jpg"),
    ("Arknights: Endfield", "arknightsendfield-f0f167",
     "https://cdn1.epicgames.com/spt-assets/3dc91103cd1b492c8ce095fea4e07c5f/arknightsendfield-10ptc.png"),
    ("Rainbow Six Siege X", "rainbow-six-siege-x",
     "https://cdn1.epicgames.com/offer/carnation/EGST_Edition_Thumbnail_1920X1080_1920x1080-a9c8b561b4fd4dd7858b9127e1c6782e"),
    ("Magic: The Gathering Arena", "mtg-arena",
     "https://cdn1.epicgames.com/offer/5fdcc0dc67294af3be740f362bd976fd/EGS_MagicTheGatheringArena_WizardsoftheCoast_S1_2560x1440-2fb49c12716244c3af412a0ef778dbde"),
]


def _og(html, prop):
    m = re.search(r'<meta[^>]*property="%s"[^>]*>' % re.escape(prop), html)
    if not m:
        return ""
    c = re.search(r'content="([^"]*)"', m.group(0))
    return c.group(1) if c else ""


def _live_check(slug):
    """Best-effort: (ok, fresh_image). Never raises."""
    try:
        r = requests.get(f"https://store.epicgames.com/en-US/p/{slug}",
                         headers=UA, timeout=25, allow_redirects=True)
        if r.status_code == 200 and _og(r.text, "og:title"):
            return True, _og(r.text, "og:image")
        return False, ""
    except Exception:
        return False, ""


def fetch():
    """Return list of deal dicts. Always returns the 14 verified games;
    the live page check only refreshes the image when reachable."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    deals = []
    for title, slug, snap_img in GAMES:
        url = f"https://store.epicgames.com/en-US/p/{slug}"
        ok, fresh_img = _live_check(slug)
        if not ok:
            print(f"[f2p] {title}: live check blocked, using verified snapshot", file=sys.stderr)
        deals.append(
            {
                "title": title,
                "desc": "Permanently free-to-play on the Epic Games Store.",
                "url": url,
                "img": fresh_img or snap_img,
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
    return deals
