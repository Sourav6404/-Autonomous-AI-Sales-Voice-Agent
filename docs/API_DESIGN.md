# FortiSales AI – REST & WebSocket API Specification

## 1. Overview & General Conventions

The FortiSales AI API conforms to OpenAPI 3.1 standards and JSON:API conventions for REST endpoints, supplemented by bidirectional, low-latency WebSocket protocols for audio streaming and live call monitoring.

- **Base URL**: `https://api.fortisales.ai/v1`
- **WebSocket Gateway URL**: `wss://stream.fortisales.ai/v1`
- **Content Type**: `application/json` (REST), `application/octet-stream` / JSON text framing (WebSockets)
- **Authentication**: Bearer JWT (`Authorization: Bearer <access_token>`) or API Key (`X-API-Key: <key>`)
- **Standard Error Payload**:
  ```json
  {
    "error": {
      "code": "SLOT_CONFLICT",
      "message": "The requested appointment time slot is no longer available.",
      "details": { "requested_start": "2026-11-26T14:00:00Z" },
      "timestamp": "2026-11-25T21:45:00Z"
    }
  }
  ```

---

## 2. Authentication & Tenant Authorization Endpoints

### 2.1 Organization Registration & Initial Owner
- `POST /auth/register` (Available at `/api/v1/auth/register` and `/v1/auth/register`)
  - **Body**:
    ```json
    {
      "org_name": "Apex AI Solutions",
      "org_slug": "apex-ai-solutions",
      "timezone": "America/New_York",
      "email": "owner@apexai.com",
      "password": "SecurePassword123!",
      "full_name": "Alice Apex",
      "phone_number": "+15551234567"
    }
    ```
  - **Response (201 Created)**:
    ```json
    {
      "user": {
        "id": "e2f1842e-1317-48f1-8f5b-0925e0c52bb1",
        "org_id": "78b4081c-99d9-48f3-8b7c-c46b5a265691",
        "email": "owner@apexai.com",
        "full_name": "Alice Apex",
        "role": "owner",
        "is_active": true,
        "created_at": "2026-11-25T23:00:00Z"
      },
      "org_id": "78b4081c-99d9-48f3-8b7c-c46b5a265691",
      "org_name": "Apex AI Solutions",
      "tokens": {
        "access_token": "eyJhbGciOi...",
        "refresh_token": "eyJhbGciOi...",
        "token_type": "bearer",
        "expires_in": 3600
      }
    }
    ```

### 2.2 Staff Authentication
- `POST /auth/login`
  - **Body**: `{ "email": "owner@apexai.com", "password": "SecurePassword123!" }`
  - **Response (200 OK)**:
    ```json
    {
      "access_token": "eyJhbGciOi...",
      "refresh_token": "eyJhbGciOi...",
      "token_type": "bearer",
      "expires_in": 3600
    }
    ```
- `POST /auth/refresh`
  - **Body**: `{ "refresh_token": "eyJhbGciOi..." }`
  - **Response (200 OK)**: `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 3600 }`
- `POST /auth/logout`
  - **Headers**: `Authorization: Bearer <token>`
  - **Action**: Blacklists current token until expiry.
- `GET /auth/me`
  - **Headers**: `Authorization: Bearer <token>`
  - **Response (200 OK)**: Current authenticated user profile and role claims.

---

## 3. Business Availability & Operations Configuration Endpoints

### 3.1 Organization Profile Management
- `GET /organizations/me`
  - Returns current tenant organization profile (name, slug, default_timezone).
- `PATCH /organizations/me`
  - **Permissions**: `owner`, `admin`
  - **Body**: `{ "name": "Updated Corp Name", "default_timezone": "America/Chicago" }`

### 3.2 Business Profile & Telephony Settings
- `GET /business-settings`
  - Returns business profile, address, contact phone/email, services, voice_id, after_hours_behavior, recording consent.
- `PATCH /business-settings`
  - **Permissions**: `owner`, `admin`
  - **Body**: `{ "contact_phone": "+18005550199", "business_address": "100 Tech Blvd", "recording_consent_required": true }`

