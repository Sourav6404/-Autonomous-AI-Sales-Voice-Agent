# FortiSales AI — Local Startup and Manual Testing Guide

This guide provides exact, step-by-step instructions for starting, configuring, running, and manually testing **FortiSales AI** on a local Windows machine using PowerShell.

---

## 1. System Prerequisites

Before running the application, ensure the following software is installed on your Windows workstation:

| Requirement | Minimum Version | Verification Command | Notes |
| :--- | :--- | :--- | :--- |
| **Python** | 3.11.0+ | `python --version` | Tested on Python 3.11.9 |
| **PostgreSQL** | 15.0+ (16 recommended) | `psql --version` | Must include `pgvector` and `btree_gist` |
| **Redis** | 6.2+ (Optional) | `redis-cli ping` | Optional; in-memory fallback engages automatically |
| **Git** | 2.30+ | `git --version` | Version control |
| **Web Browser** | Chrome 120+ / Edge | Browser UI | Supports Web Audio API `AudioWorkletNode` |

> [!NOTE]
> **Node.js and npm are NOT required**: The frontend is built entirely in Vanilla HTML5, modern CSS3, and native ES6+ JavaScript served directly via FastAPI `StaticFiles`. There are zero frontend build, bundling, or compilation steps.

---

## 2. Initial Setup & Configuration (Windows PowerShell)

Open Windows PowerShell and navigate to your project directory.

### Step 1: Create and Activate Python Virtual Environment
```powershell
# Navigate to workspace
cd "E:\pep\FortiSales AI"

# Create virtual environment
python -m venv venv

# Set execution policy for the current process and activate
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

### Step 2: Install Python Dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Create your local `.env` configuration file from the template:
```powershell
Copy-Item .env.example .env
```

Verify the database connection variables inside `.env`:
```env
APP_NAME="FortiSales AI"
APP_ENV="development"
DEBUG=true
API_V1_PREFIX="/v1"
SECRET_KEY="local_dev_secret_key_change_in_production_32b"

# PostgreSQL 16 Local Credentials
POSTGRES_SERVER="localhost"
POSTGRES_PORT=5432
POSTGRES_USER="fortisales_user"
POSTGRES_PASSWORD="fortisales_secure_dev_pw"
POSTGRES_DB="fortisales_db"

DATABASE_URL="postgresql+asyncpg://fortisales_user:fortisales_secure_dev_pw@localhost:5432/fortisales_db"
SYNC_DATABASE_URL="postgresql+psycopg2://fortisales_user:fortisales_secure_dev_pw@localhost:5432/fortisales_db"

# AI Provider Configuration (Default to mock or insert API keys)
DEFAULT_AI_PROVIDER="openai" # "openai" or "gemini"
STT_PROVIDER="deepgram"       # "deepgram" or "mock"
TTS_PROVIDER="cartesia"       # "cartesia", "elevenlabs", or "mock"
```

### Step 4: Prepare PostgreSQL Database & Extensions
Open `psql` as administrator (`postgres` superuser):
```sql
-- Create role and database
CREATE USER fortisales_user WITH PASSWORD 'fortisales_secure_dev_pw';
CREATE DATABASE fortisales_db OWNER fortisales_user;
GRANT ALL PRIVILEGES ON DATABASE fortisales_db TO fortisales_user;

-- Connect to the database
\c fortisales_db

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;
GRANT ALL ON SCHEMA public TO fortisales_user;
```

### Step 5: Run Database Migrations
Apply Alembic migrations to construct all 23 database tables, constraints, and exclusion indexes:
```powershell
alembic upgrade head
```

Verify migration status:
```powershell
alembic current
# Should output: 0006_stage7_appointments (head)
```

---

## 3. Starting the Application

Use two separate Windows PowerShell windows:

### Terminal 1: Database & Services
Ensure PostgreSQL is running locally on port 5432:
```powershell
# If using Windows PostgreSQL Service:
Get-Service -Name postgresql* | Start-Service

# Or if using Docker container:
docker run -d --name fortisales-pg -p 5432:5432 -e POSTGRES_USER=fortisales_user -e POSTGRES_PASSWORD=fortisales_secure_dev_pw -e POSTGRES_DB=fortisales_db pgvector/pgvector:pg16
```

### Terminal 2: FastAPI Backend Server
In your activated virtual environment:
```powershell
cd "E:\pep\FortiSales AI"
.\venv\Scripts\Activate.ps1

# Start Uvicorn development server
uvicorn backend.app.main:app --reload --port 8000
```

The console will output:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Starting FortiSales AI in 'development' environment
INFO:     Database connectivity established successfully.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

## 4. Manual Testing Walkthrough

Follow this step-by-step sequence to test all major features manually in your browser.

### Test 1: Verify System Health Probes
Open your browser and navigate to:
1. **Liveness Probe**: `http://localhost:8000/v1/health/live`
   - Returns: `{"status":"ok","app":"FortiSales AI","environment":"development"}`
2. **Readiness Probe**: `http://localhost:8000/v1/health/ready`
   - Returns 200 OK with detailed diagnostics:
     - `database`: PostgreSQL connection active and query latency in ms.
     - `redis`: Redis connection status or in-memory fallback indication.
     - `ai_provider`: Active provider and model.
     - `voice_engine`: Active STT and TTS provider configuration.
3. **OpenAPI Interactive Documentation**: `http://localhost:8000/docs`

---

