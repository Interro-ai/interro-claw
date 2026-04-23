---
name: devops-cicd
description: DevOps, CI/CD pipelines, containerization, and infrastructure operations
applies_to: OpsAgent, ArchitectAgent, BackendAgent
priority: 12
---

# DevOps & CI/CD Best Practices

## CI/CD Pipeline Design

```
Code Push → Lint & Format → Unit Tests → Build → Integration Tests → Security Scan → Deploy Staging → E2E Tests → Deploy Production
```

### Pipeline Principles

- Fail fast: cheapest checks first (lint → unit test → build → integration)
- Immutable artifacts: build once, deploy the same artifact to all environments
- Deterministic builds: pin all dependency versions, use lockfiles
- Pipeline as code: `.github/workflows/`, `azure-pipelines.yml`, `Jenkinsfile`
- Secrets via pipeline secrets manager (never in repo, never in env files)

## Packaging & Deployment Targets

Choose the packaging strategy based on the deployment target — do NOT default to Docker.

### When to use Docker

- Multi-service architectures needing orchestration (docker-compose, Kubernetes)
- Custom OS-level dependencies that can't be satisfied by managed services
- User explicitly requests Docker/container deployment
- Need for identical dev/staging/prod environments

### When NOT to use Docker

- Simple Python CLI tools → use pyproject.toml + pip install
- Static websites → use CDN / Azure Static Web Apps / Vercel
- Mobile apps → use native build systems (Gradle, Xcode)
- Desktop apps → use platform installers (MSI, AppImage, DMG)
- Serverless functions → use Azure Functions / AWS Lambda config
- Libraries → use package registries (PyPI, npm, NuGet)

### Platform-Specific Packaging

| Target           | Packaging                            | Distribution                |
| ---------------- | ------------------------------------ | --------------------------- |
| Python app / CLI | pyproject.toml + `[project.scripts]` | `pip install` or PyPI       |
| .NET app         | .csproj + `dotnet publish`           | Self-contained exe or NuGet |
| Android          | build.gradle + signing config        | APK/AAB → Play Store        |
| iOS              | Xcode project + Fastlane             | IPA → App Store             |
| Windows desktop  | WiX / Inno Setup / MSIX              | MSI installer or winget     |
| Linux desktop    | AppImage / snap / flatpak / .deb     | Package manager             |
| Web app (static) | Build script (vite, webpack)         | CDN or Static Web Apps      |
| Web app (server) | Procfile or systemd unit             | App Service or VM           |
| Docker           | Dockerfile + docker-compose          | Container registry          |
| Serverless       | function.json / SAM template         | Azure Functions / Lambda    |

## Containerization (Docker)

> **Only generate Docker artifacts when the deployment target is "docker" or containers are clearly needed.**

- Use multi-stage builds to minimize image size
- Base on official slim images (`python:3.12-slim`, `node:20-alpine`)
- Run as non-root user inside container
- Use `.dockerignore` to exclude dev files, tests, docs
- Pin base image digests for reproducible builds
- Health checks in Dockerfile: `HEALTHCHECK CMD curl -f http://localhost:8080/health`
- One process per container (use orchestration for multi-process)

### Example Dockerfile Pattern

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY . .
USER nobody
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## Infrastructure as Code

- **Bicep** (Azure-native): recommended for Azure workloads
- **Terraform** (multi-cloud): recommended for multi-cloud or AWS/GCP
- **Pulumi** (programmatic): recommended when team prefers real code over DSL
- Always use modules/templates for reusable components
- Separate environments with parameter files, not branches
- Use remote state with locking (Azure Storage, S3+DynamoDB)
- Plan before apply: always review `terraform plan` / `bicep what-if`

## Environment Strategy

- **Development** — local Docker Compose or dev containers
- **Staging** — mirrors production (same infra, smaller scale)
- **Production** — full scale, monitoring, alerting
- Use feature flags (LaunchDarkly, Azure App Configuration) over branches
- Database migrations must be backward-compatible (expand-contract pattern)

## Monitoring & Alerting

- **Four Golden Signals**: latency, traffic, errors, saturation
- Set up alerts: error rate > 1%, p99 latency > 2s, CPU > 80%
- Use dashboards for real-time visibility (Grafana, Azure Monitor)
- Log aggregation with structured JSON logs (correlation IDs)
- Distributed tracing for request flow (OpenTelemetry)
- Cost monitoring: set budget alerts, review weekly

## Deployment Strategies

- **Rolling update** (default): gradually replace instances
- **Blue/Green**: switch traffic between two identical environments
- **Canary**: route small % of traffic to new version, validate, then expand
- **Feature flags**: deploy dark, enable for specific users first
- Always have rollback plan: previous image tag, database backup point

## Security in CI/CD

- Scan dependencies on every build (Dependabot, Snyk, pip-audit)
- Static analysis in pipeline (bandit, semgrep, ESLint security rules)
- Container image scanning (Trivy, Azure Defender)
- Sign artifacts and verify signatures
- Rotate service credentials regularly
- Principle of least privilege for CI/CD service accounts
