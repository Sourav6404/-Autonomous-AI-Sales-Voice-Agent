# FortiSales AI – System Workflows & Operational Sequences

This document details the seven end-to-end operational workflows governing FortiSales AI, accompanied by Mermaid sequence and flow diagrams.

---

## Workflow A: Inbound Call Lifecycle & Session Ingestion

**Scope**: Customer dials in $\to$ Customer identification $\to$ Call session instantiation $\to$ Voice conversation loop $\to$ Session finalization and transcript persistence.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Inbound Caller
    participant Telephony as Telephony Gateway (Twilio/SIP)
    participant WSGateway as FastAPI Call Gateway
    participant Redis as Redis Session Cache
    participant DB as PostgreSQL DB
    participant Celery as Celery Async Worker

    Caller->>Telephony: Inbound Voice Call
    Telephony->>WSGateway: Establish WebSocket Connection (CallSID, CallerPhone, DID)
    WSGateway->>DB: Query Customer by Phone (org_id, caller_phone)
    alt Customer Exists
        DB-->>WSGateway: Return Customer Record (Name, History, Notes)
    else New Customer
        WSGateway->>DB: Create Customer Record (CallerPhone, Status=New)
        DB-->>WSGateway: Return New Customer ID
    end

    WSGateway->>DB: Insert `calls` Record (Status='in_progress', StartedAt=NOW)
    DB-->>WSGateway: Return `call_id`

    WSGateway->>Redis: Initialize Session `call:session:{org_id}:{call_id}` (Customer Profile, Empty Turns)
    WSGateway->>Telephony: Send Initial Greeting TTS ("Hello, thank you for calling Acme Corp...")

    loop Conversational Turns
        Telephony->>WSGateway: Stream Inbound Audio Frames
        WSGateway->>WSGateway: Process VAD + STT + LLM + TTS
        WSGateway-->>Telephony: Stream Outbound Audio Chunks
        WSGateway->>Redis: Append Turn (Role, Message, Sentiment, Latency)
    end

    Caller->>Telephony: Hangs Up Call
    Telephony->>WSGateway: WS Disconnect / Event: 'stop'
    WSGateway->>DB: Update `calls` (Status='completed', EndedAt=NOW, Duration=TotalSeconds)
    WSGateway->>Celery: Enqueue `tasks.process_post_call(call_id)`
    WSGateway->>Redis: Set Session Expiry (TTL=24 hours)

    Celery->>Redis: Fetch Full Call Turns & Slot Metadata
    Celery->>DB: Batch Insert `conversations` and `messages`
    Celery->>Celery: Run LLM Call Summarization & Lead Scoring
    Celery->>DB: Insert `call_summaries`
```

---

## Workflow B: Customer Knowledge Enquiry & RAG Retrieval

**Scope**: Caller asks a complex factual question (pricing, SLA, tech specs) $\to$ Semantic retrieval $\to$ Guardrailed LLM synthesis $\to$ Audible delivery.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Caller
    participant AudioCore as Audio Pipeline (FastAPI)
    participant Embedder as Sentence Transformer / Embeddings API
    participant VectorDB as PostgreSQL (pgvector)
    participant LLM as Streaming LLM (Gemini 1.5 Flash)
    participant TTS as Streaming TTS (Cartesia)

    Caller->>AudioCore: "What is your refund policy and do you offer monthly billing?"
    AudioCore->>AudioCore: VAD End-of-Utterance Detected
    AudioCore->>Embedder: Generate Query Embedding Vector (384/1536 dim)
    Embedder-->>AudioCore: Vector Float Array

    AudioCore->>VectorDB: Query Cosine Similarity (<=> distance) with Org Filter
    Note over VectorDB: SELECT chunk_content FROM knowledge_chunks<br/>WHERE org_id = :org_id AND distance < 0.28<br/>ORDER BY distance LIMIT 3;
    VectorDB-->>AudioCore: Top 3 Grounded Knowledge Chunks

    AudioCore->>LLM: Stream System Prompt + Grounded Chunks + Dialog History + User Query
    Note over LLM: Groundedness Guardrail Active:<br/>Synthesize answer solely from chunks.<br/>If unmentioned, state specialist required.

    loop Stream Response
        LLM-->>AudioCore: Stream Tokens
        AudioCore->>TTS: Stream Sentence Clauses
        TTS-->>AudioCore: Synthesized Audio Chunks
        AudioCore-->>Caller: Stream Audio to Ear
    end
```

---

## Workflow C: Conversational Lead Qualification & CRM Extraction

**Scope**: The AI receptionist conversationally gathers customer criteria, executes scoring, updates customer records, and triggers sales notifications.

