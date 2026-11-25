# FortiSales AI – Phased Implementation Roadmap

This roadmap decomposes the development of FortiSales AI into discrete, independently verifiable implementation stages. Each stage defines clear technical deliverables, testing regimens, acceptance criteria, and risk mitigations, tailored for realistic, high-velocity execution by an individual developer.

```mermaid
flowchart LR
    S0["Stage 0: Architecture (Complete)"] --> S1["Stage 1: Core DB & Environment"]
    S1 --> S2["Stage 2: Auth & Organization APIs"]
    S2 --> S3["Stage 3: Availability & Hours Engine"]
    S3 --> S4["Stage 4: Document RAG & Vector Engine"]
    S4 --> S5["Stage 5: Voice Pipeline (VAD/STT/TTS)"]
    S5 --> S6["Stage 6: Autonomous Agent State Machine"]
    S6 --> S7["Stage 7: Lead Qualification & CRM"]
    S7 --> S8["Stage 8: Appointment Booking Engine"]
    S8 --> S9["Stage 9: Live Takeover & Audio Bridge"]
    S9 --> S10["Stage 10: Async Workers & Summaries"]
    S10 --> S11["Stage 11: React + TS Dashboard"]
    S11 --> S12["Stage 12: Hardening & Load Testing"]
```

---

## Stage 0: Architecture, Requirements & Technical Blueprint (Current)
- **Objective**: Establish foundational system design, database schemas, API specs, and workflow diagrams without writing application code.
- **Deliverables**: Comprehensive technical documentation under `docs/`.
- **Status**: Completed.

---

## Stage 1: Development Environment, Multi-Tenant Database Schema & Migrations
- **Objective**: Bootstrap repository, configure containerized services (PostgreSQL 16 with `pgvector`, Redis 7.2), configure Alembic migrations, and generate core SQLAlchemy 2.0 async models.
- **Scope**:
  - Docker Compose setup for local development.
  - Base configuration, environment variable validation using Pydantic Settings.
  - SQLAlchemy models for Organizations, Users, Departments, Employees, BusinessHours, Holidays, Customers, Calls, Conversations, Messages, Leads, Appointments.
  - Initial Alembic migration script.
- **Files Expected**:
  - `docker-compose.yml`, `.env.example`, `.gitignore`
  - `backend/app/core/config.py`, `backend/app/core/database.py`
  - `backend/app/models/*.py` (declarative models)
  - `backend/alembic/env.py`, `backend/alembic/versions/*.py`
- **Dependencies**: PostgreSQL 16 (`pgvector`), Redis 7.2, Python 3.11+.
- **Testing Strategy**: Automated Pytest suite executing containerized migration up/down cycles and validating UUID generation and foreign key constraints.
- **Acceptance Criteria**: `docker compose up` starts DB and Redis; `alembic upgrade head` applies cleanly with zero SQL errors; test seed script inserts test tenant.
- **Risks & Mitigation**: Vector extension mismatch on local host $\to$ Use official `pgvector/pgvector:pg16` Docker image.

---

## Stage 2: Authentication, Tenant Isolation & User Management REST APIs
- **Objective**: Implement secure multi-tenant authentication, JWT issuance, password hashing, and role-based access control middleware.
- **Scope**:
  - Password hashing with `bcrypt` / `argon2`.
  - JWT token generation (access + refresh token rotation in Redis).
  - FastAPI dependency injection for `get_current_user`, `require_role(role)`.
  - CRUD REST endpoints for `/auth`, `/users`, `/departments`, `/employees`.
- **Files Expected**:
  - `backend/app/core/security.py`, `backend/app/api/deps.py`
  - `backend/app/schemas/auth.py`, `backend/app/schemas/user.py`
  - `backend/app/api/v1/auth.py`, `backend/app/api/v1/users.py`, `backend/app/api/v1/departments.py`
- **Testing Strategy**: Unit tests for password hashing; integration tests verifying RBAC permissions (e.g., Sales Employee cannot delete departments).
- **Acceptance Criteria**: Staff can login, receive JWT, and access tenant-isolated resources; unauthorized requests receive 401/403.
- **Risks & Mitigation**: Tenant leakage $\to$ Unit tests assert that queries from Tenant A cannot retrieve records from Tenant B.

