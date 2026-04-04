---
name: backend-architecture
description: Backend API design, database patterns, microservices, and performance
applies_to: BackendAgent, ArchitectAgent, RefactorAgent
priority: 12
---

# Backend Architecture & API Design

## API Design (REST)

- Use resource-oriented URLs: `/api/v1/users/{id}/orders`
- HTTP methods map to CRUD: GET=read, POST=create, PUT/PATCH=update, DELETE=remove
- Always version APIs: `/api/v1/`, `/api/v2/`
- Return consistent response envelopes: `{"data": ..., "meta": ..., "errors": [...]}`
- Use HTTP status codes correctly: 200=OK, 201=Created, 400=Bad Request, 401=Unauthorized, 404=Not Found, 409=Conflict, 422=Unprocessable, 500=Server Error
- Implement pagination: `?page=1&limit=20` with `Link` headers or cursor-based
- Support filtering: `?status=active&created_after=2024-01-01`
- Rate limit all endpoints, return `429` with `Retry-After` header

## Database Patterns

- Use connection pooling (never open/close per request)
- Parameterize ALL queries — never interpolate user input into SQL
- Add indexes for frequently filtered/sorted columns
- Use database migrations (Alembic for SQLAlchemy, Prisma Migrate, etc.)
- Implement soft deletes for user data (`deleted_at` timestamp)
- Use transactions for multi-step operations
- Denormalize for read-heavy workloads, normalize for write-heavy

## Service Layer Pattern

```
Controller/Route → Service → Repository → Database
     ↓                ↓           ↓
  Validation     Business     Data Access
  Serialization  Logic        Queries
```

- Keep controllers thin (validate + delegate)
- Services contain business logic, are testable without HTTP
- Repositories abstract database access (switchable backends)

## Authentication & Authorization

- Use JWT for stateless auth (short expiry: 15min access, 7d refresh)
- Store refresh tokens server-side (database/Redis)
- Hash passwords with bcrypt (cost factor 12) or argon2
- Implement role-based access control (RBAC) with middleware
- Use API keys for service-to-service communication
- Never expose internal IDs in URLs without authorization checks

## Error Handling

- Use structured error responses: `{"code": "VALIDATION_ERROR", "message": "...", "details": [...]}`
- Map internal exceptions to HTTP status codes at the controller level
- Log full stack traces server-side, return sanitized messages to clients
- Implement global exception handlers (FastAPI exception_handler, Express error middleware)
- Use circuit breakers for external service calls

## Caching Strategy

- Cache at multiple levels: CDN → API Gateway → Application → Database
- Use Redis/Memcached for application cache
- Set appropriate TTLs based on data volatility
- Implement cache invalidation on writes (write-through or write-behind)
- Use ETags for HTTP-level caching

## Async & Background Jobs

- Use task queues for long-running operations (Celery, Bull, Temporal)
- Return 202 Accepted for async operations with a status endpoint
- Implement idempotency keys for retry-safe operations
- Use WebSockets or SSE for real-time updates (not polling)

## Observability

- Structured logging with correlation IDs (trace every request end-to-end)
- Metrics: request latency (p50, p95, p99), error rates, throughput
- Distributed tracing for microservice architectures (OpenTelemetry)
- Health check endpoints: `/health` (liveness) and `/ready` (readiness)

## Performance

- Use async I/O for all database and HTTP calls
- Implement request timeouts (30s max for user-facing, 5min for background)
- Batch database operations where possible
- Use connection pooling with appropriate pool sizes
- Profile before optimizing — measure, don't guess