### 3.3 Operating Hours Management
- `GET /business-hours`
  - Returns weekly operating hours, split shifts, and optional department filter (`?department_id=`).
- `PUT /business-hours`
  - **Permissions**: `owner`, `admin`
  - **Body**:
    ```json
    {
      "schedules": [
        { "day_of_week": 1, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": false },
        { "day_of_week": 2, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": false },
        { "day_of_week": 0, "open_time": "00:00:00", "close_time": "23:59:59", "is_closed": true }
      ]
    }
    ```

### 3.4 Holidays & Special Schedules
- `GET /holidays`
- `POST /holidays`
  - **Permissions**: `owner`, `admin`
  - **Body**:
    ```json
    {
      "name": "New Year Holiday",
      "start_date": "2027-01-01",
      "end_date": "2027-01-02",
      "is_recurring_yearly": true,
      "special_announcement": "Our offices are closed for the New Year. For urgent sales, press 1."
    }
    ```
- `PATCH /holidays/{holiday_id}`
- `DELETE /holidays/{holiday_id}`
- `GET /special-schedules`
- `POST /special-schedules`
  - Defines temporary closures, split shifts, or custom working hours on specific dates.
- `DELETE /special-schedules/{schedule_id}`

### 3.5 AI Availability Precedence Resolution Engine
- `GET /ai-availability/status`
  - **Permissions**: `employee`, `receptionist`, `admin`, `owner`
  - Query parameters: `?department_id=` (optional), `?timestamp=` (optional ISO timestamp)
  - Evaluates strictly ordered precedence rules:
    1. Emergency closure active -> Business Closed, AI Offline
    2. Manual status override (`maintenance`, `takeover_only`, `offline`)
    3. Temporary offline mode (`temp_offline_until`)
    4. Special date schedule overrides
    5. Holiday closures
    6. Regular weekly operating hours
    7. Default closed state (with AI handling after-hours per `after_hours_behavior`)
- `PATCH /ai-availability`
  - **Permissions**: `receptionist`, `admin`, `owner`
  - Body: `{ "status": "online", "emergency_closure_active": false }`
- `POST /ai-availability/temp-offline`
  - **Permissions**: `receptionist`, `admin`, `owner`
  - Body: `{ "duration_minutes": 60, "reason": "Staff Lunch Break" }`
- `POST /ai-availability/scheduled-change`
  - **Permissions**: `admin`, `owner`
  - Body: `{ "scheduled_status": "maintenance", "scheduled_status_change_at": "2026-12-01T02:00:00Z" }`

---

## 4. Real-Time Call Streaming WebSocket Protocol

The call gateway provides a full-duplex WebSocket connection between the telephony provider (or web client) and the FastAPI backend.

- **Endpoint**: `wss://stream.fortisales.ai/v1/calls/stream`
- **Query Parameters**:
  - `org_id`: UUID
  - `telephony_sid`: String (e.g., Twilio Call SID)
  - `caller`: String (Caller phone number)
  - `callee`: String (Inbound dialed DID)

### 4.1 Inbound Messages (Client / Telephony Gateway $\to$ FastAPI)
```json
// 1. Connection Initialization
{
  "event": "start",
  "start": {
    "stream_id": "stream_84fa9201",
    "call_sid": "CA_123456789",
    "caller_number": "+15551234567",
    "callee_number": "+18005550199",
    "format": "audio/x-mulaw;rate=8000" // or "audio/x-raw;rate=16000"
  }
}

// 2. Continuous Inbound Audio Frame
{
  "event": "media",
  "media": {
    "track": "inbound",
    "chunk": 12,
    "payload": "base64EncodedAudioDataHere..."
  }
}

// 3. User Interruption / DTMF (Optional)
{
  "event": "dtmf",
  "dtmf": { "digit": "1" }
}

// 4. Call Disconnect / Hang-up
{
  "event": "stop",
  "stop": { "call_sid": "CA_123456789", "reason": "caller_hangup" }
}
```

