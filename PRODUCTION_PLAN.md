# AI Lead Automation — Production Separation Plan
## Python API + Next.js Frontend Architecture

**Document Date:** May 15, 2026  
**Status:** Planning Phase  
**Goal:** Separate monolithic Python backend from embedded dashboard into production-ready microservices

---

## 1. Current State Analysis

### Current Architecture (Monolithic)
```
ai-leads/
├── main.py                    # FastAPI + Agent orchestrator
├── dashboard/app.py           # FastAPI serving static HTML
├── dashboard/static/          # Embedded SPA (vanilla JS)
├── agent/                     # Core automation logic
│   ├── listener.py           # Job queue coordinator
│   ├── evaluator.py          # AI skill matching (GPT-4o-mini)
│   ├── bidder.py             # Playwright automation
│   ├── notifier.py           # Telegram alerts
│   ├── session.py            # Browser session management
│   ├── store.py              # Redis-backed state
│   └── models.py             # Data models
├── platforms/                 # Platform adapters (Airtasker)
├── stealth/                  # Browser stealth + CAPTCHA solving
└── config/                   # Settings & profiles
```

### Current Problems
1. **Tight Coupling:** Dashboard UI and agent logic in single process
2. **Scaling Issues:** Can't scale API independently from frontend
3. **Deployment Complexity:** Can't deploy frontend to CDN separately
4. **Technology Mismatch:** Python-only = harder to iterate on UI
5. **Maintenance:** Single codebase = deployment risk (frontend bug blocks agent)
6. **Performance:** Static HTML served from Python process

### Current Strengths to Preserve
✅ Real-time SSE log streaming  
✅ Redis state management (distributed, scalable)  
✅ Clear separation of concerns (listener/evaluator/bidder/notifier)  
✅ Test infrastructure (pytest/mock_ws_server)  
✅ Docker containerization  

---

## 2. Target Architecture (Production)

```
┌─────────────────────────────────────────────────────────────────┐
│                         PRODUCTION INFRA                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────┐              ┌──────────────────┐         │
│  │   FRONTEND       │              │   BACKEND API    │         │
│  │   (Next.js)      │◄────────────►│   (Python)       │         │
│  │   Vercel/Netlify │   HTTPS      │   (FastAPI)      │         │
│  │                  │              │   Docker/Cloud   │         │
│  ├──────────────────┤              ├──────────────────┤         │
│  │ - Dashboard UI   │              │ - Agent Loop     │         │
│  │ - Real-time logs │              │ - REST API       │         │
│  │ - Stats display  │              │ - WebSocket      │         │
│  │ - Settings       │              │ - Redis Bridge   │         │
│  └──────────────────┘              └──────────────────┘         │
│         CDN                                                       │
│    (images, JS)                                                   │
│                                                                   │
│  ┌──────────────────┐              ┌──────────────────┐         │
│  │   REDIS          │              │  POSTGRES        │         │
│  │   (Shared State) │              │  (Optional: Logs)│         │
│  └──────────────────┘              └──────────────────┘         │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principles
- **API First:** Backend exposes REST + WebSocket APIs
- **Frontend Agnostic:** Dashboard is a completely separate deployment
- **Stateless API:** All state in Redis (allows horizontal scaling)
- **Independent Deployment:** Can push UI changes without restarting agent
- **Real-time:** WebSocket for log streaming, REST for data updates

---

## 3. API Contract Design

### REST Endpoints (Base: `/api/v1/`)

#### Stats & Monitoring
```
GET  /api/v1/stats
     Response: { jobs_seen, jobs_evaluated, bids_placed, wins, earnings, uptime }

GET  /api/v1/leads
     Response: [{ job_id, title, budget, status, bid_amount, created_at }...]

GET  /api/v1/logs?limit=100&offset=0
     Response: { logs: [{ timestamp, level, message }...], total: 1500 }
```

#### Session Management
```
GET  /api/v1/session/status
     Response: { status: "VALID" | "INVALID" | "NEEDS_REAUTH", expires_at }

POST /api/v1/session/login
     Request: (trigger manual login flow)
     Response: { message: "Login flow started", manual_url: "..." }

POST /api/v1/session/logout
     Response: { message: "Logged out" }
```

#### Agent Control
```
GET  /api/v1/agent/status
     Response: { is_running, mode: "LIVE" | "DRY_RUN", pid, since, workers }

POST /api/v1/agent/start?mode=LIVE
     Response: { message: "Agent started", mode }

POST /api/v1/agent/stop
     Response: { message: "Agent stopped" }

POST /api/v1/agent/pause
     Response: { message: "Agent paused (evaluates but doesn't bid)" }
