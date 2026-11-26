# FortiSales AI — Local Setup and Troubleshooting Guide

This guide provides end-to-end instructions for installing, configuring, running, and troubleshooting FortiSales AI on a local workstation (Windows, macOS, or Linux).

---

## 1. System Requirements & Prerequisites

| Component | Minimum Version | Recommended Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Operating System** | Windows 10/11, Ubuntu 22.04+, macOS 12+ | Windows 11 / Ubuntu 22.04 LTS | Host OS |
| **Python** | 3.11.0 | 3.11.9+ | Backend runtime |
| **PostgreSQL** | 15.0+ | 16.x | Relational DB + pgvector & btree_gist |
| **Redis** | 6.2+ | 7.x (Optional) | Voice tickets & distributed locking |
| **Web Browser** | Modern Chromium / Firefox | Chrome 120+ / Edge | Browser AudioWorklet & Web Audio |

> [!NOTE]
> Redis is **optional** for local development. If Redis is unavailable or unconfigured, FortiSales AI automatically falls back to secure in-memory ticket management without crashing.

---

## 2. Step-by-Step Installation (PowerShell on Windows)

### Step 1: Clone Repository and Enter Workspace
```powershell
git clone https://github.com/Sourav6404/-Autonomous-AI-Sales-Voice-Agent.git "FortiSales AI"
cd "FortiSales AI"
```

### Step 2: Create and Activate Python Virtual Environment
```powershell
python -m venv venv
# If execution policy restricts scripts, allow for process:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

### Step 3: Install Required Dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure Local Environment Variables
Create your local `.env` configuration file from the template:
```powershell
Copy-Item .env.example .env
```

Open `.env` and verify your local PostgreSQL connection credentials:
```env
APP_NAME="FortiSales AI"
APP_ENV="development"
DEBUG=true
API_V1_PREFIX="/v1"
SECRET_KEY="local_dev_super_secret_key_change_in_production"

# Local PostgreSQL 16 Credentials
POSTGRES_SERVER="localhost"
POSTGRES_PORT=5432
POSTGRES_USER="fortisales_user"
POSTGRES_PASSWORD="fortisales_secure_dev_pw"
POSTGRES_DB="fortisales_db"

DATABASE_URL="postgresql+asyncpg://fortisales_user:fortisales_secure_dev_pw@localhost:5432/fortisales_db"
SYNC_DATABASE_URL="postgresql+psycopg2://fortisales_user:fortisales_secure_dev_pw@localhost:5432/fortisales_db"

# AI & Voice Engine Configuration
DEFAULT_AI_PROVIDER="openai" # "openai" or "gemini"
STT_PROVIDER="deepgram"       # "deepgram" or "mock"
TTS_PROVIDER="cartesia"       # "cartesia", "elevenlabs", or "mock"
```

---

## 3. Database Initialization & Alembic Migrations

FortiSales AI utilizes PostgreSQL with two essential extensions:
- `vector`: Provides 384-dimensional cosine vector indexing for RAG knowledge retrieval.
- `btree_gist`: Provides exclusion constraints (`tstzrange`) preventing overlapping appointment bookings for employees.

### Step 1: Create Database & Enable Extensions
Open `psql` or pgAdmin as administrator/superuser (`postgres`):
```sql
CREATE USER fortisales_user WITH PASSWORD 'fortisales_secure_dev_pw';
CREATE DATABASE fortisales_db OWNER fortisales_user;
GRANT ALL PRIVILEGES ON DATABASE fortisales_db TO fortisales_user;

\c fortisales_db

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
GRANT ALL ON SCHEMA public TO fortisales_user;
```

### Step 2: Run Database Migrations
Execute Alembic migrations to build all schema tables, indexes, and constraints:
```powershell
alembic upgrade head
```

Verify migration status:
```powershell
alembic current
```
The head revision should match `0006_stage7_appointments`.

---

## 4. Running the Application

### Start Backend Development Server
Run Uvicorn with auto-reload:
```powershell
uvicorn backend.app.main:app --reload --port 8000
```

### Verify Service Health
Open a browser or terminal and check the health endpoints:
- **Liveness Probe**: `http://localhost:8000/v1/health/live`
- **Readiness Probe**: `http://localhost:8000/v1/health/ready`
  - Returns PostgreSQL latency, Redis status, configured AI provider, and Voice engine status.
