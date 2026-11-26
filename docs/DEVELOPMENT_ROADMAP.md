# FortiSales AI — Phased Implementation Roadmap & Actual Status

This roadmap outlines the complete development trajectory of FortiSales AI from architectural conception to final verification. All ten core engineering stages (Stages 1 through 10) are **100% complete**, verified by **134 automated unit, integration, and concurrency tests** running against local PostgreSQL 16.

```mermaid
flowchart LR
    S1["Stage 1: Core DB & Foundation (Done)"] --> S2["Stage 2: Auth & Org Config (Done)"]
    S2 --> S3["Stage 3: AI Conversation Engine (Done)"]
    S3 --> S4["Stage 4: Real-Time Voice Engine (Done)"]
    S4 --> S5["Stage 5: Knowledge Base & RAG (Done)"]
    S5 --> S6["Stage 6: CRM & Role Workspaces (Done)"]
    S6 --> S7["Stage 7: Appointment Engine (Done)"]
    S7 --> S8["Stage 8: Human Handoff & Fallback (Done)"]
    S8 --> S9["Stage 9: Local Reliability & Setup (Done)"]
    S9 --> S10["Stage 10: Final Testing & Docs (Done)"]
```

---

## Stage 1: Backend and Database Foundation
- **Objective**: Bootstrap repository, configure asynchronous PostgreSQL 16 with `pgvector` and `uuid-ossp`, configure Alembic migrations, and generate core SQLAlchemy 2.0 async models.
- **Scope Delivered**:
  - Pydantic Settings configuration (`backend/app/core/config.py`).
  - Asynchronous SQLAlchemy engine with Asyncpg and synchronous Psycopg2 driver for Alembic (`backend/app/core/database.py`).
  - Multi-tenant base models with `TenantMixin` and `GUID` type (`backend/app/models/base.py`).
  - Core models: `Organization`, `User`, `Department`, `Employee`, `Customer`, `Call`, `Conversation`, `Message`, `AuditLog`.
  - Initial Alembic migration `0001_initial_schema.py`.
- **Status**: **Completed** (Verified with automated migration and schema tests).

---

## Stage 2: Authentication and Business Configuration
- **Objective**: Implement secure multi-tenant authentication, JWT issuance, password hashing, role-based access control, and business operating schedule evaluation.
- **Scope Delivered**:
  - Scrypt RFC 7914 password hashing with unique salts (`backend/app/core/security.py`).
  - JWT access and refresh token lifecycle, token blacklist, single-use refresh token rotation.
  - Role-based access control hierarchy (`owner` > `admin` > `receptionist` > `sales_employee`).
  - Business operating hours, statutory holiday closures, special schedules, and AI availability precedence engine (`backend/app/services/availability_service.py`).
  - API endpoints for `/auth`, `/organizations`, `/business-hours`, `/holidays`, `/special-schedules`, `/ai-availability`.
  - Migration `0002_stage2_business_and_roles.py`.
- **Status**: **Completed** (53 passing tests).

---

## Stage 3: AI Conversation Engine
- **Objective**: Establish provider-independent conversational intelligence layer capable of dynamic context assembly, tool execution, session state management, and intent extraction.
- **Scope Delivered**:
  - Provider-agnostic LLM interface (`BaseLLMProvider`) supporting OpenAI and Google Gemini via async HTTP, plus deterministic mock providers.
  - Backend-controlled `ToolRegistry` with Pydantic argument validation, authorization, and tenant isolation.
  - Initial tools: `get_business_information`, `get_business_hours`, `get_ai_availability`, `request_human_handoff`.
  - Multi-turn conversation orchestrator (`ConversationOrchestrator`) coordinating prompts, context loading, tool execution loops (bounded at 3 loops), DB persistence, and intent extraction.
  - Progressive memory and context pruning (`ContextManager`) with sliding history windows and token bounding.
  - Dynamic prompt management (`PromptManager`) injecting business profile, operating status, and anti-hallucination guardrails.
  - Conversation REST APIs (`/conversations`). Migration `0003_stage3_conversation_engine.py`.
