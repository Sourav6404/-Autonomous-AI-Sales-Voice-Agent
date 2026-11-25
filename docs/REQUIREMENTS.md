# FortiSales AI – System Requirements Specification (SRS)

## 1. Executive Summary & Business Objective

**FortiSales AI** is an enterprise-grade autonomous AI sales voice agent designed to function as an intelligent virtual receptionist and frontline sales development representative (SDR). The system conducts natural, bidirectional, low-latency voice interactions with incoming callers, answers corporate and product questions accurately using Retrieval-Augmented Generation (RAG), qualifies leads based on configurable criteria, books appointments directly into CRM and calendar schedules, and coordinates intelligent call routing and human receptionist handoffs.

The system is built for multi-tenant scalability, supporting up to 100,000 registered users across multiple organizations. Each concurrent call operates in a strictly isolated execution context with independent conversation state, short-term working memory, real-time transcription, and customer records.

---

## 2. Functional Requirements (FR)

### FR-1: Real-Time Bidirectional Voice Interaction
- **FR-1.1**: The system shall ingest incoming audio streams over full-duplex WebSockets (PCM / WebM / Opus formats at 16kHz or 24kHz).
- **FR-1.2**: Inbound audio shall be processed via real-time Speech-to-Text (STT) with Voice Activity Detection (VAD) to detect end-of-speech and caller interruptions.
- **FR-1.3**: The response generation pipeline shall convert LLM text tokens to audible speech using streaming Text-to-Speech (TTS) and immediately stream audio chunks to the client.
- **FR-1.4**: Target voice loop turnaround latency (caller finishes speaking to first audio packet returned) shall remain under **800ms** (optimal target <600ms).
- **FR-1.5**: The system shall support barge-in (interruption handling): if the caller speaks while the AI is outputting TTS audio, the system immediately cuts audio playback, flushes output buffers, and transitions to listening mode.

### FR-2: Contextual Conversation Memory & State Management
- **FR-2.1**: Every call session must maintain an isolated working memory buffer in Redis with a unique `session_id` and `call_id`.
- **FR-2.2**: The conversation context must retain dynamic slot state: caller identity, customer intent, qualification answers, sentiment trajectory, and referenced entities.
- **FR-2.3**: Memory compaction and rolling window summarization must be supported to prevent prompt token bloat during extended calls (>15 turns).
- **FR-2.4**: Upon call conclusion, the full conversation turns, raw transcript, and compact summary must be persisted to the relational database.

### FR-3: Multilingual Voice Communication
- **FR-3.1**: The system shall detect caller language automatically within the first 1–2 utterances.
- **FR-3.2**: The system shall support primary business languages (e.g., English, Spanish, French, German, Hindi) with matched STT, LLM reasoning, and natural localized TTS voice models.
- **FR-3.3**: The AI must maintain linguistic consistency across the call unless explicitly requested by the customer to switch languages.

### FR-4: RAG-Based Knowledge Retrieval
- **FR-4.1**: Organizations can upload documents (PDF, DOCX, TXT, CSV, Markdown, FAQ lists) into a departmental or organization-wide knowledge base.
- **FR-4.2**: The ingestion pipeline shall chunk, clean, and embed documents using dense vector embeddings stored in a vector database.
- **FR-4.3**: During calls, caller queries trigger hybrid semantic search (vector similarity + metadata filtering on department/org) to inject verified facts into the prompt context.
- **FR-4.4**: Groundedness guardrails must instruct the LLM to strictly decline unverified questions and avoid hallucinations, offering a callback or human transfer instead.

### FR-5: Intelligent Lead Qualification & Scoring
- **FR-5.1**: The AI receptionist shall conversationally elicit qualification parameters based on frameworks such as BANT (Budget, Authority, Need, Timeline) or custom business scorecards.
- **FR-5.2**: The system shall compute a dynamic lead score (0–100) and qualification tier (`Cold`, `Warm`, `Hot`, `Unqualified`).
- **FR-5.3**: Qualified leads must automatically generate or update customer records, lead entities, and structured follow-up tasks in the CRM.

### FR-6: Real-Time Sentiment & Intent Analysis
- **FR-6.1**: Every customer utterance must be classified for sentiment (`Positive`, `Neutral`, `Negative`, `Frustrated`, `Angry`) and confidence score.
- **FR-6.2**: Sustained frustration or negative sentiment triggers de-escalation protocols or escalates immediately to human handoff.

### FR-7: Automated Appointment Booking
- **FR-7.1**: The AI receptionist shall parse caller meeting requests, check calendar availability against business operating hours, holidays, and employee schedules.
- **FR-7.2**: The system will propose open slots, collect confirmation, and book the meeting with collision-safe atomic database locking.
- **FR-7.3**: Booking confirmation notifications (email/SMS payload dispatch) and calendar invite tasks shall be queued immediately.

### FR-8: Business Availability & Schedule Management
- **FR-8.1**: Configurable standard operating hours per weekday (e.g., Monday–Friday 09:00–18:00, Saturday 10:00–14:00, Sunday Closed).
- **FR-8.2**: Support split shifts (e.g., 09:00–13:00 and 14:00–18:00) and department-specific schedules.
- **FR-8.3**: Holiday calendar configuration (statutory public holidays and custom corporate closures) with recurring or single-year rules.
- **FR-8.4**: Special working days (e.g., working weekend days with customized hours).
- **FR-8.5**: Temporary emergency office closures with custom voicemail/out-of-office automated scripts.
- **FR-8.6**: Master toggle to manually switch the AI receptionist `Online`, `Offline`, or `Call Forwarding Only`.
- **FR-8.7**: Scheduled automatic open/close transitions aligned with time zones.

