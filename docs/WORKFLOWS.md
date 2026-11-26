# FortiSales AI – System Workflows & Operational Sequences

This document details the core operational workflows governing FortiSales AI, accompanied by Mermaid sequence and flowchart diagrams reflecting the actual implementation.

---

## Workflow A: Inbound Voice Call Lifecycle & AudioWorklet Ingestion

**Scope**: Browser/Telephony client connects $\to$ Ephemeral ticket redemption $\to$ Full-duplex WebSocket session $\to$ VAD framing $\to$ STT $\to$ LLM $\to$ Sentence-level TTS $\to$ Call persistence.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Caller (AudioWorklet)
    participant API as FastAPI REST Gateway
    participant Redis as Redis Ticket Cache
    participant WSGateway as WebSocket Voice Gateway
    participant VAD as Silero VAD
    participant STT as Deepgram Nova-2
    participant Orchestrator as Conversation Orchestrator
    participant TTS as Cartesia/ElevenLabs TTS
    participant DB as PostgreSQL DB

    Caller->>API: POST /api/v1/voice/tickets (Bearer JWT)
    API->>Redis: Set Ticket Hash (TTL=30s)
    API-->>Caller: Return Raw Ticket String (tkt_...)

    Caller->>WSGateway: Connect /api/v1/voice/stream?ticket=tkt_...
    WSGateway->>Redis: GETDEL voice_ticket:{hash}
    alt Ticket Invalid or Expired
        WSGateway-->>Caller: Close 4401 Unauthorized
    else Origin Forbidden
        WSGateway-->>Caller: Close 4403 Forbidden
    else Ticket Valid
        WSGateway->>DB: Insert `calls` (status='in_progress')
        WSGateway->>DB: Insert `conversations` (status='active')
        WSGateway-->>Caller: Send Connection Ready JSON
    end

    loop Dialogue Turns
        Caller->>WSGateway: Stream 20ms PCM16 Frames (640 bytes)
        WSGateway->>VAD: Evaluate Speech Energy
        WSGateway->>STT: Forward Audio Buffer
        VAD-->>WSGateway: Speech Ended (>400ms silence)
        STT-->>Orchestrator: Deliver Utterance Transcript
        Orchestrator->>TTS: Stream Sentence Token Chunks
        TTS-->>WSGateway: Synthesized Audio Frames
        WSGateway-->>Caller: Audio Frames to AudioWorklet
    end

    Caller->>WSGateway: Disconnects / Hangs Up
    WSGateway->>DB: Update `calls` (status='completed', duration_seconds=N)
    WSGateway->>DB: Auto-create `leads` (if qualified)
    WSGateway->>DB: Commit Session State
```

---

## Workflow B: Customer Knowledge Inquiry & pgvector RAG Retrieval

**Scope**: Caller asks a company question (pricing, policies, services) $\to$ Semantic retrieval $\to$ Catalog precedence enforcement $\to$ Spoken response.

```mermaid
flowchart TD
    Question([Caller Asks Question]) --> Orchestrator[Conversation Orchestrator]
    Orchestrator --> IntentCheck{Inquiry Type?}

    IntentCheck -->|Pricing / Service Spec| ToolCatalog[Execute: get_product_or_service_details]
    IntentCheck -->|Policies / FAQs / General| ToolRAG[Execute: query_knowledge_base]

    ToolCatalog --> CatalogDB[(products_services Table)]
    CatalogDB --> PricingRule{Structured Price Found?}
    PricingRule -->|Yes| Override[Confirmed Catalog Price Enforced]
    PricingRule -->|No| FallbackToRAG[Query Vector Knowledge Chunks]

    ToolRAG --> VectorDB[(knowledge_chunks Table)]
    VectorDB --> CosineSearch[Execute 384-dim Cosine Distance: <=>]
    CosineSearch --> TopChunks[Retrieve Top 3 Chunks > 0.70 Similarity]

    Override --> LLMSynthesis[LLM Response Generation]
    TopChunks --> LLMSynthesis
    FallbackToRAG --> VectorDB

    LLMSynthesis --> GuardrailCheck{Facts in Context?}
    GuardrailCheck -->|Yes| SpokenOutput[Stream Sentence-Level TTS to Caller]
    GuardrailCheck -->|No| HonestDecline["Honestly Admit Unknown & Offer Specialist Follow-Up"]
    HonestDecline --> SpokenOutput