```

#### Profile Management
```
GET  /api/v1/profile
     Response: { home_suburb, radius_km, skills: [], min_hourly_rate, ... }

PUT  /api/v1/profile
     Request: { home_suburb, radius_km, skills, min_hourly_rate, ... }
     Response: { message: "Profile updated", profile }

GET  /api/v1/profiles
     Response: [{ name, config, is_default, created_at }...]

POST /api/v1/profiles
     Request: { name, config: {...} }
     Response: { profile_id, profile }
```

#### Health & System
```
GET  /api/v1/health
     Response: { status: "ok" | "degraded", redis: "connected", agents_alive: 2 }

GET  /api/v1/version
     Response: { version: "1.0.0", backend: "python/fastapi", frontend: "next.js" }
```

### WebSocket Endpoints
```
WS /ws/logs?token=AUTH_TOKEN
   - Real-time log stream (SSE alternative)
   - Message: { type: "log", timestamp, level, message }
   - Message: { type: "job", job_id, title, status }
   - Message: { type: "win", job_id, earnings }

WS /ws/stats?token=AUTH_TOKEN
   - Real-time stats push
   - Every 5 seconds: { jobs_seen_delta, bids_delta, wins_delta }
```

### Response Format (Standardized)
```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "timestamp": "2026-05-15T10:30:00Z"
}
```

---

## 4. New Directory Structure

### Backend (Python API)
```
backend/
├── pyproject.toml            # Modern Python packaging
├── requirements.txt
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .env.example
├── main.py                   # FastAPI app entry
├── settings.py               # Config management
│
├── api/                      # REST endpoints
│   ├── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── stats.py         # /stats, /leads, /logs
│   │   ├── session.py       # /session/status, /login, /logout
│   │   ├── agent.py         # /agent/status, /start, /stop, /pause
│   │   ├── profile.py       # /profile, /profiles
│   │   └── health.py        # /health, /version
│   ├── ws/                   # WebSocket handlers
│   │   ├── __init__.py
│   │   ├── logs_stream.py
│   │   └── stats_stream.py
│   ├── dependencies.py       # Auth, validation, DI
│   └── errors.py             # Exception handlers
│
├── agent/                    # Core automation (existing)
│   ├── listener.py          # Orchestrator
│   ├── evaluator.py         # AI matching
│   ├── bidder.py            # Playwright automation
│   ├── notifier.py          # Telegram
│   ├── session.py           # Browser session
│   ├── store.py             # Redis interface
│   ├── models.py            # Pydantic models
│   └── __init__.py
│
├── platforms/               # Existing (Airtasker)
├── stealth/                 # Existing (browser stealth)
├── config/                  # Profiles, settings
├── logs/                    # Runtime logs
├── tests/                   # Existing test suite
└── README.md
```

### Frontend (Next.js)
```
frontend/
├── package.json
├── next.config.js           # Next.js config
├── tailwind.config.js       # If using Tailwind
├── tsconfig.json            # TypeScript config
├── .env.example
│
├── src/
│   ├── pages/               # App Router
│   │   ├── page.tsx         # Dashboard home
│   │   ├── logs/
│   │   │   └── page.tsx
│   │   ├── profile/
│   │   │   └── page.tsx
│   │   ├── api/
│   │   │   ├── socket.ts    # WebSocket helpers
│   │   │   └── client.ts    # API client wrapper
│   │   └── layout.tsx       # Root layout
│   │
│   ├── components/
│   │   ├── Header.tsx
│   │   ├── Stats.tsx
│   │   ├── JobsList.tsx
│   │   ├── LogsViewer.tsx
│   │   ├── ProfileEditor.tsx
│   │   └── AgentControls.tsx
│   │
│   ├── hooks/
│   │   ├── useApi.ts        # React Query / SWR wrapper
│   │   ├── useWebSocket.ts
│   │   └── useStats.ts
│   │
│   ├── lib/
│   │   ├── api-client.ts    # HTTP/WS client config
│   │   ├── auth.ts          # Auth utilities
│   │   └── constants.ts
│   │
│   └── styles/
│       └── globals.css      # Tailwind / base styles
│
├── public/
│   ├── favicon.ico
│   └── logo.png
│
├── __tests__/
├── Dockerfile               # For containerized frontend (optional)
├── .dockerignore
├── .gitignore
└── README.md
```

---

## 5. Backend: FastAPI Refactoring

### Current main.py (Simplified)
```python
# main.py
import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from agent.listener import Listener
from dashboard.app import app as dashboard_app

