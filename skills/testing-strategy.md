---
name: testing-strategy
description: Testing strategy and best practices for E2E and integration tests
applies_to: TestAgent, BackendAgent, FrontendAgent
priority: 10
---

# Testing Strategy

## Testing Pyramid

1. **Unit tests** (70%) — fast, isolated, mock external dependencies
2. **Integration tests** (20%) — test service interactions, use test containers
3. **E2E tests** (10%) — test critical user flows end-to-end

## Python Testing

- Framework: pytest with fixtures and parametrize
- Async: pytest-asyncio for async code
- Mocking: unittest.mock or pytest-mock
- Coverage: pytest-cov with 80% minimum threshold
- API testing: httpx + TestClient for FastAPI

## Frontend Testing

- Unit: React Testing Library + Jest/Vitest
- Component: Storybook for visual testing
- E2E: Playwright (preferred) or Cypress
- Accessibility: axe-core integration

## Test Organization

- Mirror source structure: `tests/test_<module>.py`
- Use descriptive test names: `test_<what>_<condition>_<expected>`
- Group related tests in classes
- Use fixtures for common setup/teardown

## CI Integration

- Run all tests on every PR
- Block merge on test failure
- Report coverage to PR comments
- Run E2E tests nightly (they're slow)
