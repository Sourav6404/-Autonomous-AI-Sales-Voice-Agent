# FortiSales AI – Scalability & Security Architecture

## 1. Concurrency Engineering & Capacity Analysis

The architecture of **FortiSales AI** is engineered around asynchronous, non-blocking I/O using Python 3.11 `asyncio` and `uvloop`. System load is mathematically decomposed into distinct operational tiers:

1. **Registered Users Across Tenants**:
   - Total user entities stored in PostgreSQL across all tenant organizations.
   - Database storage footprint: $100,000 \times \sim 1\text{ KB} \approx 100\text{ MB}$ (standard relational storage).
2. **Daily Active Users (DAU $\approx 10,000 - 15,000$)**:
   - Staff members logging into role-based workspaces (`admin-dashboard`, `receptionist-dashboard`, `sales-dashboard`).
   - Peak REST API traffic: $\sim 50 - 150\text{ requests/sec}$, comfortably handled by a single Uvicorn instance.
3. **Concurrent Active Voice Calls ($C_{calls}$)**:
   - Simultaneous live voice calls actively processed by the system.
   - For an SMB/Enterprise deployment: **50 to 200 concurrent active calls** during peak hours.
4. **Concurrent WebSocket Connections ($W_{conns}$)**:
   - Inbound AudioWorklet voice streams: $1 \times C_{calls}$.
   - Live receptionist monitoring connections: $\sim 20 - 50$ staff connections.
5. **Concurrent Audio & AI Operations**:
   - Speech interactions are half-duplex: at any given moment, $\sim 40\%$ callers are speaking (streaming STT), $\sim 40\%$ AI is speaking (streaming TTS), $\sim 15\%$ LLM is generating tokens, and $\sim 5\%$ silence / VAD deliberation.

### Audio Bandwidth & Throughput for 100 Concurrent Calls:
- **Audio Framing**:
  - Uncompressed linear PCM 16kHz 16-bit mono = $256\text{ kbps} = 32\text{ KB/s}$ per channel.
  - 100 concurrent bidirectional calls $\times 32\text{ KB/s} \times 2 = 6.4\text{ MB/s} = 51.2\text{ Mbps}$ network throughput.
- **FastAPI / Uvicorn Capacity**:
  - Python `asyncio` maintains thousands of concurrent WebSockets with low memory overhead ($\sim 40\text{ KB}$ per idle socket).
  - Bounded 250-frame ring buffers per call prevent memory leaks during slow consumer connections.

---

## 2. Multi-Tenant Isolation Architecture

```mermaid
flowchart TD
    Request[Incoming HTTP / WebSocket Request] --> AuthDep[get_current_user Dependency]
    AuthDep --> JWTVal[Validate JWT Signature & Scrypt Hash]
    JWTVal --> ExtractOrg[Extract org_id Claim]
    ExtractOrg --> BindContext[Bind TenantContext: contextvars.ContextVar]

    BindContext --> QueryLayer[SQLAlchemy 2.0 / Vector Query Layer]
    QueryLayer --> ScopedQuery["SELECT ... WHERE org_id = TenantContext.get_current_tenant_id()"]

    ScopedQuery --> Response[Generate Response]
    Response --> ClearContext[Middleware: TenantContext.clear()]
```

### Three-Layer Tenant Isolation:
1. **Model Layer (`TenantMixin`)**:
   - Every operational model inherits from `TenantMixin`, defining an indexed `org_id: Mapped[UUID]` foreign key referencing `organizations.id` with `ondelete="CASCADE"`.
2. **Context Layer (`TenantContext`)**:
   - Built on Python's async-safe `contextvars.ContextVar`.
   - The authentication dependency extracts `org_id` from the cryptographically signed JWT and binds it to the current coroutine context.
   - Bounded queries retrieve data only for the authenticated tenant. Client requests cannot supply an arbitrary `org_id` parameter to access another tenant's data.
   - Global HTTP and WebSocket cleanup middleware guarantees that `TenantContext.clear()` executes on every disconnect or exception.
