---
name: security-guidelines
description: Application security guidelines and OWASP best practices
applies_to: SecurityAgent, BackendAgent, OpsAgent
priority: 15
---

# Security Guidelines

## OWASP Top 10 Awareness

- A01: Broken Access Control — enforce least privilege at every layer
- A02: Cryptographic Failures — use TLS everywhere, hash passwords with bcrypt/argon2
- A03: Injection — parameterize all queries, escape all output
- A04: Insecure Design — threat model before implementation
- A05: Security Misconfiguration — disable debug mode, remove defaults
- A06: Vulnerable Components — scan dependencies, update regularly
- A07: Authentication Failures — use MFA, secure session management
- A08: Data Integrity Failures — verify signatures, use SRI for CDN assets
- A09: Logging & Monitoring — log security events, alert on anomalies
- A10: SSRF — validate URLs, block internal network access

## Dependency Management

- Run `pip audit` or `npm audit` on every build
- Pin versions in production
- Use Dependabot or Renovate for automated updates
- Review changelogs before major version bumps

## Secrets Management

- NEVER commit secrets to version control
- Use Azure Key Vault, AWS Secrets Manager, or HashiCorp Vault
- Rotate keys regularly
- Use .env.example files (without values) as documentation

## Static Analysis

- Python: bandit, pylint security checks, safety
- JavaScript: eslint-plugin-security, snyk
- General: semgrep, CodeQL