### FR-9: Departmental Routing & Human Receptionist Takeover
- **FR-9.1**: Support call routing based on intent (e.g., Sales, Support, Billing, General Inquiries).
- **FR-9.2**: Human takeover mechanism: A human receptionist or sales agent can view live call transcripts via a real-time dashboard and click "Take Over Call".
- **FR-9.3**: Seamless handover protocol: The AI informs the caller ("Transferring you to an agent now..."), pauses AI synthesis, and bridges the audio stream to the human agent's WebRTC or SIP extension along with full real-time context and transcript.
- **FR-9.4**: Fallback handling if no human agent answers within a timeout (e.g., 20 seconds): AI resumes conversation, offers to record a message, or books a callback.

### FR-10: Call Post-Processing, Summarization & Analytics
- **FR-10.1**: Automated generation of structured call summaries (Call Reason, Key Points Discussed, Action Items, Customer Objections, Next Steps).
- **FR-10.2**: Storage of time-stamped speaker-separated audio recordings and verbatim transcripts.
- **FR-10.3**: Executive dashboards displaying call volume metrics, conversion rates, average handle times (AHT), lead qualification distributions, and customer sentiment trends.

---

## 3. User Roles & RBAC Matrix

The system enforces strict Role-Based Access Control (RBAC) across organizational tenants:

| Feature / Action | Super Admin / Owner | Administrator | Receptionist | Sales Employee | AI Receptionist (System) |
|---|---|---|---|---|---|
| **Manage Organizations & Billing** | ✅ Full | ❌ None | ❌ None | ❌ None | ❌ None |
| **Manage Organization Users & Roles** | ✅ Full | ✅ Org scope | ❌ None | ❌ None | ❌ None |
| **Configure Business Hours & Holidays** | ✅ Full | ✅ Full | ⚠️ View only | ❌ None | ⚠️ Read for routing |
| **AI Receptionist Master On/Off Toggle** | ✅ Full | ✅ Full | ✅ Full | ❌ None | ❌ None |
| **Upload / Manage RAG Knowledge Base** | ✅ Full | ✅ Full | ⚠️ View only | ⚠️ View only | ⚠️ Read semantic search |
| **Live Call Monitor & Intercept (Takeover)** | ✅ Full | ✅ Full | ✅ Assigned / All | ✅ Assigned dept | ⚠️ Surrenders control |
| **View All Organization Leads & CRM** | ✅ Full | ✅ Full | ⚠️ Read basic | ⚠️ Assigned / Dept | ⚠️ Writes qualified leads |
| **Manage Personal Calendar & Availability** | ✅ Full | ✅ Full | ✅ Personal | ✅ Personal | ⚠️ Reads for booking |
| **View Analytics & Audit Logs** | ✅ Full | ✅ Full | ❌ None | ❌ None | ⚠️ Generates audit logs |
| **Process Inbound Audio & Execute RAG** | ❌ None | ❌ None | ❌ None | ❌ None | ✅ Core system function |

### Role Definitions:
1. **Super Admin / Business Owner**: Highest privilege tier. Manages tenant account, billing, global compliance settings, system integrations, and all administrators.
2. **Administrator**: Manages organizational policies, department definitions, business schedules, AI receptionist behavior guidelines, knowledge base documents, and user provisioning.
3. **Receptionist**: Front-desk operator monitoring incoming calls, queue status, live transcripts, and executing manual call takeover or warm transfers to sales reps.
4. **Sales Employee**: Field or desk sales executive receiving qualified leads, booked calendar appointments, and assigned follow-up tasks with full call transcript history.
5. **AI Receptionist (Autonomous Machine Identity)**: System-level role executing real-time voice conversations, querying RAG knowledge bases, mutating call session state, scheduling appointments, and emitting audit logs.

---

## 4. Non-Functional Requirements (NFR)

### NFR-1: Latency & Real-Time Performance
- **Speech-to-Text Latency**: Streaming partial transcription within **150ms**; final utterance boundary detection within **250ms**.
- **LLM Time-to-First-Token (TTFT)**: Under **400ms** using streaming endpoints.
- **Text-to-Speech Streaming Latency**: First synthesized audio chunk returned within **200ms** of receiving initial sentence tokens.
- **Total Acoustic Turnaround Latency**: User silence to AI voice start $\le$ **800ms**.

### NFR-2: Concurrency & System Capacity
- System must support up to **100,000 registered users** in the database.
- Multi-instance stateless design capable of scaling from **50 to 500+ simultaneous active voice calls** without session cross-talk or degradation.
- Strict isolation of in-memory call state using Redis key namespacing (`call:session:{org_id}:{call_id}`).

### NFR-3: High Availability & Reliability
- 99.9% uptime for core API and call ingestion gateways.
- Graceful degradation: If RAG vector search times out (>400ms), fallback to core system prompt guidelines without stalling the call.
- Fail-safe audio handling: If LLM fails or hits rate limits, immediate playback of natural filler audio ("I am looking that up for you right now...") to prevent awkward silence.

### NFR-4: Security & Compliance
- Full tenant isolation at database and vector index level.
- Multi-factor authentication (MFA) and JWT-based session security with short-lived access tokens and refresh rotation.
- In-transit encryption (TLS 1.3 for HTTPS and WSS) and at-rest encryption (AES-256) for audio recordings, transcripts, and database storage.
- Mandatory two-party call recording consent announcement at call initiation.
- Immutable audit logging for all administrative actions, data exports, and call access.