```mermaid
flowchart TD
    Start([Caller Engaged in Sales Conversation]) --> ExtractUtterance[Parse Caller Utterance]
    ExtractUtterance --> SlotFilling{Contains Qualification Data?}

    SlotFilling -- Budget Mentioned --> UpdateBudget[Update Slot: Budget Range]
    SlotFilling -- Authority Mentioned --> UpdateAuth[Update Slot: Decision Maker Flag]
    SlotFilling -- Need Mentioned --> UpdateNeed[Update Slot: Core Pain Points]
    SlotFilling -- Timeline Mentioned --> UpdateTime[Update Slot: Purchase Timeline]
    SlotFilling -- General Chit-Chat --> ContinueConv[Continue Conversational Flow]

    UpdateBudget & UpdateAuth & UpdateNeed & UpdateTime --> RedisSync[Sync Dynamic Slots to Redis]
    RedisSync --> EvaluateScore[Calculate Real-Time BANT Score 0-100]

    EvaluateScore --> ThresholdCheck{Score >= 70?}
    ThresholdCheck -- Yes --> MarkHot[Tier = HOT Lead]
    ThresholdCheck -- 40 to 69 --> MarkWarm[Tier = WARM Lead]
    ThresholdCheck -- < 40 --> MarkCold[Tier = COLD / Unqualified]

    MarkHot --> ProposeMeeting[AI Prompt: Proactively Suggest Booking Demo]
    MarkWarm --> ProposeMeeting
    MarkCold --> OfferGeneralInfo[AI Prompt: Offer Collateral / Email Follow-up]

    ProposeMeeting --> CallEnd([Call Ends])
    OfferGeneralInfo --> CallEnd

    CallEnd --> CeleryPostProcess[Celery Task: Ingest Lead into CRM]
    CeleryPostProcess --> DBInsert[Insert/Update `leads` and `customers` Tables]
    DBInsert --> AssignRep[Assign Round-Robin Sales Representative]
    AssignRep --> CreateTask[Generate `follow_up_tasks` for Sales Rep]
```

---

## Workflow D: Real-Time Appointment Scheduling & Slot Collision Guard

**Scope**: Customer requests a demo/meeting $\to$ Evaluate working hours, holidays, and employee calendars $\to$ Propose available times $\to$ Confirm with atomic database lock.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Caller
    participant AI as AI Receptionist (FastAPI)
    participant ScheduleService as Scheduling Service
    participant Redis as Redis Lock Manager
    participant DB as PostgreSQL DB

    Caller->>AI: "Can I schedule a product demo for this Thursday afternoon?"
    AI->>ScheduleService: Query Availability(Date='2026-11-26', TimeRange='afternoon')
    ScheduleService->>DB: Check `business_hours` & `holidays` for Thursday
    Note over DB: Verify Thursday is open & not a company holiday
    ScheduleService->>DB: Query `employees` matching sales department
    ScheduleService->>DB: Query existing `appointments` for Thursday afternoon
    ScheduleService-->>AI: Available Slots: 14:00-14:30, 15:00-15:30

    AI-->>Caller: "I have openings this Thursday at 2:00 PM or 3:00 PM Eastern. Which works best for you?"
    Caller->>AI: "Let's do 2:00 PM."

    AI->>Redis: Acquire Distributed Lock `lock:appointment:{emp_id}:2026-11-26T14:00` (TTL 30s)
    alt Lock Acquired
        AI->>DB: Begin Transaction
        AI->>DB: Insert into `appointments` (Status='scheduled', Start='14:00', End='14:30')
        Note over DB: PostgreSQL GiST Exclusion Constraint validates no overlap
        AI->>DB: Commit Transaction
        AI->>Redis: Release Distributed Lock
        AI-->>Caller: "You're all set! I have booked your product demo for this Thursday at 2:00 PM. A calendar invite has been sent to your email."
    else Lock Failed (Slot Just Taken)
        AI-->>Caller: "I apologize, that 2:00 PM slot was just reserved. Would 3:00 PM work for you instead?"
    end
```

---

## Workflow E: Human Receptionist Takeover & Call Transfer

**Scope**: Caller frustration or specific request for a human $\to$ Alert staff via WebSocket $\to$ Audio bridge transition $\to$ Real-time context handover.

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Caller
    participant Gateway as FastAPI Call Gateway
    participant MonitorWS as Live Monitor Hub
    actor Staff as Human Receptionist / Sales Rep
    participant AudioBridge as WebRTC / SIP Audio Bridge

    Caller->>Gateway: "I want to speak with a human supervisor right now."
    Gateway->>Gateway: Intent Detected: ESCALATION_REQUEST
    Gateway-->>Caller: "I understand. Let me transfer you directly to one of our specialists. Please stay on the line."

    Gateway->>MonitorWS: Broadcast Event `call.escalation` {call_id, customer_name, urgency="high"}
    MonitorWS-->>Staff: Sound Audio Chime & Flash Banner on Dashboard
    Staff->>MonitorWS: Click "Review & Accept Call"

    MonitorWS->>Gateway: Command `takeover_approved` {employee_id: "emp_123"}
    Gateway->>Gateway: Pause AI LLM & Mute TTS Engine
    Gateway->>AudioBridge: Route Caller Audio Track to Staff WebRTC Endpoint
    Gateway->>AudioBridge: Route Staff Audio Track to Caller Inbound Stream

    Staff-->>Caller: "Hello! This is Alex from customer relations. I have your call history right in front of me. How can I assist you today?"

    Note over Gateway: Call status updated to `handed_off`.<br/>AI pipeline continues passive transcription in background.
```

