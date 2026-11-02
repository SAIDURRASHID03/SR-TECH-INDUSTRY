"""Priority watchlist: popular games that jump to the top of Weekly Discounts
the moment they go on sale.

Matching is by title keywords (normalized), so it works for both Epic and
Steam items. A match sets pinned=1 on the item; the site theme sorts pinned
items first inside the Weekly Discounts section.
"""

import re

# Each entry: (keywords, exact). exact=True means the normalized title must
# EQUAL a keyword (used when a game's name sits inside another game's name,
# e.g. "The Forest" inside "Sons Of The Forest").
WATCHLIST = [
    (("grand theft auto v", "grand theft auto 5", "gta v", "gta 5"), False),
    (("red dead redemption 2", "rdr2"), False),
    (("cyberpunk 2077",), False),
    (("watch dogs legion",), False),
    (("watch dogs 2",), False),
    (("tomb raider",), False),
    (("the forest",), True),
    (("fallout 4",), False),
    (("days gone",), False),
    (("green hell",), False),
    (("gold rush",), False),
]


def _norm(title):
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_watchlist(title):
    """True if the title matches any watchlist game."""
    t = _norm(title)
    for keywords, exact in WATCHLIST:
        if exact:
            if t in keywords:
                return True
        elif any(re.search(r"\b" + re.escape(kw) + r"\b", t) for kw in keywords):
            return True
    return False


def apply(items):
    """Set pinned=1 on discount items matching the watchlist. Returns items."""
    for it in items:
        it["pinned"] = 1 if (it.get("sub") == "discount" and is_watchlist(it.get("title"))) else 0
    return items