- **Status**: **Completed** (67 passing tests).

---

## Stage 4: Real-Time Voice Engine
- **Objective**: Develop the real-time bidirectional voice engine enabling low-latency browser-based voice receptionist interactions.
- **Scope Delivered**:
  - Cryptographically secure single-use ticket mechanism (`POST /api/v1/voice/tickets`) with SHA-256 hashed storage, 30s TTL, and atomic Redis `GETDEL` redemption (close code `4401` on invalid/expired ticket, `4403` on unauthorized Origin).
  - Bidirectional WebSocket streaming gateway (`/api/v1/voice/stream`) with strict `TenantContext` lifecycle binding.
  - Linear PCM16 (16kHz mono, 20ms = 640-byte frames) protocol with bounded ring buffer and 2-byte sample alignment.
  - Silero VAD frame accumulator for end-of-speech detection.
  - Streaming STT integration using Deepgram Nova-2 with mock fallback.
  - Streaming TTS integration (Cartesia Sonic / ElevenLabs) with sentence-boundary chunk streaming (`SentenceAggregator`).
  - Barge-in interruption handling: caller speech during AI playback instantly fires cancellation event, terminates TTS, and resets conversational turn.
  - Browser AudioWorklet node (`pcm-processor.js`) and Receptionist Voice Console (`/voice-console`).
- **Status**: **Completed** (90 passing tests).

---

## Stage 5: Business Knowledge Base and RAG
- **Objective**: Implement document ingestion, text chunking, embedding generation, and cosine similarity vector retrieval using `pgvector`.
- **Scope Delivered**:
  - Document ingestion supporting PDF, DOCX, and TXT files (`backend/app/services/rag/ingestion.py`).
  - Sliding-window text chunker (500 tokens with 100 token overlap) preserving paragraph integrity.
  - Vector storage in `knowledge_chunks` using 384-dimensional pgvector cosine distance (`<=>`).
  - `KnowledgeRetriever` with metadata filtering and strict anti-hallucination guardrails.
  - Structured Product Catalog and pricing precedence: confirmed catalog prices **always** override vector text chunks.
  - Knowledge Base Console (`/knowledge-console`) for document upload, FAQ CRUD, and semantic retrieval inspection.
  - Migration `0004_stage5_knowledge_base.py`.
- **Status**: **Completed** (113 passing tests).

---

## Stage 6: CRM and Role-Based Frontend
- **Objective**: Build CRM lead management, customer directory, inquiry tracking, and three distinct role-based workspaces using a unified White-and-Violet design system.
- **Scope Delivered**:
  - Relational entities: `Customer`, `Lead`, `Inquiry`, `FollowUpTask`, `Employee`.
  - Automatic customer profile creation and inquiry ticket creation from inbound calls.
  - Automatic lead generation upon call completion with qualification scoring (0–100) and tiering (`cold`, `warm`, `hot`).
  - Cross-rep isolation: sales employees (`sales_employee` role) can only access their own assigned leads, inquiries, and schedules.
  - Role-based workspaces:
    - *Admin Workspace* (`/admin-dashboard`): Org configuration, business hours, services catalog, employee provisioning, org-wide metrics.
    - *Receptionist Workspace* (`/receptionist-dashboard`): Call activity, customer directory, inquiries, leads, and calendar.
    - *Sales Rep Workspace* (`/sales-dashboard`): Personal leads pipeline, stage progression (`new` $\to$ `contacted` $\to$ `qualified` $\to$ `converted`), tasks.
  - Migration `0005_stage6_crm.py`.
- **Status**: **Completed** (121 passing tests).

---

