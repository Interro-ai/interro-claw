---
name: frontend-standards
description: Frontend development standards for React and Next.js
applies_to: FrontendAgent, RefactorAgent
priority: 10
---

# Frontend Development Standards

## React / Next.js
- Use functional components with hooks exclusively
- Prefer `useReducer` over `useState` for complex state
- Implement error boundaries for graceful failure handling
- Use React.memo and useMemo for expensive computations

## TypeScript
- Enable strict mode in tsconfig.json
- Define interfaces for all component props
- Use discriminated unions for state management
- Avoid `any` type — use `unknown` when type is uncertain

## Accessibility
- All images must have alt text
- Use semantic HTML elements (nav, main, article, etc.)
- Ensure keyboard navigation for all interactive elements
- Test with screen readers (NVDA, VoiceOver)

## Performance
- Lazy-load routes and heavy components
- Optimize images with next/image or WebP
- Use Lighthouse scores as quality gates (target 90+)
- Implement code splitting at route boundaries

## Testing
- Unit tests with React Testing Library (not Enzyme)
- E2E tests with Playwright for critical user flows
- Test accessibility with axe-core
