# Analyst Ledger

A free website listing Wall Street analyst rating changes. Each analyst gets a dated history and an independently computed track record. The site rebuilds itself every day on GitHub Pages and posts automatically to social media.

## How it runs (no manual work after setup)

| When | What happens |
|---|---|
| Every day | A scheduled Claude task reads public financial news. It adds new rating changes to `data/news_events.json`, with source links. |
| Mon–Fri 13:00 and 22:30 UTC | A GitHub Action pulls licensed API data (FMP / Finnhub, if keys are set) and merges it with the news events. It then rebuilds the site and posts **alerts** for major changes. |
| Saturday 14:00 UTC | A GitHub Action posts the **weekly recap**. It also posts any queued posts, such as the weekly options watch Claude prepares on Fridays. |

Each social platform switches on as soon as its secrets are added. A platform without secrets is skipped, and nothing breaks.

## One-time setup

### 1. Website data APIs (optional, but recommended)
- **Financial Modeling Prep:** sign up at financialmodelingprep.com and copy your API key. Add it as repo secret `FMP_API_KEY`. Check that your plan allows public display before relying on it commercially.
- **Finnhub:** sign up at finnhub.io and add the key as `FINNHUB_API_KEY`.

### 2. Social accounts → repo secrets
Secrets go in GitHub under Settings → Secrets and variables → Actions → New repository secret.

| Platform | What to create | Secrets |
|---|---|---|
| Bluesky | Account, then Settings → App passwords → Add | `BSKY_HANDLE`, `BSKY_APP_PASSWORD` |
| Telegram | Public channel, plus a bot from @BotFather. Add the bot as a channel admin. | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (e.g. `@analystledger`) |
| Mastodon | Account, then Preferences → Development → New application (scope `write`) | `MASTODON_INSTANCE`, `MASTODON_TOKEN` |
| X | Account, then developer.x.com → app with Read+Write → keys and access tokens. Mark the account as automated in its settings. | `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` |
| Facebook | A Page, plus an app at developers.facebook.com. Generate a long-lived Page access token. | `FB_PAGE_ID`, `FB_PAGE_TOKEN` |
| Instagram | Professional (Business/Creator) account linked to the Facebook Page | `IG_USER_ID` (uses `FB_PAGE_TOKEN`) |
| TikTok | Account, plus an app at developers.tiktok.com with Content Posting API. Verify the site's URL prefix. | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` |

Notes:
- TikTok keeps posts private until TikTok approves (audits) the app.
- Instagram and TikTok fetch post images from the public site, so GitHub Pages must be on.

### 3. Turn on GitHub Pages
Settings → Pages → Deploy from a branch → `main` / `/docs`.

## Files
- `config.json`: brand name, URL, alert watchlist and thresholds
- `data/events.json`: permanent history (merged from all sources)
- `data/news_events.json`: events Claude adds from the news
- `data/posts_queue.json`: posts Claude prepares (weekly options watch)
- `scripts/`: updater, site builder, social poster, image cards
- `brand/`: profile picture and banners for the social accounts

Disclaimer: information only, not investment advice.
