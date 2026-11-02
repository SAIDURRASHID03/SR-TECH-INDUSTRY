"""SR Tech Industry deal-bot — entry point.

CONTRACT — every deal item is a dict with exactly these keys:
    title:str            human-readable title
    desc:str             short excerpt, max ~400 chars
    url:str              source claim page
    img:str              Cloudinary URL after upload (images[0])
    images:list          [img]
    sub:str              'games' (Epic free games) | 'discount' (Epic on-sale + WinningPC coupons)
                         'daily' (software giveaways) | 'preset' (Fab free 3D assets)
    price:str            NUMBERS ONLY, e.g. "24.99" (site v44 adds the $ at display)
    sale:str             NUMBERS ONLY sale price, e.g. "3.99"; "" when not on sale
                         (site shows $3.99 struck $24.99 instead of "Free")
    expiresAt:int        epoch ms
    src:str              'epic' | 'fab' | 'gotd' | 'winningpc'
    srcId:str            stable dedup key (Epic id / Fab uid / source URL)
    status:str           'live' (Epic + Fab auto-publish) | 'draft' (scraped, needs human approval)
    ts:int               collection time, epoch ms

Usage:
    python main.py --dry-run                 # collect + print, no uploads, no Firebase writes
    python main.py --dry-run --source epic
    python main.py --source all              # real run (needs env: FIREBASE_API_KEY,
                                             # FIREBASE_DB_URL, BOT_EMAIL, BOT_PASSWORD)
    python main.py --strict                  # exit 1 if any source fails
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import epic
import fab
import f2p
import images
import scrapers
import steam
import store
import watchlist

SOURCES = ("epic", "fab", "f2p", "steam", "gotd", "winningpc")

# Section limits (his rules): Weekly Discounts holds at most 50 live games,
# Long-Term Free at most 30, and no discounted game may cost more than $30.
MAX_DISCOUNTS = 50
MAX_LONGTERM = 30
PRICE_CAP_USD = 30.0


def _fnum(v):
    try:
        return float(str(v).replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _discount_pct(it):
    p, s = _fnum(it.get("price")), _fnum(it.get("sale"))
    if p and p > 0 and s is not None and 0 <= s < p:
        return (p - s) / p
    return 0.0


def enforce_limits(items):
    """Apply his section rules to the NEW items about to be pushed.
    Discounts: drop anything over the $30 price cap, then keep the top 50 by
    (watchlist-pinned first, most player reviews, biggest discount %).
    Long-Term Free: keep at most 30. Returns the trimmed list."""
    discounts = [i for i in items if i.get("sub") == "discount"]
    longterm = [i for i in items if i.get("sub") == "longterm"]
    rest = [i for i in items if i.get("sub") not in ("discount", "longterm")]

    kept_d, dropped_price = [], 0
    for i in discounts:
        s = _fnum(i.get("sale"))
        if s is not None and s > PRICE_CAP_USD:
            dropped_price += 1
            print(f"[limits] price-cap drop: {i['title'][:50]} (${s:.2f})", file=sys.stderr)
        else:
            kept_d.append(i)
    kept_d.sort(key=lambda i: (i.get("pinned") or 0, i.get("reviews") or 0, _discount_pct(i)), reverse=True)
    if len(kept_d) > MAX_DISCOUNTS:
        print(f"[limits] discount cap: {len(kept_d)} -> {MAX_DISCOUNTS}", file=sys.stderr)
        kept_d = kept_d[:MAX_DISCOUNTS]
    if len(longterm) > MAX_LONGTERM:
        print(f"[limits] longterm cap: {len(longterm)} -> {MAX_LONGTERM}", file=sys.stderr)
        longterm = longterm[:MAX_LONGTERM]
    return rest + kept_d + longterm


def collect(source, strict):
    """Run one source. Returns (items, error_or_None). Never raises unless strict."""
    try:
        if source == "epic":
            return epic.fetch(), None
        if source == "fab":
            return fab.fetch(), None
        if source == "f2p":
            return f2p.fetch(), None
        if source == "steam":
            return steam.fetch(), None
        if source == "gotd":
            return scrapers.gotd(), None
        if source == "winningpc":
            return scrapers.winningpc(), None
    except Exception as ex:  # noqa: BLE001 - defensive by design
        msg = f"{source}: {ex}"
        print(f"[{source}] FAILED: {ex}", file=sys.stderr)
        if strict:
            raise RuntimeError(msg)
        return [], msg
    return [], f"unknown source: {source}"


def dedupe_existing(db_url, id_token):
    """Delete duplicate srcIds from Firebase, keeping the oldest entry.
    Runs at the start of every live run — self-heals duplicates left by
    overlapping runs. Manual items (no srcId) are never touched.
    Returns the number deleted."""
    data = store.read_existing(db_url, id_token)
    by_src = {}
    for key, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        sid = v.get("srcId")
        if not sid:
            continue
        by_src.setdefault(str(sid), []).append(key)
    deleted = 0
    for sid, keys in sorted(by_src.items()):
        if len(keys) > 1:
            keys.sort()  # Firebase push keys are time-ordered: keep oldest
            for k in keys[1:]:
                try:
                    store.delete(db_url, id_token, k)
                    deleted += 1
                except Exception as ex:
                    print(f"[dedupe] failed to delete {k}: {ex}", file=sys.stderr)
    if deleted:
        print(f"[dedupe] removed {deleted} duplicate item(s)", file=sys.stderr)
    return deleted


def trim_discounts(db_url, id_token, now_ms):
    """Keep the live Weekly Discounts section at MAX_DISCOUNTS items total.
    New items are capped per run, but different games arrive each run — so
    without this the section would grow without bound until items expire.
    Keeps the best-ranked (pinned, reviews, discount %) and deletes the rest.
    Manual items (no srcId) are never touched. Returns the number deleted."""
    data = store.read_existing(db_url, id_token)
    live = []
    for key, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        if v.get("sub") != "discount" or v.get("status") != "live":
            continue
        if not v.get("srcId"):  # manual item — never auto-delete
            continue
        exp = v.get("expiresAt")
        if exp and exp <= now_ms:
            continue
        live.append((key, v))
    if len(live) <= MAX_DISCOUNTS:
        return 0
    live.sort(key=lambda kv: (kv[1].get("pinned") or 0,
                              kv[1].get("reviews") or 0,
                              _discount_pct(kv[1])), reverse=True)
    doomed = live[MAX_DISCOUNTS:]
    deleted = 0
    for key, v in doomed:
        try:
            store.delete(db_url, id_token, key)
            deleted += 1
        except Exception as ex:
            print(f"[trim] failed to delete {key}: {ex}", file=sys.stderr)
    if deleted:
        print(f"[trim] Weekly Discounts: {len(live)} -> {MAX_DISCOUNTS} (removed {deleted})",
              file=sys.stderr)
    return deleted


def existing_src_ids(dry_run):
    """{srcId: (firebase_key, expiresAt)} already in Firebase.
    Skipped in dry-run (no credentials)."""
    if dry_run:
        print("[dedup] dry-run: skipping Firebase read (no dedup against live data)", file=sys.stderr)
        return {}
    data = store.read_existing(os.environ.get("FIREBASE_DB_URL", ""))
    ids = {}
    for key, v in (data or {}).items():
        if isinstance(v, dict) and v.get("srcId"):
            ids[str(v["srcId"])] = (key, v)
    return ids


def main():
    ap = argparse.ArgumentParser(description="SR Tech Industry deal-bot")
    ap.add_argument("--dry-run", action="store_true",
                    help="collect and print only; no Cloudinary uploads, no Firebase writes")
    ap.add_argument("--source", choices=("epic", "fab", "f2p", "steam", "scraped", "all"), default="all",
                    help="'scraped' = gotd + winningpc (drafts only)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any source fails (default: log and continue)")
    args = ap.parse_args()

    wanted = list(SOURCES) if args.source == "all" else (
        ["epic"] if args.source == "epic" else (
        ["fab"] if args.source == "fab" else (
        ["f2p"] if args.source == "f2p" else (
        ["steam"] if args.source == "steam" else ["gotd", "winningpc"])))
    )

    all_items, errors = [], {}
    for s in wanted:
        items, err = collect(s, args.strict)
        all_items.extend(items)
        if err:
            errors[s] = err
        print(f"[{s}] collected {len(items)} item(s)", file=sys.stderr)

    if not args.dry_run:
        id_token = store.signin()  # raises with API message on failure
        db_url = os.environ["FIREBASE_DB_URL"]
    else:
        id_token = db_url = None

    seen = existing_src_ids(args.dry_run)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # Volatile fields refreshed on every run so prices/ratings never go stale.
    # status/sub/img/images/desc/url are NEVER touched here (drafts stay drafts,
    # manual items have no srcId and are invisible to this loop).
    SYNC_FIELDS = ("price", "sale", "reviews", "pinned", "expiresAt", "title")
    new_items, refreshed, synced = [], 0, 0
    for i in all_items:
        sid = str(i["srcId"])
        if sid not in seen:
            new_items.append(i)
            continue
        # Self-correct: stored record expired but the deal is live again
        # (e.g. a wrong/old expiry) -> delete the stale record, push fresh.
        key, rec = seen[sid]
        exp = rec.get("expiresAt")
        new_exp = i.get("expiresAt")
        if exp and exp <= now_ms and (not new_exp or new_exp > now_ms):
            if not args.dry_run:
                try:
                    store.delete(os.environ["FIREBASE_DB_URL"], id_token, key)
                except Exception as ex:
                    print(f"[refresh] delete failed for {sid}: {ex}", file=sys.stderr)
                    continue
            refreshed += 1
            print(f"[refresh] {i['title'][:50]}: stale expired record replaced", file=sys.stderr)
            new_items.append(i)
        elif not args.dry_run:
            # Price-sync: the deal is already listed — refresh volatile fields
            # (price, sale, reviews, pinned...) so the site matches the store.
            patch = {f: i.get(f) for f in SYNC_FIELDS
                     if i.get(f) != rec.get(f)}
            if patch:
                patch["ts"] = now_ms
                try:
                    store.update(db_url, id_token, key, patch)
                    synced += 1
                except Exception as ex:
                    print(f"[sync] update failed for {sid}: {ex}", file=sys.stderr)
    dupes = len(all_items) - len(new_items) - refreshed
    print(f"[sync] {synced} existing item(s) refreshed with live data", file=sys.stderr)

    # Watchlist pinning + his section limits (caps, $30 price cap).
    new_items = watchlist.apply(new_items)
    new_items = enforce_limits(new_items)

    # Self-heal: remove duplicates left by any earlier overlapping runs.
    if not args.dry_run:
        dedupe_existing(db_url, id_token)

    pushed_live = pushed_draft = 0
    for it in new_items:
        if not args.dry_run:
            final_img = images.upload(it["img"])
            it["img"] = final_img
            it["images"] = [final_img] if final_img else []
            key = store.push(db_url, id_token, it)
            print(f"[push] {it['src']}/{it['status']}: {it['title'][:60]} -> {key}", file=sys.stderr)
        if it["status"] == "live":
            pushed_live += 1
        else:
            pushed_draft += 1

    if not args.dry_run:
        trim_discounts(db_url, id_token, int(datetime.now(timezone.utc).timestamp() * 1000))

    if args.dry_run:
        print(json.dumps(new_items, indent=2, ensure_ascii=False))

    print("=" * 60, file=sys.stderr)
    print(f"SUMMARY  mode={'dry-run' if args.dry_run else 'LIVE'}", file=sys.stderr)
    print(f"  new live items (auto-publish): {sum(1 for i in new_items if i['status'] == 'live')}", file=sys.stderr)
    print(f"    - epic free games: {sum(1 for i in new_items if i['src'] == 'epic' and i['sub'] == 'games')}", file=sys.stderr)
    print(f"    - epic on-sale games: {sum(1 for i in new_items if i['src'] == 'epic' and i['sub'] == 'discount')}", file=sys.stderr)
    print(f"    - fab free assets: {sum(1 for i in new_items if i['src'] == 'fab')}", file=sys.stderr)
    print(f"    - free-to-play games: {sum(1 for i in new_items if i['src'] == 'f2p')}", file=sys.stderr)
    print(f"    - steam discounts: {sum(1 for i in new_items if i['src'] == 'steam')}", file=sys.stderr)
    print(f"    - pinned watchlist games: {sum(1 for i in new_items if i.get('pinned'))}", file=sys.stderr)
    print(f"  new scraped drafts (need approval): {sum(1 for i in new_items if i['status'] == 'draft')}", file=sys.stderr)
    print(f"  skipped as duplicates: {dupes}", file=sys.stderr)
    for s, e in errors.items():
        print(f"  ERROR [{s}]: {e}", file=sys.stderr)
    if errors and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
