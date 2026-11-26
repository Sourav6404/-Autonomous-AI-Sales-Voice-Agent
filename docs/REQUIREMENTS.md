# FortiSales AI – System Requirements Specification (SRS)

## 1. Executive Summary & Business Objective

**FortiSales AI** is an enterprise-grade autonomous AI sales voice agent designed to function as an intelligent virtual receptionist and frontline sales development representative (SDR). The system conducts natural, bidirectional, low-latency voice interactions with incoming callers, answers corporate and product questions accurately using Retrieval-Augmented Generation (RAG), qualifies leads based on configurable criteria, books appointments directly into CRM and calendar schedules, and coordinates intelligent call routing and human receptionist handoffs.

The system is built for multi-tenant scalability, supporting registered users across multiple organizations. Each concurrent call operates in a strictly isolated execution context with independent conversation state, short-term working memory, real-time transcription, and customer records.

---

## 2. Functional Requirements (FR)

### FR-1: Real-Time Bidirectional Voice Interaction (Implemented - Stage 4)
- **FR-1.1**: The system ingests incoming audio streams over full-duplex WebSockets using raw linear PCM16 format (16kHz mono, 20ms frames = 640 bytes).
- **FR-1.2**: Inbound audio is processed via streaming Speech-to-Text (STT) powered by Deepgram Nova-2 with Silero Voice Activity Detection (VAD) to detect end-of-speech and caller interruptions.
- **FR-1.3**: The response generation pipeline converts LLM text to speech using streaming Text-to-Speech (TTS via Cartesia Sonic or ElevenLabs) with sentence-boundary chunk streaming (`SentenceAggregator`) and immediately streams audio frames to the client.
- **FR-1.4**: Target voice loop turnaround latency (caller finishes speaking to first audio packet returned) operates under **500ms**.
- **FR-1.5**: The system supports barge-in (interruption handling): if the caller speaks while the AI is outputting TTS audio, Silero VAD fires a cancellation event within 80ms, terminating active TTS synthesis, clearing audio buffers, and resetting the conversational turn.
- **FR-1.6**: Browser microphone capture and playback are driven by a dedicated Web Audio API `AudioWorkletNode` (`pcm-processor.js`), running on a separate audio rendering thread.

### FR-2: Contextual Conversation Memory & State Management (Implemented - Stage 3)
- **FR-2.1**: Every call session maintains an isolated context in PostgreSQL and working state with a unique `session_id`, `conversation_id`, and `call_id`.
- **FR-2.2**: The conversation context retains dynamic slot state: caller identity, customer intent, qualification parameters, sentiment trajectory, and referenced entities.
- **FR-2.3**: Memory compaction and rolling window summarization (`ContextManager`) bound prompt tokens during extended calls (>15 turns).
- **FR-2.4**: Upon call conclusion, full conversation turns, raw transcript messages, and structured summaries are persisted to PostgreSQL.

### FR-3: Multilingual Voice Communication (Implemented - Stage 3 & 4)
- **FR-3.1**: The system supports caller language configuration (default English `en`), respecting language preferences throughout STT and TTS synthesis.
- **FR-3.2**: Matched STT and natural localized TTS models ensure clear pronunciation and conversational cadence.

### FR-4: RAG-Based Knowledge Retrieval (Implemented - Stage 5)
- **FR-4.1**: Organizations can upload documents (PDF, DOCX, TXT) and manage FAQs through the Knowledge Base Console (`/knowledge-console`).
- **FR-4.2**: The ingestion pipeline cleans, chunks (500 tokens, 100 token overlap), and embeds documents into 384-dimensional dense vectors stored in PostgreSQL using `pgvector`.
- **FR-4.3**: During calls, caller queries trigger semantic cosine similarity search (`<=>`) combined with strict `org_id` tenant filtering.
- **FR-4.4**: Groundedness guardrails instruct the LLM to strictly decline unverified questions and avoid hallucinations, offering a callback or human transfer instead.
- **FR-4.5**: **Structured Pricing Precedence**: Confirmed prices in the Product/Service catalog **always** override vector text chunks.