```

---

## Workflow C: Autonomous Lead Qualification, Scoring & CRM Pipeline

**Scope**: Customer dialogue turns $\to$ Turn intelligence extraction $\to$ Lead scoring (0–100) $\to$ Tiering $\to$ CRM lead creation $\to$ Sales rep isolation.

```mermaid
flowchart LR
    TurnTranscript[Spoken Dialogue Turn] --> TurnExtractor[Orchestrator Turn Intelligence]
    TurnExtractor --> BANT["Extract Budget, Authority, Need, Timeline"]
    BANT --> LeadScorer["Calculate Score (0-100)"]

    LeadScorer --> TierDecision{Score Tier}
    TierDecision -->|Score >= 70| HotTier["Hot Lead (Immediate Priority)"]
    TierDecision -->|Score 40-69| WarmTier["Warm Lead (Follow-up 24h)"]
    TierDecision -->|Score < 40| ColdTier["Cold Lead (Nurture)"]

    HotTier --> LeadInsert[Insert/Update `leads` in PostgreSQL]
    WarmTier --> LeadInsert
    ColdTier --> LeadInsert

    LeadInsert --> CallEnd{Call Concluded?}
    CallEnd -->|Yes| AdminAssign[Admin Assigns Lead to Sales Employee]
    AdminAssign --> SalesRepPortal[Sales Rep Workspace: /sales-dashboard]
    SalesRepPortal --> IsolationCheck{Cross-Rep Isolation}
    IsolationCheck -->|Assigned Rep| FullAccess[View Lead & Schedule Discovery]
    IsolationCheck -->|Other Rep| Forbidden[Access Blocked: 403 Forbidden]
```

---

## Workflow D: Conflict-Free Appointment Booking with GiST Exclusion

**Scope**: Customer requests booking $\to$ Availability check $\to$ Customer confirmation $\to$ Atomic booking protected by PostgreSQL GiST exclusion constraint.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Customer
    participant Orchestrator as AI Receptionist
    participant ApptTool as Appointment Tools
    participant AvailService as Availability Engine
    participant BookService as Booking Service
    participant DB as PostgreSQL 16 (btree_gist)

    Caller->>Orchestrator: "I'd like to book an appointment this Friday at 10 AM"
    Orchestrator->>ApptTool: check_appointment_availability(date="2026-11-27", employee_id)
    ApptTool->>AvailService: Evaluate Operating Hours, Holidays, Overlaps
    AvailService-->>ApptTool: Slot Available (10:00 - 10:30 AM)
    ApptTool-->>Orchestrator: Available
    Orchestrator-->>Caller: "I have 10:00 AM available on Friday. Shall I confirm this booking?"
    Caller->>Orchestrator: "Yes, please confirm it."

    rect rgb(245, 243, 255)
        Note over Orchestrator,DB: Atomic Booking & Concurrency Guard
        Orchestrator->>ApptTool: book_appointment(customer_confirmed=True)
        ApptTool->>BookService: Execute Booking inside Async Transaction
        BookService->>DB: Immediate Revalidation Query
        BookService->>DB: INSERT INTO appointments ...
        alt Slot Free
            DB-->>BookService: 201 Created (Appointment Locked)
            BookService-->>Orchestrator: Booking Confirmed
            Orchestrator-->>Caller: "Your appointment is confirmed for Friday at 10:00 AM!"
        else Concurrent Conflict (Race Condition)
            DB-->>BookService: Raise IntegrityError: ExclusionConstraintViolation
            BookService-->>Orchestrator: 409 Conflict (Slot Taken)
            Orchestrator-->>Caller: "I apologize, that slot was just booked. May I offer 11:00 AM instead?"
        end
    end
```

