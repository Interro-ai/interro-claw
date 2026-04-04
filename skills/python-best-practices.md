---
name: python-best-practices
description: Python coding standards and best practices
applies_to: BackendAgent, RefactorAgent, TestAgent, SecurityAgent
priority: 10
---

# Python Best Practices

## Code Style
- Follow PEP 8 conventions
- Use type hints for all function signatures
- Use `from __future__ import annotations` for forward references
- Prefer f-strings over `.format()` or `%` formatting

## Async Patterns
- Use `async/await` for I/O-bound operations
- Use `asyncio.gather()` for concurrent async operations
- Never mix sync and async code in the same function

## Error Handling
- Use specific exception types, avoid bare `except:`
- Always log exceptions with context
- Use `raise ... from exc` for exception chaining

## Security
- Never hard-code secrets; use environment variables
- Validate and sanitize all user input
- Use parameterized queries for databases
- Pin dependencies to exact versions in production

## Performance
- Use generators for large datasets
- Use `lru_cache` for expensive pure functions
- Profile before optimizing — measure first