### 4.2 Outbound Messages (FastAPI $\to$ Client / Telephony Gateway)
```json
// 1. Audio Playback Chunk (Streamed to Caller)
{
  "event": "media",
  "media": {
    "track": "outbound",
    "payload": "base64EncodedTTSAudioChunk..."
  }
}

// 2. Interruption Clear Command (Barge-In)
{
  "event": "clear",
  "stream_id": "stream_84fa9201"
}

// 3. Call Control Transfer / Hangup
{
  "event": "redirect",
  "destination": "+18005550198",
  "reason": "human_takeover"
}
```

---

## 5. Conversation Intelligence & Dialogue Session Endpoints (Stage 3)

### 5.1 Create Conversation Session
- `POST /v1/conversations` (or `/api/v1/conversations`)
  - **Headers**: `Authorization: Bearer <token>`
  - **Body**:
    ```json
    {
      "customer_phone": "+15551234567",
      "customer_name": "Jane Doe",
      "call_id": null,
      "language": "en"
    }
    ```
  - **Response (201 Created)**:
    ```json
    {
      "id": "e305d218-02ce-4e58-963d-4c38d2a6a58b",
      "org_id": "78b4081c-99d9-48f3-8b7c-c46b5a265691",
      "call_id": "a98818f1-4db5-42cf-9626-d621fc426fa1",
      "status": "active",
      "language": "en",
      "turn_count": 0,
      "summary": null,
      "created_at": "2026-11-25T23:50:00Z"
    }
    ```

### 5.2 Get Conversation Session
- `GET /v1/conversations/{conversation_id}`
  - **Headers**: `Authorization: Bearer <token>`
  - **Response (200 OK)**: Returns conversation session details scoped strictly to authenticated tenant.

### 5.3 Submit User Message & Execute Orchestration Turn
- `POST /v1/conversations/{conversation_id}/messages`
  - **Headers**: `Authorization: Bearer <token>`
  - **Body**:
    ```json
    {
      "content": "Hi, what time are you open on Mondays?"
    }
    ```
  - **Response (200 OK)**:
    ```json
    {
      "user_message": {
        "id": "4b68e982-b7e1-4c7b-b3c9-04a88f7293a1",
        "conversation_id": "e305d218-02ce-4e58-963d-4c38d2a6a58b",
        "turn_number": 1,
        "speaker_role": "caller",
        "content": "Hi, what time are you open on Mondays?",
        "created_at": "2026-11-25T23:50:05Z"
      },
      "agent_message": {
        "id": "6a90802c-5692-411a-bc07-bc7e2d9361a4",
        "conversation_id": "e305d218-02ce-4e58-963d-4c38d2a6a58b",
        "turn_number": 2,
        "speaker_role": "ai_agent",
        "content": "We are open from 8:30 AM to 5:30 PM on Mondays. How can I assist you further?",
        "created_at": "2026-11-25T23:50:07Z"
      },
      "extracted_intent": {
        "customer_intent": "General inquiry regarding Monday operating schedule",
        "intent_category": "inquiry",
        "urgency": "low",
        "sentiment": "neutral",
        "handoff_recommended": false
      },
      "tools_executed": [
        {
          "tool": "get_business_hours",
          "arguments": { "day_of_week": 1 },
          "result": { "schedules": [{ "day": "Monday", "open_time": "08:30:00", "close_time": "17:30:00", "is_closed": false }] }
        }
      ],
      "turn_count": 2
    }
    ```

### 5.4 Retrieve Conversation Message History
- `GET /v1/conversations/{conversation_id}/messages`
  - **Headers**: `Authorization: Bearer <token>`
  - **Response (200 OK)**: List of all message turns ordered by `turn_number ASC`.

### 5.5 End Conversation Session
- `POST /v1/conversations/{conversation_id}/end`
  - **Headers**: `Authorization: Bearer <token>`
  - **Response (200 OK)**: Updates status to `completed` and computes call duration if applicable.

---

## 6. Staff Live Monitor & Human Takeover WebSocket Protocol

Staff receptionists connect to this channel to observe live calls in real time and execute instantaneous takeovers.