# Background task: run listener agent
listener = None
listener_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global listener, listener_task
    listener = Listener()
    listener_task = asyncio.create_task(listener.run())
    yield
    # Shutdown
    if listener_task:
        listener_task.cancel()

# Main API app
app = FastAPI(title="AI Lead Agent API", lifespan=lifespan)

# Register API routes
app.include_router(routes.stats.router)
app.include_router(routes.session.router)
app.include_router(routes.agent.router)
app.include_router(routes.profile.router)
app.include_router(routes.health.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
```

### New Route Structure
```python
# api/routes/stats.py
from fastapi import APIRouter, Depends
from api.dependencies import get_store

router = APIRouter(prefix="/api/v1", tags=["stats"])

@router.get("/stats")
async def get_stats(store = Depends(get_store)):
    return await store.get_stats()

@router.get("/leads")
async def get_leads(limit: int = 100, offset: int = 0):
    # Paginated leads from Redis or Postgres
    pass

@router.get("/logs")
async def get_logs(limit: int = 100, offset: int = 0):
    # Fetch logs from Redis or new Postgres logs table
    pass
```

### Authentication Middleware
```python
# api/dependencies.py
from fastapi import Depends, HTTPException, Header

async def get_auth_user(authorization: str = Header(None)):
    """JWT/API key validation"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing auth")
    # Validate token
    return user

async def get_store(auth_user = Depends(get_auth_user)):
    """DI: provide Redis store instance"""
    return agent.store
```

---

## 6. Frontend: React → Next.js Migration

### Create Next.js App
```bash
cd frontend
npx create-next-app@latest --typescript --tailwind --eslint
```

### Key Components to Build

#### API Client (`src/lib/api-client.ts`)
```typescript
export class ApiClient {
  private baseUrl: string;
  private token: string;

  constructor(baseUrl: string, token: string) {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
    if (!res.ok) throw new Error(`API Error: ${res.status}`);
    return res.json();
  }

  async getStats() { return this.request("/api/v1/stats"); }
  async getLeads() { return this.request("/api/v1/leads"); }
  async getProfile() { return this.request("/api/v1/profile"); }
  async updateProfile(profile: any) {
    return this.request("/api/v1/profile", { method: "PUT", body: JSON.stringify(profile) });
  }
  async startAgent(mode: "LIVE" | "DRY_RUN") {
    return this.request(`/api/v1/agent/start?mode=${mode}`, { method: "POST" });
  }
}
```

#### Hooks
```typescript
// src/hooks/useApi.ts
import useSWR from "swr";
import { useAuth } from "./useAuth";

export function useStats() {
  const { client } = useAuth();
  const { data, error, isLoading, mutate } = useSWR(
    "/api/v1/stats",
    () => client.getStats(),
    { refreshInterval: 5000 }
  );
  return { stats: data, error, isLoading, refresh: mutate };
}

// src/hooks/useWebSocket.ts
export function useWebSocket(url: string) {
  const [data, setData] = useState(null);
  const { token } = useAuth();

  useEffect(() => {
    const ws = new WebSocket(`${url}?token=${token}`);
    ws.onmessage = (e) => setData(JSON.parse(e.data));
    return () => ws.close();
  }, [url, token]);

  return data;
}
```

#### Dashboard Components
```typescript
// src/components/Stats.tsx
import { useStats } from "@/hooks/useApi";

export function Stats() {
  const { stats, isLoading } = useStats();
  if (isLoading) return <div>Loading...</div>;
  return (
    <div className="grid grid-cols-4 gap-4">
      <Card label="Jobs Seen" value={stats.jobs_seen} />
      <Card label="Bids Placed" value={stats.bids_placed} />
      <Card label="Wins" value={stats.wins} />
      <Card label="Earnings" value={`$${stats.earnings}`} />
    </div>
  );
}

// src/components/LogsViewer.tsx
export function LogsViewer() {
  const logs = useWebSocket("ws://localhost:8000/ws/logs");
  return (
    <div className="font-mono text-sm bg-black rounded p-4 h-96 overflow-y-auto">
      {logs?.map((log, i) => (
        <div key={i} className={`text-${log.level}`}>{log.message}</div>
      ))}
    </div>
  );
}
```

---

## 7. State Management & Data Layer

### Redis Schema (Existing + Expanded)
```
# Job tracking
jobs:all -> [Job]
job:{id} -> Job
job:{id}:bid -> Bid
job:{id}:status -> "seen" | "evaluated" | "bid_placed" | "won"

# Stats aggregation
stats:daily:{date} -> { jobs_seen, bids, wins, earnings }
stats:lifetime -> { total_jobs, total_bids, total_wins, total_earnings }

# Session state
session:status -> "VALID" | "INVALID"
session:expires_at -> timestamp

# Logs (circular buffer or with TTL)
logs:stream -> [LogEntry] (with Redis Stream or sorted set + TTL)

# Agent state
agent:running -> bool
agent:mode -> "LIVE" | "DRY_RUN"
agent:workers:alive -> N

# Profiles
profile:active -> Profile (JSON)
profiles:all -> [Profile]
```

### Optional: Add PostgreSQL for Long-term Storage
```sql
-- logs table (Redis TTL 7 days, Postgres permanent)
CREATE TABLE logs (
  id SERIAL PRIMARY KEY,
  timestamp TIMESTAMP,
  level VARCHAR(10),
  message TEXT,
  agent_id VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);

-- leads table
CREATE TABLE leads (
  id SERIAL PRIMARY KEY,
  job_id VARCHAR(50) UNIQUE,
  title VARCHAR(500),
  budget DECIMAL,
  status VARCHAR(50),
  bid_amount DECIMAL,
  created_at TIMESTAMP,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- earnings table
CREATE TABLE earnings (
  id SERIAL PRIMARY KEY,
  job_id VARCHAR(50),
  amount DECIMAL,
  status VARCHAR(50),
  earned_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 8. Authentication & Security

### API Authentication (JWT or API Key)
```python
# api/dependencies.py - JWT auth
from fastapi.security import HTTPBearer, HTTPAuthCredentials
import jwt

async def get_current_user(credentials: HTTPAuthCredentials = Depends(HTTPBearer())):
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=["HS256"]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401)
        return user_id
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401)
```

### Frontend Auth Flow
```typescript
// src/hooks/useAuth.ts
export function useAuth() {
  const [token, setToken] = useState(localStorage.getItem("auth_token"));
  const client = useMemo(() => new ApiClient(API_BASE_URL, token), [token]);

  const login = async (email: string, password: string) => {
    const { access_token } = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }).then(r => r.json());
    localStorage.setItem("auth_token", access_token);
    setToken(access_token);
  };

  return { token, client, login };
}
```

---

## 9. Deployment Strategy

### Development (Local)
```bash
# Terminal 1: Backend
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py

# Terminal 2: Frontend
cd frontend
npm install
npm run dev

# Terminal 3: Redis (Docker)
docker run -p 6379:6379 redis:7-alpine
```

### Production: Backend (Docker/Cloud)

#### Option A: Docker Compose (Single Server)
```yaml
# docker-compose.yml
version: "3.9"

services:
  api:
    build:
      context: ./backend
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    env_file: .env.prod
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

#### Option B: Kubernetes / Cloud Run (Google Cloud / AWS)
```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-lead-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ai-lead-api
  template:
    metadata:
      labels:
        app: ai-lead-api
    spec:
      containers:
      - name: api
        image: gcr.io/your-project/ai-lead-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          value: redis://redis-service:6379
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: credentials
              key: openai-key
```

### Production: Frontend (CDN + Vercel)

#### Deploy to Vercel (Recommended)
```bash
npm install -g vercel
vercel                           # Interactive deployment
vercel env add API_BASE_URL https://api.yourdomain.com
vercel deploy --prod
```

#### Or Docker + Docker Registry
```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
RUN npm ci --only=production
EXPOSE 3000
CMD ["npm", "start"]
```

---

## 10. Implementation Phases

### Phase 1: Backend Refactoring (Week 1-2)
- [ ] Create `/api/routes/` structure
- [ ] Migrate FastAPI endpoints to new routes
- [ ] Add proper error handling & logging middleware
- [ ] Implement authentication (JWT)
- [ ] Add OpenAPI/Swagger documentation
- [ ] Refactor store.py to expose async methods
- [ ] Write integration tests

**Deliverable:** Backend API running on `http://localhost:8000` with `/api/v1/*` endpoints

### Phase 2: Frontend Setup (Week 2-3)
- [ ] Initialize Next.js project
- [ ] Set up TypeScript & Tailwind CSS
- [ ] Create API client wrapper
- [ ] Build auth flow (login/logout)
- [ ] Recreate dashboard layout (migrate from vanilla HTML)
- [ ] Implement SWR hooks for data fetching
- [ ] Add WebSocket support for log streaming

**Deliverable:** Frontend running on `http://localhost:3000` connecting to backend

### Phase 3: Feature Parity (Week 3-4)
- [ ] Migrate all dashboard features
  - [ ] Stats cards
  - [ ] Jobs list (paginated)
  - [ ] Live logs viewer (WebSocket)
  - [ ] Session management (login form)
  - [ ] Agent controls (start/stop/pause)
  - [ ] Profile editor
- [ ] Add error boundaries & loading states
- [ ] Implement real-time updates (WebSocket)

**Deliverable:** Feature-complete Next.js frontend with all existing functionality

### Phase 4: Testing & Optimization (Week 4-5)
- [ ] End-to-end tests (Playwright/Cypress)
- [ ] Performance optimization (images, code splitting)
- [ ] Load testing on API
- [ ] Security audit (CORS, auth, input validation)
- [ ] Documentation (API docs, deployment guide)

**Deliverable:** Tested, optimized, documented system

### Phase 5: Deployment (Week 5-6)
- [ ] Set up CI/CD (GitHub Actions)
- [ ] Configure Docker builds
- [ ] Deploy backend to Cloud Run / VPS
- [ ] Deploy frontend to Vercel / S3+CloudFront
- [ ] Configure domain & SSL
- [ ] Set up monitoring & alerts

**Deliverable:** Live production system

---

## 11. Migration Checklist

### Breaking Changes to Handle
- [ ] API paths change from `/` to `/api/v1/*`
- [ ] CORS configuration (frontend domain != backend domain)
- [ ] Authentication required (add bearer token to frontend)
- [ ] WebSocket URL structure (new endpoint)
- [ ] Error response format (standardize)

### Backward Compatibility
- [ ] Keep old `/dashboard` route redirecting to frontend URL
- [ ] Support both old `.html` and new API during transition
- [ ] Feature flags for gradual rollout

### Data Migration
- [ ] Redis data persists (no schema changes needed)
- [ ] Log history remains accessible
- [ ] Stats/earnings data preserved

---

## 12. Technology Stack Summary

| Component | Current | New |
|-----------|---------|-----|
| **Backend** | FastAPI | FastAPI (refactored) |
| **Frontend** | Vanilla HTML/CSS/JS | Next.js + TypeScript |
| **State** | Redis | Redis + Optional: PostgreSQL |
| **Auth** | None | JWT |
| **Deployment** | Docker Compose | Docker + Vercel / Cloud Run |
| **Frontend Hosting** | Same server | Vercel / Netlify / S3+CDN |
| **API Documentation** | None | Swagger/OpenAPI |

---

## 13. Success Criteria

✅ **Independent Deployments:** Push frontend code without restarting agent  
✅ **Scalability:** Can run multiple agent instances with shared Redis  
✅ **Production Ready:** Error handling, logging, monitoring  
✅ **Security:** Authentication, rate limiting, input validation  
✅ **Observability:** Structured logging, metrics, alerting  
✅ **Developer Experience:** Clear API docs, type-safe frontend  
✅ **Performance:** Sub-100ms API responses, real-time log streaming  

---

## 14. Quick Reference: Key Files to Create/Modify

### Backend
- [ ] `backend/api/routes/*.py` - New route modules
- [ ] `backend/api/dependencies.py` - Auth & DI
- [ ] `backend/api/errors.py` - Exception handlers
- [ ] `backend/docker/Dockerfile` - Updated image
- [ ] `backend/README.md` - API documentation
- [ ] `backend/settings.py` - Configuration (refactored)

### Frontend
- [ ] `frontend/src/lib/api-client.ts` - HTTP client
- [ ] `frontend/src/hooks/*.ts` - Custom hooks
- [ ] `frontend/src/components/*.tsx` - React components
- [ ] `frontend/src/pages/layout.tsx` - Root layout
- [ ] `frontend/.env.example` - Config template
- [ ] `frontend/next.config.js` - Next.js config

### DevOps
- [ ] `.github/workflows/deploy.yml` - CI/CD pipeline
- [ ] `k8s/deployment.yaml` - Kubernetes manifests (optional)
- [ ] `docker-compose.prod.yml` - Production compose file

---

## 15. Questions & Next Steps

**Clarifications Needed:**
1. **Frontend Hosting:** Vercel, self-hosted Docker, or other?
2. **Database:** PostgreSQL for historical logs or stick with Redis?
3. **Auth Method:** JWT, API keys, or simple bearer tokens?
4. **Monitoring:** DataDog, New Relic, or simple logging?
5. **Multi-tenant:** Support multiple user profiles or single user?

**Immediate Next Steps:**
1. Review this plan and confirm direction
2. Set up separate `backend/` and `frontend/` directories
3. Begin Phase 1: Backend API refactoring
4. Create base Next.js project structure

---

**Document Version:** 1.0  
**Last Updated:** May 15, 2026  
**Next Review:** After Phase 1 completion
