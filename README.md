# NFT Offer Bot (Telegram Business)

A minimal Python bot for sending custom NFT gift offer messages through a connected Telegram Business account.

## Important limitations

- These are custom bot messages, not native/system Telegram gift offers.
- A bot cannot start a private conversation with an arbitrary `@username`. The target chat must already be accessible through the connected Business account and be learned from an incoming business message.
- This sample stores chats and offers in memory. Render restarts clear them.
- `/received ID` records the administrator's manual confirmation only; it does not verify NFT ownership or transfer automatically.
- Stars payouts are manual and are not performed by this code.
- Do not commit `.env` or share your bot token.

## Commands

`/offer @username 1000 https://t.me/nft/...`

`/received OFFER_ID`

## Run locally

1. Install Python 3.11+.
2. Run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set `BOT_TOKEN` and `ADMIN_ID`.
4. Run `python bot.py`.

## Deploy on Render

Create a **Background Worker** linked to this repository.

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`

Set `BOT_TOKEN` and `ADMIN_ID` under Render Environment Variables.

Do not run the same bot token in another long-polling process at the same time.