- **Endpoint**: `wss://stream.fortisales.ai/v1/monitor/live`
- **Headers**: `Authorization: Bearer <staff_jwt>`

### 5.1 Server-to-Staff Events
```json
// Live Utterance Transcript Stream
{
  "event": "transcript_update",
  "call_id": "9a1f2b4c-8822-4a0b-99d8-745a1f22e091",
  "speaker": "caller",
  "text": "I'm looking to buy 50 enterprise licenses next month.",
  "sentiment": "positive",
  "current_score": 85,
  "timestamp": "2026-11-25T21:45:10Z"
}

// Takeover Request Alert
{
  "event": "takeover_requested",
  "call_id": "9a1f2b4c-8822-4a0b-99d8-745a1f22e091",
  "reason": "customer_requested_human",
  "customer_name": "John Doe",
  "company": "Acme Corp"
}
```

### 5.2 Staff-to-Server Commands
```json
// Command to Take Over Active Call
{
  "action": "initiate_takeover",
  "call_id": "9a1f2b4c-8822-4a0b-99d8-745a1f22e091",
  "employee_id": "b3e01124-71bb-45e0-94f1-61cc5b821992"
}
```

---

## 6. Appointments & Availability Scheduling Endpoints

### 6.1 Query Available Slots
- `GET /organizations/{org_id}/appointments/available-slots`
  - **Query Parameters**:
    - `department_id`: Optional UUID
    - `employee_id`: Optional UUID
    - `date`: `YYYY-MM-DD`
    - `timezone`: e.g., `America/New_York`
  - **Response (200 OK)**:
    ```json
    {
      "date": "2026-11-26",
      "available_slots": [
        { "start_time": "2026-11-26T14:00:00Z", "end_time": "2026-11-26T14:30:00Z", "employee_id": "b3e0..." },
        { "start_time": "2026-11-26T14:30:00Z", "end_time": "2026-11-26T15:00:00Z", "employee_id": "b3e0..." },
        { "start_time": "2026-11-26T16:00:00Z", "end_time": "2026-11-26T16:30:00Z", "employee_id": "b3e0..." }
      ]
    }
    ```

### 6.2 Book Appointment
- `POST /organizations/{org_id}/appointments`
  - **Body**:
    ```json
    {
      "customer_id": "4b68e982-b7e1-4c7b-b3c9-04a88f7293a1",
      "employee_id": "b3e01124-71bb-45e0-94f1-61cc5b821992",
      "call_id": "9a1f2b4c-8822-4a0b-99d8-745a1f22e091",
      "start_time": "2026-11-26T14:00:00Z",
      "end_time": "2026-11-26T14:30:00Z",
      "meeting_type": "Product Demo",
      "notes": "Interested in 50 licenses with SSO integration."
    }
    ```
  - **Response (201 Created)**: Returns created appointment object with `calendar_event_id`.

---

## 7. Knowledge Base & RAG Management Endpoints

- `POST /organizations/{org_id}/knowledge/upload`
  - **Form-Data**: `file` (PDF/TXT/DOCX), `document_type` ("pricing" / "faq"), `department_id` (optional)
  - **Response (202 Accepted)**:
    ```json
    {
      "document_id": "f8a19280-5b12-4cf3-a7c8-89c0b892a012",
      "status": "indexing_queued",
      "task_id": "task_4892019"
    }
    ```
- `POST /organizations/{org_id}/knowledge/query`
  - Internal testing endpoint for semantic retrieval testing.
  - **Body**: `{ "query": "What is your refund policy?", "department_id": null, "limit": 3 }`
  - **Response (200 OK)**: Returns matching chunks with cosine similarity score and citation metadata.

---

## 8. CRM Leads & Customer Endpoints

- `GET /organizations/{org_id}/leads`
  - Returns paginated list of leads with filter by `tier` (`hot`, `warm`, `cold`), `status`, and `assigned_employee_id`.
- `GET /organizations/{org_id}/calls/{call_id}/summary`
  - Returns structured AI post-call executive summary, sentiment analysis, key objections, and action items.