---

## Stage 3: Business Availability, Operating Hours & Schedule Engine
- **Objective**: Build the business logic engine responsible for determining if the business or department is currently open, on holiday, or offline.
- **Scope**:
  - Business hours CRUD (split shifts, weekday schedules).
  - Holiday calendar and special dates management.
  - AI Availability master switch (online/offline/emergency closure).
  - Core evaluation service: `AvailabilityService.is_business_open(org_id, timestamp, department_id)`.
- **Files Expected**:
  - `backend/app/services/availability_service.py`
  - `backend/app/schemas/business_hours.py`, `backend/app/schemas/holidays.py`
  - `backend/app/api/v1/business_hours.py`, `backend/app/api/v1/holidays.py`, `backend/app/api/v1/ai_availability.py`
- **Testing Strategy**: Comprehensive parameter-driven unit tests testing various timezones, leap years, statutory holidays, weekend shifts, and emergency overrides.
- **Acceptance Criteria**: Evaluator accurately reports open/closed/holiday status for any arbitrary datetime across all configured time zones.
- **Risks & Mitigation**: Timezone discrepancies $\to$ Store all operational records in UTC with IANA timezone strings (`org.default_timezone`).

---

## Stage 4: Company Knowledge Base Ingestion & RAG Retrieval Engine
- **Objective**: Implement document upload, text chunking, embedding generation, and cosine similarity vector retrieval using `pgvector`.
- **Scope**:
  - File upload endpoint supporting PDF, Markdown, and TXT.
  - Recursive text splitter with overlap.
  - Vector embedding generator (Sentence Transformers / OpenAI API).
  - Vector similarity search service with tenant and department filtering.
- **Files Expected**:
  - `backend/app/services/rag/ingestion.py`, `backend/app/services/rag/retriever.py`
  - `backend/app/schemas/knowledge.py`
  - `backend/app/api/v1/knowledge.py`
- **Testing Strategy**: Ingest sample company FAQ/pricing document; test semantic query matching against exact and paraphrased queries; benchmark query latency.
- **Acceptance Criteria**: Relevant knowledge chunks returned within $<150\text{ms}$ with cosine similarity score $>0.75$; cross-tenant search returns zero records.
- **Risks & Mitigation**: Ingestion processing stalls API $\to$ Offload embedding calculation of large documents to Celery background task.

---

## Stage 5: Real-Time Audio Streaming Pipeline (VAD, STT & TTS)
- **Objective**: Establish the bi-directional WebSocket audio pipeline integrating Voice Activity Detection, streaming Speech-to-Text, and streaming Text-to-Speech.
- **Scope**:
  - WebSocket gateway endpoint for audio frames (`/v1/calls/stream`).
  - Silero VAD frame accumulator for end-of-speech detection.
  - Streaming STT integration (Deepgram Nova-2 / Whisper).
  - Streaming TTS integration (Cartesia Sonic / ElevenLabs / OpenAI TTS).
  - Barge-in / interruption detection and audio flush.
- **Files Expected**:
  - `backend/app/services/voice/vad.py`
  - `backend/app/services/voice/stt_service.py`
  - `backend/app/services/voice/tts_service.py`
  - `backend/app/services/voice/pipeline.py`
  - `backend/app/api/v1/websocket_call.py`
- **Testing Strategy**: Automated Python audio mock script sending raw PCM 16kHz audio chunks over WebSocket; measure VAD cutoff precision and audio synthesis latency.
- **Acceptance Criteria**: Speech transcribed accurately; silence triggers turnaround within 350ms; TTS stream delivers audible chunks under 300ms.
- **Risks & Mitigation**: High latency on TTS $\to$ Utilize sentence-boundary chunk streaming rather than waiting for full LLM response completion.

---

