# FortiSales AI – REST & WebSocket API Specification

## 1. Overview & General Conventions

The FortiSales AI API conforms to OpenAPI 3.1 standards and JSON conventions for REST endpoints, supplemented by a low-latency binary WebSocket protocol for real-time voice streaming.

- **Base URL**: `http://localhost:8000/v1` (with alias at `/api/v1`)
- **WebSocket Gateway URL**: `ws://localhost:8000/v1/voice/stream?ticket=<raw_ticket>`
- **Content Types**: `application/json` (REST), `multipart/form-data` (document uploads), `application/octet-stream` / binary frames (WebSockets)
- **Authentication**: Bearer JWT (`Authorization: Bearer <access_token>`)
- **WebSocket Authentication**: Ephemeral single-use 256-bit tickets (`POST /voice/tickets`), redeemed atomically via Redis `GETDEL` (close code `4401` on invalid/expired ticket, `4403` on forbidden origin).

---

## 2. Authentication & Tenant Authorization Endpoints

### `POST /auth/register`
Creates an organization tenant and root `owner` user account.
- **Request Body**:
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
- **Response (201 Created)**: Returns tenant ID, user object, and `{ access_token, refresh_token, token_type: "bearer" }`.

### `POST /auth/login`
Authenticates a user and returns signed JWT tokens.
- **Request Body**: `{ "email": "user@apexai.com", "password": "SecurePassword123!" }`
- **Response (200 OK)**: `{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }`

### `POST /auth/refresh`
Rotates tokens using single-use refresh token.
- **Request Body**: `{ "refresh_token": "..." }`
- **Response (200 OK)**: New access and refresh token pair.

### `POST /auth/logout`
Blacklists refresh token and clears session. Requires `Authorization: Bearer <token>`.

### `GET /auth/me`
Retrieves authenticated user profile, organization ID, and role.

---

## 3. Business Configuration Endpoints

- `GET /organizations/me`: Organization profile.
- `PUT /organizations/me`: Update organization name, slug, timezone (Admin only).
- `GET /business-settings`: Operating profile, description, services, address, after-hours behavior.
- `PUT /business-settings`: Update business profile (Admin only).
- `GET /business-hours`: Operating schedule per weekday (0=Sun to 6=Sat).
- `PUT /business-hours`: Update weekday hours (Admin only).
- `GET /holidays` / `POST /holidays` / `DELETE /holidays/{id}`: Holiday closures.
- `GET /special-schedules` / `POST /special-schedules`: Date-specific schedule overrides.
- `GET /ai-availability`: Real-time operating status and availability evaluation.

---

## 4. Voice Engine & Audio Endpoints

### `POST /voice/tickets`
Issues a cryptographically secure, single-use 256-bit voice session ticket with 30-second TTL.
- **Headers**: `Authorization: Bearer <token>`
- **Request Body**:
  ```json
  {
    "conversation_id": "optional-uuid",
    "caller_phone": "+15551234567",
    "language": "en"
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "ticket": "tkt_...",
    "expires_in_seconds": 30,
    "websocket_url": "/api/v1/voice/stream?ticket=tkt_...",
    "conversation_id": "...",
    "call_id": "..."
  }
  ```

### `WebSocket /voice/stream?ticket={raw_ticket}`
Full-duplex real-time voice streaming gateway.
- **Close Codes**:
  - `4401 Unauthorized`: Ticket expired or invalid.
  - `4403 Forbidden`: Browser Origin header is untrusted.
  - `4429 Rate Limited`: Tenant exceeded concurrent voice session quota.
- **Binary Frames**: Inbound and outbound 16kHz linear PCM16 audio (20ms = 640-byte frames).
- **JSON Control Messages**:
  - `{"type": "vad_state", "state": "speech_started"}` / `"speech_ended"`
  - `{"type": "transcript", "speaker": "caller", "text": "...", "is_final": true}`
  - `{"type": "transcript", "speaker": "ai_agent", "text": "..."}`
  - `{"type": "interrupted"}`: Dispatched when caller barge-in cancels active TTS.
  - `{"type": "handoff_status", "status": "handed_off", "message": "..."}`: Dispatched when AI triggers human escalation.

---

## 5. Conversation & Dialogue Endpoints

- `POST /conversations`: Initializes conversation session and underlying Call record.
- `GET /conversations/handoffs` (Stage 8): Lists pending handed-off calls requiring human attention (Receptionist / Admin).
  - Query Params: `include_taken_over: bool = false`, `limit: int = 50`.
- `POST /conversations/{id}/takeover` (Stage 8): Takes over a handed-off session as staff.
- `POST /conversations/{id}/handoff` (Stage 8): Manually triggers human handoff.
- `GET /conversations/{id}`: Retrieves conversation metadata and turn count.
- `POST /conversations/{id}/messages`: Posts customer utterance, executes orchestrator tool loop, and returns assistant reply.
- `GET /conversations/{id}/messages`: Chronological dialogue turn history.
- `POST /conversations/{id}/end`: Completes conversation, marks Call as completed, and auto-creates a CRM Lead.

