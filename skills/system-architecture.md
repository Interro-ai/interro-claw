---
name: system-architecture
description: System architecture patterns, scalability, cloud-native design, and technical decision-making
applies_to: ArchitectAgent, OpsAgent, BackendAgent
priority: 15
---

# System Architecture Patterns

## Architectural Decision Framework

When making architecture decisions, evaluate:

1. **Requirements** — functional, non-functional (latency, throughput, availability)
2. **Scale** — current users, projected growth, data volume
3. **Team** — team size, skill set, operational maturity
4. **Constraints** — budget, timeline, compliance, existing infrastructure
5. **Trade-offs** — document what you're trading off and why (use ADRs)

## Architecture Patterns

### Monolith (default for < 10 developers)

- Start here unless you have specific microservice requirements
- Use modular monolith: feature folders, clean boundaries, shared database
- Can extract to microservices later when pain points emerge

### Microservices (when you need independent scaling/deployment)

- Each service owns its data (database per service)
- Communicate via async messaging (events) > sync HTTP
- API Gateway for external clients (rate limiting, auth, routing)
- Service mesh for internal communication (mTLS, observability)

### Event-Driven Architecture

- Use event sourcing for audit-critical domains (financial, healthcare)
- Event bus: Azure Service Bus, Kafka, or RabbitMQ
- CQRS: separate read and write models for high-traffic reads
- Ensure idempotent consumers (events may be delivered more than once)

## Cloud-Native Design Principles

- Design for failure: everything will fail, plan for it
- Use managed services over self-hosted when possible
- Containers for workloads, serverless for glue code
- Infrastructure as Code: Bicep, Terraform, or Pulumi — never manual changes
- 12-Factor App methodology for configuration, logging, statelessness

## Data Architecture

- Choose storage by access pattern:
  - Relational (PostgreSQL) — structured data, complex queries, transactions
  - Document (Cosmos DB, MongoDB) — flexible schema, horizontal scale
  - Key-value (Redis) — caching, sessions, rate limiting
  - Search (Elasticsearch) — full-text search, analytics
  - Object (Blob Storage) — files, images, backups
- Data flows: define clear boundaries for data ownership
- Implement data versioning for APIs and schemas

## Scalability Patterns

- **Horizontal scaling** — stateless services behind load balancers
- **Read replicas** — for read-heavy workloads
- **Sharding** — partition data by tenant/region for massive scale
- **Caching** — CDN + application cache + database cache
- **Queue-based load leveling** — absorb traffic spikes with message queues
- **Bulkhead pattern** — isolate failure domains (separate pools/services)

## Reliability & Resilience

- Target SLA: 99.9% (8.7h downtime/year), 99.99% (52min/year)
- Implement circuit breakers on all external calls
- Retry with exponential backoff + jitter
- Health checks: liveness (am I running?) + readiness (can I serve traffic?)
- Graceful degradation: disable non-critical features under load
- Chaos engineering: regularly test failure scenarios

## Security Architecture

- Zero trust: verify every request, assume breach
- Defense in depth: multiple security layers
- Least privilege: minimal permissions for every service/user
- Network segmentation: private subnets for data, public for frontends
- Secrets management: never in code, always in vault (Azure Key Vault)
- Encrypt at rest and in transit (TLS 1.3)

## Folder Structure (Recommended)

```
project/
├── src/
│   ├── api/          # Controllers/routes
│   ├── services/     # Business logic
│   ├── models/       # Data models/schemas
│   ├── repositories/ # Data access layer
│   ├── middleware/    # Auth, logging, error handling
│   ├── events/       # Event handlers/publishers
│   └── utils/        # Shared utilities
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── infra/            # IaC (Bicep, Terraform)
├── docs/             # Architecture Decision Records
└── scripts/          # Build, deploy, seed scripts
```

## Documentation Requirements

- Architecture Decision Records (ADRs) for every significant choice
- System diagram (C4 model: Context, Container, Component, Code)
- API documentation (OpenAPI/Swagger)
- Runbook for operational procedures
- Data flow diagrams for compliance-sensitive paths