## Stage 6: Autonomous Sales Agent State Machine & Dynamic Slot Filling
- **Objective**: Develop the conversation state machine that orchestrates system prompts, conversation history in Redis, RAG context injection, and dynamic slot extraction.
- **Scope**:
  - Redis session memory manager (`CallSessionManager`).
  - LLM prompt engineering with strict guardrails and persona definition.
  - Dynamic slot extractor (Caller Name, Budget, Timeline, Service Needed).
  - Real-time sentiment classifier per turn.
- **Files Expected**:
  - `backend/app/services/agent/prompts.py`
  - `backend/app/services/agent/state_machine.py`
  - `backend/app/services/agent/slot_extractor.py`
  - `backend/app/services/agent/session_memory.py`
- **Testing Strategy**: Mock multi-turn conversations testing lead discovery, handling objections, answering RAG questions, and graceful fallback when questions are unknown.
- **Acceptance Criteria**: Agent maintains context across 10+ turns; extracted slots sync to Redis after every turn; prompt token bloat kept under 2,000 tokens.
- **Risks & Mitigation**: LLM hallucination $\to$ Enforce zero-tolerance groundedness prompt with negative constraints ("If not in context, answer that you will connect them with a human specialist").

---

## Stage 7: Intelligent Lead Qualification & CRM Integration
- **Objective**: Implement real-time BANT lead scoring, customer profile creation/updating, and CRM opportunity persistence.
- **Scope**:
  - BANT scoring algorithm (0–100 scale, hot/warm/cold classification).
  - Customer contact upserting based on caller phone number.
  - Lead entity creation and sales representative assignment.
  - Follow-up task creation.
- **Files Expected**:
  - `backend/app/services/crm/qualification_service.py`
  - `backend/app/services/crm/lead_service.py`
  - `backend/app/api/v1/leads.py`, `backend/app/api/v1/customers.py`
- **Testing Strategy**: Unit tests evaluating diverse simulated customer conversations with varying budgets, timelines, and authority levels; assert correct tier and score assignment.
- **Acceptance Criteria**: High-intent callers classified as `hot` and assigned to reps; lead and task records inserted into database upon call conclusion.
- **Risks & Mitigation**: Over-scoring unqualified leads $\to$ Require explicit budget and authority confirmation before exceeding 70-point threshold.

---

## Stage 8: Collision-Safe Appointment Booking & Calendar Integration
- **Objective**: Build the appointment booking engine capable of querying open slots and locking them atomically without double-booking.
- **Scope**:
  - Slot discovery service factoring in business hours, holidays, and existing employee bookings.
  - Distributed Redis locking mechanism (`lock:appointment:{employee_id}:{slot}`).
  - PostgreSQL exclusion constraint enforcement on appointment ranges.
  - Booking confirmation email/calendar invite generator.
- **Files Expected**:
  - `backend/app/services/scheduling/appointment_service.py`
  - `backend/app/services/scheduling/calendar_sync.py`
  - `backend/app/schemas/appointment.py`
  - `backend/app/api/v1/appointments.py`
- **Testing Strategy**: Concurrent race-condition test: 10 parallel requests attempting to book the exact same 30-minute employee slot; assert exactly 1 succeeds and 9 fail with 409 Conflict.
- **Acceptance Criteria**: Open slots accurately calculated; zero double-bookings possible; appointments properly linked to calls and customers.
- **Risks & Mitigation**: Calendar out of sync $\to$ Implement idempotent synchronization with external Google Calendar / Outlook APIs.

---

## Stage 9: Live Call Monitoring Hub & Human Receptionist Takeover
- **Objective**: Build the real-time staff monitoring WebSocket hub allowing human receptionists to watch live transcripts and instantly take over active calls.
- **Scope**:
  - Live monitor WebSocket router (`/v1/monitor/live`).
  - Redis Pub/Sub bridge broadcasting live utterance transcripts and sentiment.
  - Takeover command handler: mutes AI, connects caller audio to staff WebRTC/SIP stream.
- **Files Expected**:
  - `backend/app/services/telephony/takeover_service.py`
  - `backend/app/api/v1/websocket_monitor.py`