---

## 6. Business Knowledge Base & RAG Endpoints

- `POST /knowledge/upload`: Uploads and ingests document (multipart PDF, DOCX, TXT) with sliding-window chunking and 384-dimensional pgvector embedding.
- `GET /knowledge/documents`: Lists uploaded knowledge documents and processing statuses (`pending`, `processed`, `failed`).
- `DELETE /knowledge/documents/{id}`: Deletes document and cascades deletion to vector chunks.
- `POST /knowledge/documents/{id}/retry`: Retries failed document processing.
- `GET /knowledge/faqs` / `POST /knowledge/faqs` / `PUT /knowledge/faqs/{id}` / `DELETE /knowledge/faqs/{id}`: FAQ CRUD management.
- `POST /knowledge/retrieve`: Executes semantic similarity search against knowledge chunks with cosine distance (`<=>`).
- `GET /knowledge/catalog` / `POST /knowledge/catalog`: Product & service offerings with definitive pricing models (`fixed`, `starting_at`, `quote_required`).
- `GET /knowledge/policies` / `POST /knowledge/policies`: Business policy management.

---

## 7. CRM, Leads & Inquiries Endpoints (Stage 6)

### Customers
- `GET /customers`: Paginated customer directory with search (`query` matches phone, name, email).
- `POST /customers`: Creates customer record (`phone_number`, `first_name`, `last_name`, `email`).
- `GET /customers/{id}`: Customer profile with call history and leads.
- `PUT /customers/{id}`: Updates customer details.
- `GET /customers/by-phone/{phone}`: Looks up customer by phone number.

### Leads
- `GET /leads`: Lists all organization leads (Admin / Receptionist).
- `GET /leads/my`: Lists only leads assigned to current user's employee profile (Sales Rep isolated).
- `GET /leads/{id}`: Retrieves specific lead details.
- `POST /leads`: Manually creates a lead.
- `PUT /leads/{id}`: Updates lead status (`new`, `contacted`, `qualified`, `converted`, `lost`), score, tier, and notes.
- `POST /leads/{id}/assign`: Assigns lead to a sales representative (Admin only).

### Inquiries
- `GET /inquiries`: Lists inquiry support tickets with status filter (`open`, `in_progress`, `resolved`).
- `POST /inquiries`: Creates inquiry ticket.
- `GET /inquiries/{id}`: Retrieves inquiry details.
- `PUT /inquiries/{id}`: Updates priority, description, or assigned staff.
- `POST /inquiries/{id}/resolve`: Resolves inquiry with resolution notes.

### Employees & Dashboard
- `GET /employees`: Lists organization staff members.
- `POST /employees`: Provisions an employee profile.
- `GET /dashboard/admin`: Executive dashboard statistics (total calls, leads, inquiries, staff).
- `GET /dashboard/receptionist`: Receptionist metrics (calls today, open inquiries, recent activity, pending handoffs).
- `GET /dashboard/sales`: Sales rep metrics (my leads, conversion rate, my open tasks).

---

## 8. Appointment & Calendar Endpoints (Stage 7)

- `GET /appointments/availability`: Checks operating status and staff availability for a date.
- `GET /appointments/available-slots`: Discovers open, conflict-free appointment time slots for a date.
- `POST /appointments/book`: Atomically books an appointment.
  - **Collision Prevention**: PostgreSQL GiST exclusion constraint (`btree_gist` + `tstzrange`) guarantees zero double-bookings.
  - **Body**:
    ```json
    {
      "customer_id": "...",
      "employee_id": "...",
      "start_time": "2026-11-27T10:00:00Z",
      "end_time": "2026-11-27T10:30:00Z",
      "meeting_type": "Sales Discovery Call",
      "purpose": "Discuss cloud security requirements"
    }
    ```
- `GET /appointments`: Lists organization appointments with date and status filters (Receptionist / Admin).
- `GET /appointments/my-calendar`: Read-only calendar of appointments assigned to the authenticated sales employee.
- `GET /appointments/{id}`: Retrieves appointment details.
- `POST /appointments/{id}/reschedule`: Reschedules appointment to a new conflict-free slot.
- `POST /appointments/{id}/cancel`: Cancels appointment with cancellation reason.

---

## 9. System Health & Diagnostic Endpoints (Stage 9)

### `GET /health/live`
Application liveness probe returning 200 OK if the process is up.

### `GET /health/ready`
Multi-component readiness probe validating backend dependencies:
- **Database**: PostgreSQL connection status and query latency in ms.
- **Redis**: Live connection active or automatic local development fallback engaged.
- **AI Provider**: Active provider name and configured model.
- **Voice Engine**: Active STT and TTS provider configuration.
- **Status Codes**: `200 OK` when ready; `503 Service Unavailable` if database is down.
