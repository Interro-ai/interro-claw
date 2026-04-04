---
name: ui-ux-design
description: UI/UX design principles, accessibility, design systems, and interaction patterns
applies_to: FrontendAgent, ArchitectAgent, RefactorAgent
priority: 12
---

# UI/UX Design Principles

## Core Principles

- **Consistency** — use the same patterns, colors, spacing, and interactions throughout
- **Hierarchy** — visual weight guides attention: size, color, contrast, spacing
- **Feedback** — every action should have a visible, immediate response
- **Affordance** — interactive elements should look interactive (buttons look clickable)
- **Progressive disclosure** — show essentials first, reveal complexity on demand

## Layout & Spacing

- Use an 8px grid system for all spacing (4px for tight areas)
- Max content width: 1200px for readability
- Minimum touch target: 44x44px (mobile), 32x32px (desktop)
- Use consistent margin/padding scales: 4, 8, 12, 16, 24, 32, 48, 64px

## Color & Typography

- Limit to 2-3 primary colors + neutrals
- Ensure WCAG AA contrast ratios (4.5:1 for text, 3:1 for large text)
- Use a type scale: 12, 14, 16, 20, 24, 32, 40px
- Line height: 1.5 for body text, 1.2 for headings
- Max line length: 60-80 characters for readability

## Component Design Patterns

- **Cards** — group related content, use consistent border-radius and shadow
- **Forms** — labels above inputs, inline validation, clear error states
- **Modals** — use sparingly, always with backdrop + close button + escape key
- **Tables** — sortable headers, sticky columns on mobile, pagination > 50 rows
- **Navigation** — breadcrumbs for depth > 2, tabs for parallel content
- **Loading** — skeleton screens over spinners, progressive loading for lists

## Responsive Design

- Mobile-first approach (min-width breakpoints)
- Breakpoints: 480px (phone), 768px (tablet), 1024px (desktop), 1440px (wide)
- Stack layouts vertically on mobile, use grid on desktop
- Hide non-essential UI on mobile, never hide navigation
- Test on real devices, not just browser resize

## Accessibility (WCAG 2.1 AA)

- All images need descriptive alt text
- Keyboard navigation for ALL interactive elements
- Focus indicators must be visible (never `outline: none` without replacement)
- Screen reader support: ARIA labels, live regions, landmark roles
- Color must not be the only way to convey information
- Support reduced motion (`prefers-reduced-motion`)
- Form inputs need associated labels (not just placeholders)

## Interaction Patterns

- **Optimistic UI** — show success immediately, rollback on failure
- **Debounce** search inputs (300ms), throttle scroll handlers
- **Empty states** — always design for zero-data state with helpful CTA
- **Error states** — explain what happened, suggest next steps, never show stack traces
- **Confirmation** — destructive actions require explicit confirmation (not just undo)
- **Autosave** — for long forms, save progress automatically

## Design System Integration

- Use established component libraries (Radix, Shadcn, MUI, Ant Design)
- Create design tokens for colors, spacing, typography, shadows
- Document component variants, states, and usage guidelines
- Keep icons consistent (same set: Lucide, Heroicons, or Phosphor)

## Performance-Aware UI

- Lazy-load images and off-screen content
- Use virtual scrolling for lists > 100 items
- Skeleton loading for above-the-fold content
- Keep bundle size under 200KB gzipped for initial load
- Measure and optimize Cumulative Layout Shift (CLS < 0.1)