---

## Workflow F: Multiple Simultaneous Calls on Shared AI Infrastructure

**Scope**: High concurrency scenario $\to$ N simultaneous incoming calls $\to$ Isolated state machines $\to$ Shared connection pools and worker queues.

```mermaid
flowchart TB
    subgraph InboundTraffic ["Inbound Traffic Pool"]
        Call1["Call 1 (Org A, Customer 1)"]
        Call2["Call 2 (Org A, Customer 2)"]
        CallN["Call N (Org B, Customer X)"]
    end

    subgraph FastAPIGateways ["FastAPI Async WebSocket Pool"]
        Handler1["asyncio.Task: Call 1 Handler"]
        Handler2["asyncio.Task: Call 2 Handler"]
        HandlerN["asyncio.Task: Call N Handler"]
    end

    subgraph RedisState ["Redis Memory Isolation"]
        Session1[("call:session:OrgA:Call1<br/>- VAD Buffer<br/>- Turns 1..k<br/>- Slots")]
        Session2[("call:session:OrgA:Call2<br/>- VAD Buffer<br/>- Turns 1..m<br/>- Slots")]
        SessionN[("call:session:OrgB:CallN<br/>- VAD Buffer<br/>- Turns 1..j<br/>- Slots")]
    end

    subgraph AIWorkerPool ["Shared AI Infrastructure (Managed Rate-Limited Queues)"]
        SemSTT["STT Semaphore Pool (Max 200 concurrent streams)"]
        SemLLM["LLM Token Stream Multiplexer (Async Client Session)"]
        SemTTS["TTS Synthesis Engine (Zero-Copy HTTP/2 Stream)"]
    end

    Call1 <--> Handler1
    Call2 <--> Handler2
    CallN <--> HandlerN

    Handler1 <--> Session1
    Handler2 <--> Session2
    HandlerN <--> SessionN

    Handler1 & Handler2 & HandlerN --> SemSTT
    Handler1 & Handler2 & HandlerN --> SemLLM
    Handler1 & Handler2 & HandlerN --> SemTTS
```

---

## Workflow G: Holiday & Business Closure Availability Handling

**Scope**: Incoming call arrives $\to$ System checks real-time availability rules $\to$ Routes to holiday greeting, emergency message, or customized after-hours handling.

```mermaid
flowchart TD
    CallIn([Incoming Call Arrives]) --> FetchConfig[Fetch Organization Business Settings & Availability]
    FetchConfig --> CheckEmergency{Emergency Closure Active?}

    CheckEmergency -- Yes --> PlayEmergency[Play Emergency Announcement & Reason]
    PlayEmergency --> LogVoicemail[Record Caller Voicemail / Callback Request]
    LogVoicemail --> TerminateCall([Graceful Hangup])

    CheckEmergency -- No --> CheckMasterToggle{AI Master Status == 'offline'?}
    CheckMasterToggle -- Yes --> ForwardExternal[Forward Call to PSTN External Fallback Number]
    ForwardExternal --> TerminateCall

    CheckMasterToggle -- No --> CheckHoliday{Current Date in `holidays`?}
    CheckHoliday -- Yes --> PlayHoliday[Speak Holiday Announcement & Reopening Date]
    PlayHoliday --> OfferBooking[Offer Automated Appointment Booking for Reopen Date]
    OfferBooking --> TerminateCall

    CheckHoliday -- No --> CheckHours{Current Time Within `business_hours`?}
    CheckHours -- Yes --> OpenSession([Initiate Full Conversational AI Receptionist])

    CheckHours -- No --> AfterHoursMode{Check `after_hours_behavior`}
    AfterHoursMode -- 'ai_voicemail' --> VoicemailGreeting[AI: 'We are currently closed. Please leave a message.']
    AfterHoursMode -- 'ai_general_info_only' --> LimitedSession[AI: Limit to FAQ & Appointment Booking Only]
    AfterHoursMode -- 'forward_to_number' --> ForwardExternal

    VoicemailGreeting --> LogVoicemail
    LimitedSession --> OpenSession
```
