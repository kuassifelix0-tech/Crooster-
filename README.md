# CROOSTER Telegram Mini App — starter MVP

A small custom-built Telegram Mini App prototype with:
- tap-to-earn virtual points and regenerating energy
- daily bonus (once per 24 hours)
- referral links and a 50-point inviter bonus for a new player
- leaderboard
- Telegram Mini App `initData` HMAC validation on server
- `/start`, `/leaderboard`, `/help` bot commands

## Important limitations

This is an MVP starter, not audited production software. It uses SQLite by default. The local SQLite database is not suitable for a horizontally scaled or ephemeral hosting setup, and some free hosts erase local files on redeploy/restart. Before a public campaign, move player data to a persistent managed database, add abuse controls and monitoring, test the referral flow, and review applicable laws and Telegram rules. One process should run the bot polling loop; do not scale this deployment to multiple instances without changing to webhooks or a single dedicated bot worker.

Points are virtual game points only. The app does not issue a token, promise an airdrop, or guarantee financial rewards. Publish a clear points/rewards policy before announcing any conversion or eligibility criteria.

## 1. Create your bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, choose display name `CROOSTER` and a unique username ending in `bot`.
3. Save the token privately. Never paste it into this chat, a screenshot or a public repository.
4. Set the bot description and profile photo with BotFather commands.

## 2. Deploy the game

1. Create a private GitHub repository and upload these project files. Do not upload a real `.env` file or token.
2. Create a web service on Render from that repository, using `render.yaml` or the settings in it.
3. Add environment variables in Render: `BOT_TOKEN`, `BOT_USERNAME` (without `@`), and temporary `WEBAPP_URL` set to the deployed HTTPS URL. Keep `DEV_MODE=false`.
4. Deploy. Open `https://YOUR-SERVICE.onrender.com/health`; it should return `ok: true`.
5. Update `WEBAPP_URL` to the final HTTPS service URL and redeploy if needed.

Render free services are useful for testing but can sleep and have limitations. Local SQLite data can be lost on some deployments. For a real launch, connect a persistent managed database and migrate away from SQLite first.

## 3. Configure Telegram Mini App

1. Open @BotFather and select your bot using `/mybots`.
2. Open **Bot Settings → Configure Mini App** (the exact menu wording may vary), or use the current BotFather Mini App setup flow.
3. Set the Mini App URL to your deployed HTTPS URL.
4. Send `/start` to your bot. The bot replies with a **Play CROOSTER** button when `WEBAPP_URL` is set to HTTPS.

## 4. Test

- Open the bot and press Start.
- Press **Play CROOSTER**.
- Tap the rooster, claim daily reward, and try the referral link with a second Telegram account.
- `/leaderboard` shows the top 10 players.
- Confirm requests outside Telegram are rejected when `DEV_MODE=false`.

For a visual-only local test, install dependencies, set `DEV_MODE=true`, run `python app.py`, then visit `http://localhost:8080/?dev=12345`. Never enable this mode on a public deployment.

## Current scoring rules

- 1 accepted tap = 1 point.
- Energy cap = 500; restores at 1 energy/second.
- Daily reward = 100 points once every 24 hours.
- Inviter gets 50 points when a new player first starts with a valid `ref_<telegram_id>` link.
- No inviter reward is given for self-referrals or unknown inviter IDs.

These values are prototype defaults and can be adjusted before launch. Referral anti-abuse controls are basic; use stronger rate limits and fraud checks before any rewards are tied to scores.
