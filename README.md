# tv-watch

Watches TradingView's support-status feed and emails you when it changes.

That feed is what renders the orange warning banner on
<https://www.tradingview.com/support/>. It is a public JSON endpoint — no login,
no cookies, no browser:

```
GET https://www.tradingview.com/support/support-portal-problems/?language=en
{"issues":[{"id":2000375,"title":"…","description":"…","show_on_chart":false}]}
```

`show_on_chart` is worth watching: TradingView flips it when an issue is
escalated from the support page to the chart banner.

## How the email works

There is no SMTP config and no secret to set. On a change the workflow opens a
GitHub issue in this repo, and GitHub emails you about it — you are watching
your own repo by default, and the body `cc @`-mentions you as a belt-and-braces
second trigger. Cost: nothing.

To send elsewhere, set the repo variable `NOTIFY_MENTION` to another GitHub
username (Settings → Secrets and variables → Actions → Variables).

## Setup

1. Create a repo on GitHub — **public** if you want it completely free
   (scheduled workflows on public repos don't consume Actions minutes).
2. Push **the contents of this folder** as the repo root:

   ```
   <repo>/.github/workflows/watch.yml
   <repo>/watch.py
   <repo>/state.json
   <repo>/README.md
   ```

   ```bash
   cd tv-watch
   git init && git add -A && git commit -m "tv-watch: initial"
   gh repo create tv-watch --public --source=. --push
   ```

   If you instead nest it inside an existing repo, prefix the three `watch.py` /
   `state.json` paths in `watch.yml` with that subfolder.
3. Then Actions → *TradingView support watch* → **Run workflow** once to
   seed `state.json`. That first run reports whatever is currently live, so
   expect one email immediately.

Nothing else. No secrets, no runner, no server.

## Behaviour

- Polls every 15 minutes (`cron: */15 * * * *`).
- Emails on: a **new** issue, an issue whose **title/description/`show_on_chart`
  changed**, and an issue that **cleared**.
- Silent when the feed is unchanged.
- A failed fetch fails the workflow run rather than reporting "all clear" — a
  TradingView outage must not look like a clean feed. GitHub emails you about
  failed runs too, so a broken feed still reaches you.
- `state.json` carries an ISO week stamp, so the file changes at least weekly
  even during a quiet stretch. That weekly commit keeps the repo active; GitHub
  disables scheduled workflows in repos with no commits for 60 days.

## Cost

Public repo: free, unlimited. Private repo: ~15 s per run × 2,880 runs/month
≈ 12 hours, against the 2,000 free minutes — so a private repo would exceed the
free tier. Keep it public, or drop the schedule to hourly.

## Local use

```bash
python3 watch.py --show      # print the live feed
python3 watch.py --dry-run   # report changes, don't write state
python3 watch.py             # report and update state
```

Standard library only — no `pip install`.