### Test 2: Register Organization & Staff Accounts
Open `http://localhost:8000/` in your browser:
1. Click **"Create Organization / Register"**.
2. Fill out:
   - Organization Name: `Apex AI Solutions`
   - Organization Slug: `apex-ai`
   - Email: `admin@apexai.com`
   - Password: `Password123!`
   - Full Name: `Alice Apex (Admin)`
3. Click **"Register & Launch"**: The application automatically logs you in and directs you to the **Admin Workspace** (`/admin-dashboard`).

---

### Test 3: Test Admin Workspace (`/admin-dashboard`)
1. **Business Profile & Operating Hours**:
   - Inspect the organization profile, contact phone, and timezone.
   - Review operating hours for Monday through Friday (09:00 to 18:00).
2. **Product & Service Catalogue**:
   - Add a new product or service:
     - Name: `Cloud Security Audit`
     - Category: `Cybersecurity`
     - Base Price: `$1,200.00`
     - Pricing Model: `Fixed`
   - Save and verify it appears in the active catalogue.
3. **Employee Provisioning**:
   - Create a staff user:
     - Email: `sales@apexai.com`
     - Password: `Password123!`
     - Full Name: `Bob Miller`
     - Role: `sales_employee`
     - Title: `Senior Account Executive`

---

### Test 4: Test Receptionist Workspace & Calendar (`/receptionist-dashboard`)
Log out and log in as an administrator or receptionist (`admin@apexai.com`):
1. Navigate to `http://localhost:8000/receptionist-dashboard`.
2. **Dashboard Overview**:
   - Observe the stat cards: Calls Today, New Callers, Open Inquiries, New Leads, and **Pending Handoffs**.
3. **Interactive Calendar**:
   - Switch between **Month** and **List** views.
   - Click **"+ Schedule Appointment"**:
     - Customer Phone: `+1 555 123 4567`
     - Date: Choose upcoming Friday
     - Available Time Slot: Select `10:00 - 10:30`
     - Meeting Type: `Sales Discovery Call`
     - Purpose: `Review cloud security architecture`
   - Click **"Schedule"**: The appointment appears immediately on the calendar.
4. **Customer Directory & Inquiries**:
   - Click **Customers**: The caller `+1 555 123 4567` is automatically listed.
   - Click **Inquiries**: Review any open support or escalation tickets.

---

### Test 5: Test Sales Representative Workspace (`/sales-dashboard`)
1. Log out and log in as the sales employee (`sales@apexai.com`).
2. Navigate to `http://localhost:8000/sales-dashboard`:
   - **Cross-Rep Isolation**: Notice that only leads assigned to Bob Miller are visible.
   - **Lead Pipeline**: Move a lead through stages (`new` $\to$ `contacted` $\to$ `qualified` $\to$ `converted`).
   - **Personal Calendar**: View upcoming assigned discovery calls in read-only mode.

---

### Test 6: Test Real-Time AI Voice Console (`/voice-console`)
Open `http://localhost:8000/voice-console`:
1. Click **"Connect & Start Conversation"**:
   - The browser prompts for microphone permissions (click **Allow**).
   - The status indicator turns green: **"Active • Listening"**.
   - The AudioWorklet node (`pcm-processor.js`) begins streaming 16kHz linear PCM audio frames.
2. **Spoken Dialogue Test**:
   - Speak into your microphone: *"What are your business hours on Friday, and what does your cloud security audit cost?"*
   - Observe:
     - VAD visualizer highlights active speech.
     - Deepgram streaming STT displays your transcript in real time.
     - The AI receptionist responds audibly in natural voice (<500ms latency), quoting the exact \$1,200 fixed price from your catalog.
3. **Barge-In (Interruption) Test**:
   - While the AI is speaking its response, interrupt by speaking: *"Wait, can I book an appointment?"*
   - Observe: The AI immediately cuts off speech playback, clears the audio buffer, and transitions back to listening mode.

---

### Test 7: Test Business Knowledge Base & RAG (`/knowledge-console`)
Navigate to `http://localhost:8000/knowledge-console`:
1. **Document Upload**:
   - Prepare a sample text or PDF document (e.g. `company_policy.txt` containing refund or service terms).
   - Select Document Type: `Policy`.
   - Click **"Upload & Process Document"**.
   - Observe: The document is uploaded, chunked via sliding window (500 tokens), embedded into 384 dimensions, and stored in PostgreSQL using `pgvector`.
2. **Semantic Retrieval Inspector**:
   - Type a query into the tester: *"What is your policy on service cancellations?"*
   - Click **"Test Retrieval"**: The top matching vector chunks return with cosine similarity scores $>0.70$.

---

### Test 8: Test Live Human Handoff & Receptionist Takeover
1. In the Voice Console (`/voice-console`), say into your microphone:
   *"I want to speak with a real person right now."*
2. The AI detects the handoff request and politely replies:
   *"I have escalated your call to our human representative team. A specialist has been notified and will take over or follow up with you directly."*
3. In a separate tab, open the **Receptionist Workspace** (`/receptionist-dashboard`):
   - Notice the **🚨 Handoffs** badge increment to `1` in red!
   - Click **"Handoff Queue"**: View the caller phone number, escalation reason, and turns.
   - Click **"Take Over Call"**: The status updates to **"Taken Over"**, recording the receptionist's name and assigning the session.

---

## 5. Running Automated Regression Tests

To run the complete automated test suite verifying all 10 stages:
```powershell
python -m pytest backend/tests -v
```

Expected result:
```
============================= test session starts =============================
...
134 passed, 1 warning in 55.42s
====================== 134 passed, 1 warning in 55.42s ======================
```