- **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`

---

## 5. Portal & Workspace URL Directory

FortiSales AI provides dedicated workspaces powered by role-based access control and a unified frontend:

| Workspace URL | Role Required | Key Capabilities |
| :--- | :--- | :--- |
| `http://localhost:8000/` | Public / All | Unified Portal Hub, login, and registration |
| `http://localhost:8000/admin-dashboard` | Admin | Org settings, business hours, service catalogue, employee management, overall stats |
| `http://localhost:8000/receptionist-dashboard` | Receptionist / Admin | Calendar booking, appointments list/month views, customer directory, inquiries, **live handoff queue** |
| `http://localhost:8000/sales-dashboard` | Sales Rep / Admin | Assigned lead pipeline, stage progression (new -> contacted -> qualified -> converted), follow-up tasks |
| `http://localhost:8000/voice-console` | Any Authenticated User | Real-time browser AudioWorklet voice session, live STT/TTS transcript, barge-in testing |
| `http://localhost:8000/knowledge-console` | Admin | Document uploads (PDF, TXT, DOCX), FAQ CRUD, vector retrieval inspection |

---

## 6. Mock vs. Live Provider Configurations

FortiSales AI is architected to operate **offline with zero external API costs** using mock providers, or **online** with enterprise streaming providers:

### Offline / Local Mock Mode (Default for automated tests)
In `.env`:
```env
DEFAULT_AI_PROVIDER="openai" # Uses mock when keys are unset
STT_PROVIDER="mock"
TTS_PROVIDER="mock"
```
- STT simulates speech recognition without consuming Deepgram credits.
- TTS returns valid PCM16 silence frames for seamless audio worklet integration.
- Tests execute deterministically without network flakiness.

### Live Production Mode
In `.env`:
```env
# AI Provider (OpenAI or Google Gemini)
DEFAULT_AI_PROVIDER="openai"
OPENAI_API_KEY="sk-..."
OPENAI_MODEL="gpt-4o-mini"

# Speech-to-Text (Deepgram Streaming)
STT_PROVIDER="deepgram"
DEEPGRAM_API_KEY="..."
DEEPGRAM_MODEL="nova-2"

# Text-to-Speech (Cartesia or ElevenLabs)
TTS_PROVIDER="cartesia"
CARTESIA_API_KEY="..."
CARTESIA_MODEL="sonic-english"
CARTESIA_VOICE_ID="a0e99841-438c-4a64-b679-ae501e7d6091"
```

---

## 7. Running the Automated Test Suite

Run the complete regression test suite against local PostgreSQL 16:
```powershell
python -m pytest backend/tests -v
```

Run specific test modules:
```powershell
# Stage 8: Human Handoff and Fallback
python -m pytest backend/tests/test_stage8_human_handoff.py -v

# Stage 7: Calendar & Appointments
python -m pytest backend/tests/test_stage7_appointments_api.py -v

# Stage 6: CRM, Customers, Leads
python -m pytest backend/tests/test_stage6_crm_api.py -v

# Stage 4: Voice Gateway & Pipeline
python -m pytest backend/tests/test_stage4_voice_gateway.py backend/tests/test_stage4_voice_pipeline.py -v
```

---

## 8. Troubleshooting Common Issues

### Issue 1: `Extension "vector" does not exist`
**Cause**: The PostgreSQL server does not have the `pgvector` extension installed.
**Resolution**:
- Windows: Download `pgvector` compiled DLLs for PostgreSQL 16 or use Docker: `docker run -d --name pg -p 5432:5432 -e POSTGRES_PASSWORD=pass pgvector/pgvector:pg16`.
- Linux: `sudo apt install postgresql-16-pgvector`.
- Connect as superuser and execute: `CREATE EXTENSION IF NOT EXISTS vector;`.

### Issue 2: `Extension "btree_gist" does not exist`
**Cause**: GiST exclusion constraints require `btree_gist` for non-interval columns (`employee_id`).
**Resolution**:
- `btree_gist` is included with standard PostgreSQL distributions.
- Connect as superuser and run: `CREATE EXTENSION IF NOT EXISTS btree_gist;`.

### Issue 3: Redis warning on startup (`Redis unavailable for voice tickets; using in-memory dev fallback`)
**Cause**: Redis is not running locally on port 6379.
**Resolution**:
- This is an **informational warning** in development. The system automatically switches to thread-safe in-memory ticket storage.
- If distributed multi-worker deployment is required, start local Redis: `redis-server` or `docker run -d -p 6379:6379 redis:7`.

### Issue 4: WebSocket Voice Connection Fails (4401 or 4403)
**Cause**:
- `4401 Unauthorized`: Ticket expired (>30 seconds) or was already redeemed (tickets are atomic single-use). Request a fresh ticket via `POST /api/v1/voice/tickets`.
- `4403 Forbidden`: Origin header does not match authorized application origins. Ensure you are accessing via `http://localhost:8000` or configured origins.

### Issue 5: Port 8000 Conflict
**Cause**: Another service is running on port 8000.
**Resolution**:
```powershell
# Find conflicting process
netstat -ano | findstr :8000
# Or start on alternate port:
uvicorn backend.app.main:app --reload --port 8080
```

### Issue 6: PowerShell script execution blocked
**Cause**: Windows Restricted execution policy prevents virtual environment activation.
**Resolution**:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```
