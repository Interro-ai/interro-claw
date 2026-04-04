---
name: azure-deployment
description: Azure deployment patterns and best practices
applies_to: OpsAgent, ArchitectAgent
priority: 10
---

# Azure Deployment Best Practices

## Infrastructure as Code
- Prefer Bicep over ARM templates for readability
- Use parameter files for environment-specific values
- Never hard-code resource names; use naming conventions with prefixes
- Tag all resources with environment, owner, and cost center

## App Service / Container Apps
- Use managed identity instead of connection strings where possible
- Enable health checks and auto-scaling
- Configure deployment slots for zero-downtime deployments
- Use Application Insights for monitoring

## CI/CD
- Use GitHub Actions or Azure DevOps Pipelines
- Separate build and deploy stages
- Run tests before deployment
- Use OIDC for authentication (no secrets in pipelines)

## Security
- Enable HTTPS-only and TLS 1.2+
- Use Azure Key Vault for secrets
- Enable Azure Defender / Microsoft Defender for Cloud
- Restrict network access with NSGs and Private Endpoints