- **Testing Strategy**: Simulate active AI call session; connect staff monitor WebSocket; assert transcript packets arrive in real time (<100ms); trigger takeover command and verify AI audio stream ceases immediately.
- **Acceptance Criteria**: Staff dashboard receives real-time transcript streaming; takeover latency is under 500ms without dropping the caller.
- **Risks & Mitigation**: Audio bridge complexity $\to$ Use a standardized WebRTC audio track switch or Twilio conference redirection primitive.

---

## Stage 10: Asynchronous Task Workers, Automated Summarization & Analytics
- **Objective**: Configure Celery and Redis to handle post-call processing, executive call summarization, PII redaction, and aggregate business analytics.
- **Scope**:
  - Celery worker application configuration and task definitions.
  - LLM call summarization pipeline (Key Points, Objections, Next Steps).
  - Audio recording file archival to S3 / local storage.
  - Analytical aggregation queries (call volume, sentiment trends, average handle time).
- **Files Expected**:
  - `backend/app/tasks/celery_app.py`, `backend/app/tasks/call_tasks.py`
  - `backend/app/services/analytics/reporting_service.py`
  - `backend/app/api/v1/analytics.py`
- **Testing Strategy**: End-to-end integration test from call hang-up event to Celery task execution, verifying database persistence of `call_summaries` within 5 seconds.
- **Acceptance Criteria**: Post-call tasks run asynchronously without blocking API threads; structured summary and analytics KPIs generated accurately.
- **Risks & Mitigation**: Celery worker failure $\to$ Configure task retry with exponential backoff and dead-letter queue.

---

## Stage 11: React + TypeScript Staff & Admin Dashboard (UI/UX)
- **Objective**: Develop the responsive Single Page Application (SPA) for business owners, administrators, receptionists, and sales employees.
- **Scope**:
  - Clean modular UI with Tailwind CSS / Shadcn UI components.
  - Authentication flow, protected routes, and role-based views.
  - Live Call Monitoring view with real-time transcript stream and "Take Over Call" button.
  - Business hours, holiday schedule, and AI availability management screens.
  - Knowledge base document upload and status view.
  - Leads table, customer details, and appointment calendar view.
- **Files Expected**:
  - `frontend/src/App.tsx`, `frontend/src/router.tsx`
  - `frontend/src/features/auth/*`
  - `frontend/src/features/calls/LiveCallMonitor.tsx`
  - `frontend/src/features/schedules/BusinessHoursManager.tsx`
  - `frontend/src/features/knowledge/KnowledgeBaseManager.tsx`
  - `frontend/src/features/crm/LeadsDashboard.tsx`
- **Testing Strategy**: Component unit tests with Vitest / React Testing Library; end-to-end user journey tests with Playwright.
- **Acceptance Criteria**: Fast page load (<1s); WebSockets auto-reconnect cleanly on network drop; intuitive scheduling and takeover workflows.
- **Risks & Mitigation**: Audio latency in browser $\to$ Use standard HTML5 Web Audio API / AudioContext for playback.

---

## Stage 12: Production Hardening, Load Testing & Docker Deployment
- **Objective**: Finalize containerization, perform stress testing, conduct security audits, and prepare deployment infrastructure.
- **Scope**:
  - Production multi-stage `Dockerfile` (optimized for size and caching).
  - Production `docker-compose.prod.yml` with Nginx reverse proxy and SSL.
  - Load testing suite with Locust (simulating 50+ concurrent audio streams and 500 REST requests/sec).
  - OWASP Top 10 security audit, CORS policy hardening, rate-limiting verification.
- **Files Expected**:
  - `backend/Dockerfile`, `frontend/Dockerfile`, `nginx/nginx.conf`
  - `tests/load/locustfile.py`
  - `deploy/docker-compose.prod.yml`
- **Testing Strategy**: Run Locust load tests; monitor CPU, RAM, Redis connection pool, and PostgreSQL query execution times under sustained concurrent load.
- **Acceptance Criteria**: System maintains sub-second voice turnaround under 50 concurrent calls with zero dropped sessions; passes automated security scan with zero critical vulnerabilities.
- **Risks & Mitigation**: LLM API budget blowout during load test $\to$ Use mock STT/LLM/TTS services during synthetic load testing.