3. **Vector Layer (`pgvector`)**:
   - Vector chunks in `knowledge_chunks` have an explicit `org_id` column.
   - Vector similarity queries execute:
     $$\min_{\vec{v}} \left( \vec{v} \cdot \vec{q} \right) \quad \text{subject to} \quad \text{org\_id} = \text{TenantContext.get\_current\_tenant\_id()}$$
     Cross-tenant vector retrieval is impossible.

---

## 3. Cryptographic Security & RBAC Guardrails

### 1. Password Hashing (Scrypt RFC 7914)
- User passwords are never stored in plaintext.
- Passwords use Scrypt with unique per-user salts ($N=16384, r=8, p=1$), offering robust resistance against ASIC and GPU rainbow-table attacks.

### 2. JWT Access & Refresh Token Security
- Access tokens have a short lifespan (1 hour) signed with a 256-bit secret key.
- Refresh tokens use single-use rotation: redeeming a refresh token issues a new access/refresh pair and invalidates the previous token.

### 3. Ephemeral Single-Use Voice Tickets
- Standard browser WebSockets do not support sending custom `Authorization` HTTP headers.
- FortiSales AI implements a single-use 256-bit ticket handshake:
  1. Client sends authenticated HTTPS request: `POST /api/v1/voice/tickets`.
  2. Server generates a cryptographically secure token (`tkt_...`), hashes it with SHA-256, and stores it in Redis with a 30-second TTL.
  3. Client opens `ws://.../voice/stream?ticket=tkt_...`.
  4. Server computes the SHA-256 hash and executes an atomic Redis `GETDEL`. If missing or expired, the socket closes with code `4401 Unauthorized`.
  5. The Origin header is validated against authorized origins (`4403 Forbidden` if untrusted).

### 4. Role-Based Access Control (RBAC) Matrix
- `owner` / `super_admin`: Full tenant administrative privileges.
- `admin`: Business hours, service catalog, employee management, and org-wide metrics.
- `receptionist`: Front-desk operations, appointment scheduling, customer directory, inquiries, and live handoff queue takeover.
- `sales_employee`: Strictly isolated access to their own assigned leads, inquiries, and personal read-only calendar. Accessing another rep's lead returns `403 Forbidden`.

---

## 4. Concurrency Protection & Race Condition Prevention

### PostgreSQL GiST Exclusion Constraints (`btree_gist`)
To prevent concurrent double-booking of appointments under simultaneous multi-threaded requests, FortiSales AI enforces an exclusion constraint at the database engine level:

```sql
ALTER TABLE appointments
ADD CONSTRAINT no_overlapping_appointments
EXCLUDE USING gist (
    employee_id WITH =,
    tstzrange(start_time, end_time, '[)') WITH &&
)
WHERE (status IN ('scheduled', 'confirmed'));
```

- **Application Revalidation**: `BookingService` executes a conflict check immediately prior to inserting.
- **Storage Engine Serialization**: If two concurrent requests attempt to book the identical slot simultaneously, the PostgreSQL GiST index serializes the write and raises an `IntegrityError` on the second transaction, which the service catches and surfaces as a clean `409 Conflict`.

---

## 5. Scope Realignment: Local vs Cloud Architecture

| Capability | Current Implemented Status | Future Cloud Roadmap |
| :--- | :--- | :--- |
| **Hosting Environment** | Local Workstations & Private Servers (Windows, macOS, Linux) | AWS ECS / EKS Cloud Cluster |
| **Process Management** | Uvicorn ASGI server with multi-worker support | Containerized Kubernetes Pods & Horizontal Pod Autoscaler |
| **Distributed Caching** | Local Redis 7+ with automatic in-memory fallback | Managed AWS ElastiCache Redis Cluster |
| **Voice Streaming Gateway** | WebSocket Voice Gateway on FastAPI with AudioWorklet | Cloudflare / Nginx SSL Reverse Proxy with WSS Load Balancing |
| **External Telephony** | Browser AudioWorklet voice console (`/voice-console`) | Direct Twilio / SIP Trunk carrier integration |
| **Notifications** | Live Receptionist Portal Queue & Inquiry Tickets | Twilio SMS, WhatsApp Business API, mobile push |
