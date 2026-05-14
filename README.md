# AI Lead Automation

> **Server-side AI agent that monitors Airtasker in real-time, auto-bids on matching jobs, and sends instant Telegram notifications when a lead is won.**

---

## Architecture

```
Airtasker (WebSocket/XHR)
        │
        ▼
  [Listener] ──► [Job Queue]
                     │
                     ▼
               [Evaluator] (GPT-4o-mini)
               ├── Distance filter (radius check)
               ├── Keyword exclusion
               └── AI: skill match + bid generation
                     │
                     ▼
                [Bidder] (Playwright stealth)
               ├── Opens isolated browser tab
               ├── Submits humanised bid
               └── Extracts contact on win
                     │
                     ▼
               [Notifier] ──► Telegram Bot 🏆
                     │
                     ▼
               [Dashboard] ─► http://localhost:8000
```

## Quick Start

### 1. Clone & install
```bash
git clone <repo>
cd ai-leads
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your credentials:
# - OPENAI_API_KEY
# - AIRTASKER_EMAIL / AIRTASKER_PASSWORD
# - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
# - CAPSOLVER_API_KEY (Cloudflare Turnstile via https://www.capsolver.com/)
# - PROXY_HOST / PROXY_PORT / PROXY_USERNAME / PROXY_PASSWORD (optional)
```

Edit your profile at `config/profiles/default.json`:
```json
{
  "home_suburb": "Parramatta",
  "home_lat": -33.8136,
  "home_lng": 151.0034,
  "radius_km": 15,
  "skills": ["carpentry", "decking", "fencing"],
  "min_hourly_rate": 100
}
```

### 3. Run (dry run first!)
```bash
# Dry run — listens + evaluates but NEVER submits bids
python main.py --dry-run

# Live — submits real bids
python main.py
```

Dashboard: **http://localhost:8000**

### 4. Docker (production VPS)
```bash
cp .env.example .env   # fill in your values
docker compose up -d
docker compose logs -f agent
```

### 5. PM2 (alternative to Docker)
```bash
npm install -g pm2
pm2 start ecosystem.config.js
pm2 logs ai-lead-agent
```

---

## Project Structure

```
ai-leads/
├── main.py                        # Entry point
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── ecosystem.config.js            # PM2 config
│
├── config/
│   ├── settings.py                # Pydantic env settings
│   └── profiles/default.json     # Carpenter profile
│
├── agent/
│   ├── models.py                  # Job dataclass, enums
│   ├── store.py                   # In-memory job store (dashboard)
│   ├── listener.py                # Orchestration pipeline
│   ├── evaluator.py              # GPT-4o-mini filter + bid gen
│   ├── bidder.py                  # Bid submission controller
│   ├── session.py                 # Playwright auth manager
│   └── notifier.py               # Telegram bot
│
├── platforms/
│   ├── base.py                    # Abstract platform interface
│   └── airtasker.py              # Airtasker WS/XHR + bid + contact
│
├── stealth/
│   ├── browser.py                 # Stealth Chromium factory
│   ├── behavior.py               # Human mouse/keyboard sim
│   ├── captcha.py                # Turnstile: CapSolver + browser fallback
│   └── capsolver_client.py       # CapSolver createTask / getTaskResult
│
├── dashboard/
│   ├── app.py                    # FastAPI backend
│   └── static/index.html        # Dark-mode SPA dashboard
│
└── tests/
    ├── test_evaluator.py
    ├── test_notifier.py
    └── mock_ws_server.py         # Fake Airtasker WS server
```

---

## Running Tests
```bash
pytest tests/ -v
```

Expected output: 10 passing tests (no API keys needed — all mocked).

---

## Getting API Keys

| Service | URL | Cost |
|---|---|---|
| OpenAI | [platform.openai.com](https://platform.openai.com) | ~$0.01 per 100 evaluations |
| Telegram Bot | Message [@BotFather](https://t.me/botfather) | Free |
| CapSolver | [capsolver.com](https://www.capsolver.com/) | Cloudflare Turnstile (~$1.2/1k per [their pricing](https://www.capsolver.com/)) |
| Residential Proxy | [iproyal.com](https://iproyal.com) | ~$7/GB |

---

## ⚠️ Important Disclaimer

This tool automates actions on a third-party platform. Using it may violate Airtasker's Terms of Service. Use at your own risk. A dedicated test account is strongly recommended before running against a production account.
