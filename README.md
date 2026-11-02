# 🤖 SR Tech Industry — Deal Bot

Automatically collects free software & game deals and publishes them to your
website's Daily Deals section. Runs by itself 4 times a day (every 6 hours) — no computer needed.

## What it collects

| Source | What | How it publishes |
|---|---|---|
| **Epic Games** | Weekly free games (title, image, original price, exact end date) → your **Weekly Free Games** section. **Only truly free games** (the bot verifies the price is $0 — discounted-but-not-free games never sneak in) | ✅ Goes live automatically — the data comes from Epic's own feed, so it's trustworthy |
| **Epic Games** | Games currently on sale (sale price + original price, exact end date) → your **Weekly Discounts** section | ✅ Goes live automatically |
| **Fab** (Epic's 3D marketplace) | Limited-time free 3D assets → your **Presets** section | ✅ Goes live automatically |
| **Free-to-play** | 14 verified permanently-free Epic games (Fortnite, Rocket League, …) → your **Long-Term Free** section. The bot re-checks each game's real store page every run | ✅ Goes live automatically |
| **Steam** | This week's discounted games (sale price + original price) → your **Weekly Discounts** section, next to the Epic deals | ✅ Goes live automatically |
| **Giveaway of the Day** | Today's free software → your **Daily Free Software** section | 📝 Saved as a **draft** — you approve it with one tap in your admin panel |
| **WinningPC** | Latest giveaway posts → **Daily Free Software**; coupon/discount posts → your **Weekly Discounts** section | 📝 Saved as a **draft** — you approve it with one tap in your admin panel |

Scraped items are **never** auto-published. Only Epic (structured, reliable data)
goes live on its own.

## Setup (one time, ~15 minutes)

### 1. Create a GitHub account + repository
1. Go to https://github.com and sign up (free).
2. Create a **new private repository** (e.g. `sr-deal-bot`).
3. Upload all the files from this `deal-bot` folder into it
   (drag-and-drop on the GitHub website works fine — keep the folder structure).

### 2. Create a bot user in Firebase
1. Open https://console.firebase.google.com → your project **sr-tech-industry**.
2. Go to **Build → Authentication → Users → Add user**.
3. Email: something like `deals-bot@srtechindustry.com`, set a **strong password**.
4. Save that email + password — you'll need them in the next step.
   (Your database rules already let any signed-in user write the deals section,
   so no rule changes are needed.)

### 3. Add the 4 secrets to GitHub
1. In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
2. Add these four (values never shown to anyone):
   - `FIREBASE_API_KEY` — your Firebase Web API key (it's inside your theme file's firebase config)
   - `FIREBASE_DB_URL` — `https://sr-tech-industry-default-rtdb.firebaseio.com`
   - `BOT_EMAIL` — the bot user's email from step 2
   - `BOT_PASSWORD` — the bot user's password from step 2

### 4. Turn it on
1. In your repo, click the **Actions** tab → enable workflows if asked.
2. Done! It runs automatically at **11:00 AM and 11:00 PM Dhaka time**.
3. To run it right now: **Actions → deals-bot → Run workflow**.

## Approving drafts
Drafts from Giveaway of the Day / WinningPC appear in your data but are marked
`status: "draft"`. In your admin panel's Daily Deals list you can review each one
and publish it (or delete it) — one tap each.

## Testing on your own computer
```bash
cd deal-bot
pip install -r requirements.txt
python main.py --dry-run --source epic      # see what Epic would publish (no changes)
python main.py --dry-run --source scraped   # see what the scrapers find (no changes)
```
Dry-run never touches Firebase or Cloudinary — it only prints what it found.

A real local run needs the secrets as environment variables:
```bash
export FIREBASE_API_KEY=... FIREBASE_DB_URL=... BOT_EMAIL=... BOT_PASSWORD=...
python main.py --source all
```

## Honest limits
- **Scrapers can break.** If Giveaway of the Day or WinningPC redesign their pages,
  those sources return nothing (logged, never crashing) until the scraper is updated.
- **Epic's feed is unofficial** but has been stable for years and is widely used.
- **Descriptions are short excerpts** (max ~400 chars) and every item links back to
  the source page — respectful and safe.
- **Prices are numbers-only** (e.g. `24.99`) — the website adds the `$` at display
  (site theme v44 convention). Epic's original prices flow straight into your
  WinningPC-style "Free ~~$24.99~~" cards automatically.
- **Images are re-uploaded to your Cloudinary** (`site-deals` folder), so your site
  never hotlinks someone else's server. If an upload fails, the original URL is
  kept and the run continues.
- The bot only **adds** deals — it never edits or deletes your existing posts.