---

## Workflow E: Live Human Handoff & Receptionist Takeover

**Scope**: Customer requests human $\to$ Tool execution $\to$ Session escalation $\to$ Real-time queue alert in receptionist portal $\to$ Staff takeover.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Customer
    participant WSGateway as Voice Gateway
    participant Orchestrator as Conversation Orchestrator
    participant HandoffTool as request_human_handoff Tool
    participant DB as PostgreSQL DB
    actor Receptionist as Receptionist Staff
    participant RecPortal as Receptionist Portal (/receptionist-dashboard)

    Caller->>WSGateway: "Can I speak to a real person please?"
    WSGateway->>Orchestrator: User Transcript
    Orchestrator->>Orchestrator: Intent Extraction: needs_human_intervention=True
    Orchestrator->>HandoffTool: Execute request_human_handoff(urgency='high')

    HandoffTool->>DB: Update `conversations` (status='handed_off')
    HandoffTool->>DB: Update `calls` (status='handed_off', outcome='handed_off')
    HandoffTool->>DB: Insert `inquiries` (status='open', priority='high')
    HandoffTool->>DB: Update `leads` (qualification_tier='hot')
    HandoffTool-->>Orchestrator: Handoff Queued (ticket_id="ESC-...")
    Orchestrator-->>Caller: "I have escalated your call to our representative team..."

    RecPortal->>DB: Poll /api/v1/conversations/handoffs (or real-time update)
    RecPortal-->>Receptionist: Red Handoff Badge Increments (1 Pending)
    Receptionist->>RecPortal: Clicks "Take Over Call"
    RecPortal->>DB: POST /api/v1/conversations/{id}/takeover
    DB-->>RecPortal: Updated Call (taken_over_by_employee_id=Staff ID)
    RecPortal-->>Receptionist: Status Updated: "Taken Over" (Staff in Control)
```

---

## Workflow F: Resilient AI Model Outage Fallback

**Scope**: Upstream LLM provider timeout or 5xx outage $\to$ Graceful error catch $\to$ Safe customer turn recording $\to$ Session marked handed off $\to$ Polite spoken follow-up.

```mermaid
flowchart TD
    CustomerTurn[Customer Message Arrives] --> Orchestrator[Conversation Orchestrator]
    Orchestrator --> LLMCall[Call active_provider.generate_response]

    LLMCall --> ProviderHealth{Provider Status}
    ProviderHealth -->|Normal| ModelResponse[Process Model Reply & Tool Loop]
    ProviderHealth -->|Timeout / 5xx Outage| ErrorCatch[Catch Exception: AIProviderTransientError]

    ErrorCatch --> RollbackTx[Rollback Failed Transaction]
    RollbackTx --> FreshTx[Open Clean Transaction]

    FreshTx --> RecordCallerTurn[Insert `messages` speaker_role='caller']
    RecordCallerTurn --> RecordFallbackTurn["Insert `messages` speaker_role='ai_agent' (Polite Apology)"]
    RecordFallbackTurn --> UpdateHandoffState["Update `conversations` status='handed_off'"]
    UpdateHandoffState --> UpdateCallRecord["Update `calls` status='handed_off', outcome='ai_fallback_handoff'"]
    UpdateCallRecord --> CommitFallback[Commit Clean Transaction]

    CommitFallback --> ReturnTurnResponse["Return 200 OK Turn Response (status='handed_off')"]
    ReturnTurnResponse --> QueueAlert[Handoff Appears in Receptionist Queue]
    ReturnTurnResponse --> SpokenApology["Stream TTS: 'I apologize, experiencing difficulties. Representative will follow up promptly.'"]
```