- `POST /organizations/{org_id}/customers`
  - Upsert customer record by phone number.

---

## 9. Real-Time Voice Streaming Gateway & Tickets (Stage 4.1)

### 9.1 Issue Voice-Session Ticket
- `POST /voice/tickets` (available at `/v1/voice/tickets` and `/api/v1/voice/tickets`)
- **Headers**: `Authorization: Bearer <access_token>`
- **Permissions**: Authenticated staff (`owner`, `admin`, `receptionist`, `employee`)
- **Description**: Generates a cryptographically secure, single-use, short-lived ticket for establishing a real-time voice WebSocket connection. The user ID and organization ID are derived strictly from the verified JWT.
- **Request Body**:
  ```json
  {
    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "customer_id": "4b68e982-b7e1-4c7b-b3c9-04a88f7293a1"
  }
  ```
  *(Note: `conversation_id` and `customer_id` are optional; if omitted, a new conversation/session is initialized upon connection).*
- **Response (200 OK)**:
  ```json
  {
    "ticket": "wB7x1_qS9...",
    "expires_in": 30,
    "websocket_url": "/api/v1/voice/stream"
  }
  ```
- **Error Responses**:
  - `401 Unauthorized`: Missing, expired, or invalid JWT token.
  - `404 Not Found`: Specified `conversation_id` does not exist or does not belong to the caller's tenant.

### 9.2 Real-Time Voice WebSocket Stream
- `WebSocket /voice/stream` (available at `/v1/voice/stream` and `/api/v1/voice/stream`)
- **Origin Validation**: Verified against `settings.CORS_ORIGINS`. Unauthorized origins are rejected with close code `4403 (Forbidden origin)`.
- **Authentication**:
  - Preferred First-Frame Auth message: Client immediately sends JSON text frame:
    ```json
    { "type": "auth", "ticket": "wB7x1_qS9..." }
    ```
  - Ticket is single-use and invalidated immediately via atomic deletion (Redis `GETDEL` or atomic in-memory fallback). Expired or replayed tickets result in close code `4401 (Unauthorized ticket)`.
- **Audio Framing**:
  - Raw binary frames: **16 kHz mono 16-bit linear PCM (LE)**.
  - Recommended packet size: 20ms frames = 640 bytes. Max frame buffer: 250 frames (5.0s audio buffer).
  - Oversized frames (> 12,800 bytes / 400ms burst) are rejected with error warning or connection termination.
- **Client Control Messages (JSON text frames)**:
  - `start`: `{ "type": "start", "recording_consent": false }`
  - `interrupt`: `{ "type": "interrupt", "timestamp_ms": 12450 }`
  - `mic_state`: `{ "type": "mic_state", "muted": true }`
  - `end_session`: `{ "type": "end_session", "reason": "user_hangup" }`
- **Server Event Messages (JSON text frames)**:
  - `session_created`:
    ```json
    {
      "type": "session_created",
      "session_id": "78b4081c-...",
      "call_id": "9a1f2b4c-...",
      "conversation_id": "3fa85f64-...",
      "state": "active",
      "recording_consent_given": false
    }
    ```
  - `session_ended`:
    ```json
    {
      "type": "session_ended",
      "session_id": "78b4081c-...",
      "call_id": "9a1f2b4c-...",
      "conversation_id": "3fa85f64-...",
      "state": "terminated",
      "duration_seconds": 45,
      "reason": "user_hangup"
    }
    ```
  - `error`:
    ```json
    {
      "type": "error",
      "code": "FRAME_OVERSIZED",
      "message": "Audio frame size 15000 exceeds maximum allowed 12800 bytes"
    }
    ```
- **WebSocket Close Codes**:
  - `1000`: Normal closure (clean user hangup).
  - `4401`: Unauthorized / invalid / expired ticket.
  - `4403`: Forbidden origin header.
  - `4409`: Conflict / concurrent connection to existing conversation (stale generation dropped).
  - `4429`: Tenant concurrent voice session limit exceeded.
  - `4500`: Internal server error during session initialization.