### FR-5: Intelligent Lead Qualification & Scoring (Implemented - Stage 6)
- **FR-5.1**: The AI receptionist conversationally elicits qualification parameters (Budget, Need, Timeline, Authority).
- **FR-5.2**: The system computes a dynamic lead score (0–100) and qualification tier (`cold`, `warm`, `hot`).
- **FR-5.3**: Qualified leads automatically create or update customer records, lead entities, and structured follow-up tasks in the CRM.

### FR-6: Real-Time Sentiment & Intent Analysis (Implemented - Stage 3 & 6)
- **FR-6.1**: Every customer utterance is classified for sentiment (`positive`, `neutral`, `negative`, `frustrated`) and confidence score.
- **FR-6.2**: Sustained frustration or human requests trigger immediate human handoff protocols.

### FR-7: Automated Appointment Booking (Implemented - Stage 7)
- **FR-7.1**: The AI receptionist parses caller meeting requests and checks calendar availability against business operating hours, statutory holidays, special schedules, and employee availability.
- **FR-7.2**: The system proposes open slots, collects explicit confirmation (`customer_confirmed=True`), and books the meeting.
- **FR-7.3**: **Collision-Safe Scheduling**: Protected against race conditions and double-booking at the database engine level via PostgreSQL GiST exclusion constraints (`btree_gist` + `tstzrange`).

### FR-8: Business Availability & Schedule Management (Implemented - Stage 2)
- **FR-8.1**: Configurable standard operating hours per weekday (e.g., Monday–Friday 09:00–18:00).
- **FR-8.2**: Holiday calendar configuration (statutory public holidays and custom corporate closures).
- **FR-8.3**: Special schedule overrides with customized hours.
- **FR-8.4**: Centralized `AvailabilityService` evaluating precedence: Emergency Closure > Holiday > Special Schedule > Business Hours > Default Closed.

### FR-9: Departmental Routing & Human Receptionist Takeover (Implemented - Stage 8)
- **FR-9.1**: Real-time intent detection for phrases like *"speak to person"*, *"connect to sales"*, *"human assistance"*, *"transfer call"*.
- **FR-9.2**: `request_human_handoff` tool updates Call and Conversation to `handed_off`, logs an urgent `Inquiry` escalation ticket, and updates the `Lead` tier to `hot`.
- **FR-9.3**: **Live Handoff Queue**: Receptionist workspace displays pending handoffs in real time with an alert badge and one-click **"Take Over Call"** action (`POST /api/v1/conversations/{id}/takeover`).
- **FR-9.4**: **Resilient AI Fallback**: Upstream model timeouts or provider errors trigger a graceful fallback turn offering human follow-up without dropping the call.

### FR-10: Call Post-Processing & Role-Based Workspaces (Implemented - Stage 6 & 7)
- **FR-10.1**: Automated generation of structured call summaries and analytics.
- **FR-10.2**: Three dedicated workspaces built on a unified White-and-Violet design system:
  - *Admin Workspace* (`/admin-dashboard`): Org profile, hours, holidays, catalog, employees, metrics.
  - *Receptionist Workspace* (`/receptionist-dashboard`): Calendar month/list view, bookings, customer directory, inquiries, handoff queue.
  - *Sales Rep Workspace* (`/sales-dashboard`): Personal assigned leads, pipeline status progression, read-only schedule.

---

## 3. User Roles & RBAC Matrix

The system enforces strict Role-Based Access Control (RBAC) across organizational tenants:

