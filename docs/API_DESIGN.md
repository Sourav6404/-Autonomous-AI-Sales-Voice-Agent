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

### 2.1 Staff Authentication
- `POST /auth/login`
  - **Body**: `{ "email": "admin@company.com", "password": "securePassword123" }`
  - **Response (200 OK)**:
    ```json
    {
      "access_token": "eyJhbGciOi...",
      "refresh_token": "dGhpcy1pcy1...",
      "token_type": "Bearer",
      "expires_in": 3600,
      "user": {
        "id": "e2f1842e-1317-48f1-8f5b-0925e0c52bb1",
        "email": "admin@company.com",
        "role": "admin",
        "org_id": "78b4081c-99d9-48f3-8b7c-c46b5a265691"
      }
    }
    ```
- `POST /auth/refresh`
  - **Body**: `{ "refresh_token": "dGhpcy1pcy1..." }`
  - **Response (200 OK)**: `{ "access_token": "...", "expires_in": 3600 }`
- `POST /auth/logout`
  - **Headers**: `Authorization: Bearer <token>`
  - **Action**: Blacklists current token in Redis until expiry.

---

## 3. Business Availability & Operations Configuration Endpoints

### 3.1 Operating Hours Management
- `GET /organizations/{org_id}/business-hours`
  - Returns standard weekly operating hours, split shifts, and department-specific overrides.
- `PUT /organizations/{org_id}/business-hours`
  - **Permissions**: `admin`, `super_admin`
  - **Body**:
    ```json
    {
      "hours": [
        { "day_of_week": 1, "open_time": "09:00", "close_time": "18:00", "is_closed": false },
        { "day_of_week": 2, "open_time": "09:00", "close_time": "18:00", "is_closed": false },
        { "day_of_week": 3, "open_time": "09:00", "close_time": "18:00", "is_closed": false },
        { "day_of_week": 4, "open_time": "09:00", "close_time": "18:00", "is_closed": false },
        { "day_of_week": 5, "open_time": "09:00", "close_time": "17:00", "is_closed": false },
        { "day_of_week": 6, "open_time": "10:00", "close_time": "14:00", "is_closed": false },
        { "day_of_week": 0, "open_time": "00:00", "close_time": "00:00", "is_closed": true }
      ]
    }
    ```

### 3.2 Holidays & Special Schedules
- `GET /organizations/{org_id}/holidays`
- `POST /organizations/{org_id}/holidays`
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
- `POST /organizations/{org_id}/special-schedules`
  - Defines temporary closures or irregular working hours on specific dates.

### 3.3 AI Availability & Master Toggle
- `GET /organizations/{org_id}/ai-availability`
  - Returns current AI receptionist state (`online`, `offline`, `maintenance`), emergency status, and active routing mode.
- `PATCH /organizations/{org_id}/ai-availability`
  - **Permissions**: `receptionist`, `admin`, `super_admin`
  - **Body**:
    ```json
    {
      "status": "offline",
      "emergency_closure_active": false,
      "emergency_reason": "Manual operator maintenance"
    }
    ```

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

## 5. Staff Live Monitor & Human Takeover WebSocket Protocol

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
