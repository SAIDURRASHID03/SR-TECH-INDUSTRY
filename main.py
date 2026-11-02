"""SR Tech Industry deal-bot — entry point.

CONTRACT — every deal item is a dict with exactly these keys:
    title:str            human-readable title
    desc:str             short excerpt, max ~400 chars
    url:str              source claim page
    img:str              Cloudinary URL after upload (images[0])
    images:list          [img]
    sub:str              'games' (Epic / weekly free games) or 'daily' (software giveaways)
    price:str            NUMBERS ONLY, e.g. "24.99" (site v44 adds the $ at display)
    expiresAt:int        epoch ms
    src:str              'epic' | 'gotd' | 'winningpc'
    srcId:str            stable dedup key (Epic id / source URL)
    status:str           'live' (Epic auto-publish) | 'draft' (scraped, needs human approval)
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

import epic
import images
import scrapers
import store

SOURCES = ("epic", "gotd", "winningpc")


def collect(source, strict):
    """Run one source. Returns (items, error_or_None). Never raises unless strict."""
    try:
        if source == "epic":
            return epic.fetch(), None
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


def existing_src_ids(dry_run):
    """Set of srcIds already in Firebase. Skipped in dry-run (no credentials)."""
    if dry_run:
        print("[dedup] dry-run: skipping Firebase read (no dedup against live data)", file=sys.stderr)
        return set()
    data = store.read_existing(os.environ.get("FIREBASE_DB_URL", ""))
    ids = set()
    for v in (data or {}).values():
        if isinstance(v, dict) and v.get("srcId"):
            ids.add(str(v["srcId"]))
    return ids


def main():
    ap = argparse.ArgumentParser(description="SR Tech Industry deal-bot")
    ap.add_argument("--dry-run", action="store_true",
                    help="collect and print only; no Cloudinary uploads, no Firebase writes")
    ap.add_argument("--source", choices=("epic", "scraped", "all"), default="all",
                    help="'scraped' = gotd + winningpc")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any source fails (default: log and continue)")
    args = ap.parse_args()

    wanted = list(SOURCES) if args.source == "all" else (
        ["epic"] if args.source == "epic" else ["gotd", "winningpc"]
    )

    all_items, errors = [], {}
    for s in wanted:
        items, err = collect(s, args.strict)
        all_items.extend(items)
        if err:
            errors[s] = err
        print(f"[{s}] collected {len(items)} item(s)", file=sys.stderr)

    seen = existing_src_ids(args.dry_run)
    new_items = [i for i in all_items if str(i["srcId"]) not in seen]
    dupes = len(all_items) - len(new_items)

    if not args.dry_run:
        id_token = store.signin()  # raises with API message on failure
        db_url = os.environ["FIREBASE_DB_URL"]
    else:
        id_token = db_url = None

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

    if args.dry_run:
        print(json.dumps(new_items, indent=2, ensure_ascii=False))

    print("=" * 60, file=sys.stderr)
    print(f"SUMMARY  mode={'dry-run' if args.dry_run else 'LIVE'}", file=sys.stderr)
    print(f"  new epic items (auto-publish/live): {sum(1 for i in new_items if i['src'] == 'epic')}", file=sys.stderr)
    print(f"  new scraped drafts (need approval): {sum(1 for i in new_items if i['src'] != 'epic')}", file=sys.stderr)
    print(f"  skipped as duplicates: {dupes}", file=sys.stderr)
    for s, e in errors.items():
        print(f"  ERROR [{s}]: {e}", file=sys.stderr)
    if errors and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