## Stage 7: Appointment and Calendar Management
- **Objective**: Build conflict-free appointment scheduling engine protected against race conditions via PostgreSQL GiST exclusion constraints.
- **Scope Delivered**:
  - Availability evaluation factoring in emergency closures, holidays, special schedules, weekday operating hours, staff booking availability, and overlapping appointments (`backend/app/services/appointments/availability.py`).
  - Concurrency safety: PostgreSQL GiST exclusion constraint (`btree_gist` + `tstzrange`) on `appointments` table preventing overlapping bookings at the storage engine level.
  - Booking service with immediate revalidation inside async transactions before commit.
  - 6 AI Receptionist tools: `check_appointment_availability`, `get_available_appointment_slots`, `book_appointment` (enforces `customer_confirmed=True`), `get_customer_appointments`, `reschedule_appointment`, `cancel_appointment`.
  - Receptionist interactive Month & List calendar UI with booking, rescheduling, and cancellation modals.
  - Migration `0006_stage7_appointments.py`.
- **Status**: **Completed** (129 passing tests).

---

## Stage 8: Basic Human Handoff and AI Fallback
- **Objective**: Implement real-time customer intent extraction for human requests, live handoff queue in the receptionist workspace, staff takeover API, and resilient AI model failure fallback.
- **Scope Delivered**:
  - Heuristic intent extraction detecting phrases like *"speak to person"*, *"connect to sales"*, *"human assistance"*, *"transfer call"*, *"talk to human"*.
  - `request_human_handoff` tool: updates `Conversation.status = "handed_off"`, `Call.status = "handed_off"`, sets `Call.outcome = "handed_off"`, creates an urgent `Inquiry` escalation ticket, and updates `Lead.qualification_tier = "hot"`.
  - Live Handoff Queue in Receptionist workspace (`/receptionist-dashboard`) with pending alert badge and one-click staff takeover (`POST /api/v1/conversations/{id}/takeover`).
  - Resilient AI Fallback in `ConversationOrchestrator`: catches upstream provider timeouts or outages, safely records customer turn, transitions session to `handed_off`, and returns an apologetic fallback message offering human follow-up without dropping the call.
- **Status**: **Completed** (134 passing tests).

---

## Stage 9: Local Environment Setup and Reliability
- **Objective**: Harden local developer setup, enhance system diagnostics, and ensure zero-external-cost local execution.
- **Scope Delivered**:
  - Enhanced `/v1/health/ready` probe diagnosing PostgreSQL latency, Redis status (with automatic local dev fallback), AI provider status, and voice engine configuration.
  - Comprehensive local setup and troubleshooting manual (`docs/LOCAL_SETUP_AND_TROUBLESHOOTING.md`).
  - Annotated `.env.example` template with clear defaults and mock provider instructions.
  - Zero-cost offline development mode using deterministic mock providers.
- **Status**: **Completed** (134 passing tests).

---

## Stage 10: Final Testing and Presentation Preparation
- **Objective**: Complete end-to-end regression validation and prepare comprehensive documentation for technical reviews, investor presentations, and code examinations.
- **Scope Delivered**:
  - 134 automated unit, integration, and concurrency tests passing with 100% pass rate.
  - Comprehensive presentation and technical interview guide (`docs/PRESENTATION_PREPARATION.md`).
  - One-page project overview (`docs/PROJECT_OVERVIEW.md`).
  - Local testing guide with exact PowerShell instructions (`docs/LOCAL_TESTING_GUIDE.md`).
- **Status**: **Completed** (134/134 passing tests).

---

## Deferred / Future Scope Roadmap
The following items are intentionally outside the current local MVP scope and scheduled for future enterprise milestones:
1. **Advanced Outbound Notification Networks**: Direct Twilio SMS/WhatsApp dispatching, mobile push notifications, and external SIP carrier trunking.
2. **Cloud Container Orchestration**: AWS ECS/EKS clusters, Kubernetes Helm charts, Terraform infrastructure-as-code, and distributed multi-region replication.
3. **Continuous Integration / Continuous Deployment (CI/CD)**: GitHub Actions pipelines for automated cloud deployment.