| Feature / Action | Super Admin / Owner | Administrator | Receptionist | Sales Employee | AI Receptionist (System) |
|---|---|---|---|---|---|
| **Manage Organizations & Settings** | ✅ Full | ✅ Org scope | ❌ None | ❌ None | ❌ None |
| **Manage Organization Users & Roles** | ✅ Full | ✅ Org scope | ❌ None | ❌ None | ❌ None |
| **Configure Business Hours & Holidays** | ✅ Full | ✅ Full | ⚠️ View only | ❌ None | ⚠️ Read for routing |
| **Upload / Manage Knowledge Base & FAQs** | ✅ Full | ✅ Full | ⚠️ View only | ⚠️ View only | ⚠️ Semantic search |
| **Live Call Monitor & Human Takeover** | ✅ Full | ✅ Full | ✅ Full Queue | ❌ None | ⚠️ Escalates to human |
| **View All Organization Leads & CRM** | ✅ Full | ✅ Full | ⚠️ Read basic | ⚠️ Assigned Only | ⚠️ Auto-creates leads |
| **Manage Calendar & Book Appointments** | ✅ Full | ✅ Full | ✅ Full Calendar | ⚠️ Read-only own | ⚠️ Collision-safe book |
| **View System Health & Diagnostic Probes** | ✅ Full | ✅ Full | ⚠️ View status | ⚠️ View status | ⚠️ Emits metrics |

---

## 4. Non-Functional Requirements (NFR)

### NFR-1: Latency & Real-Time Performance
- **Speech-to-Text Latency**: Streaming partial transcription within **150ms**; final utterance boundary detection within **250ms**.
- **LLM Time-to-First-Token (TTFT)**: Under **400ms** using streaming endpoints.
- **Text-to-Speech Streaming Latency**: First synthesized audio chunk returned within **200ms** of receiving initial sentence tokens.
- **Total Acoustic Turnaround Latency**: User silence to AI voice start $\le$ **500ms**.

### NFR-2: Concurrency & System Capacity
- Multi-instance stateless design capable of concurrent voice sessions without session cross-talk.
- Strict isolation of in-memory voice tickets using single-use Redis tokens with automatic local development fallback.

### NFR-3: High Availability & Reliability
- Health probes (`/v1/health/live`, `/v1/health/ready`) diagnosing PostgreSQL latency, Redis status, AI provider status, and voice engine configuration.
- Resilient AI model failure fallback preventing unhandled exceptions from terminating user calls.

### NFR-4: Security & Compliance
- Full tenant isolation at database and vector index level via `TenantContext` (`contextvars.ContextVar`).
- Scrypt RFC 7914 password hashing with unique salts.
- Cryptographically signed JWT access tokens and single-use refresh token rotation.
- Ephemeral 256-bit single-use voice tickets redeemed atomically via Redis `GETDEL` (close code `4401` on invalid/expired ticket, `4403` on unauthorized Origin).

---

## 5. Implementation Status & Scope Boundaries

### Completed Stages (Stages 1–10)
- **Stage 1**: Backend and Database Foundation (PostgreSQL 16, Asyncpg, Alembic, Base models).
- **Stage 2**: Authentication, RBAC, Business Availability Engine.
- **Stage 3**: AI Conversation Engine, Provider Abstraction, Tool Registry.
- **Stage 4**: Real-Time Voice Engine, AudioWorklet, STT, TTS, VAD, Barge-in.
- **Stage 5**: Business Knowledge Base, pgvector RAG, Catalog Pricing Precedence.
- **Stage 6**: CRM, Lead Scoring, Role-Based Frontend Workspaces (Admin, Receptionist, Sales).
- **Stage 7**: Appointment and Calendar Management, GiST Collision Safety.
- **Stage 8**: Basic Human Handoff, Live Receptionist Queue, AI Model Outage Fallback.
- **Stage 9**: Local Development Setup, System Health Diagnostics.
- **Stage 10**: Complete 134-Test Regression Suite, Handover & Presentation Documentation.

### Deferred / Out-of-Scope Items
- **Advanced Outbound Notification Networks**: Direct Twilio SMS/WhatsApp dispatching, mobile push notifications.
- **Public Cloud Hosting**: AWS ECS/EKS clusters, Kubernetes Helm charts, Terraform infrastructure-as-code, Docker Swarm.
