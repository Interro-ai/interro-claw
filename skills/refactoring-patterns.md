---
name: refactoring-patterns
description: Code refactoring patterns, code smells, performance optimization techniques
applies_to: RefactorAgent, BackendAgent, FrontendAgent
priority: 10
---

# Refactoring Patterns & Code Quality

## Code Smells to Fix

- **Long methods** (> 30 lines) — extract to smaller functions
- **Deep nesting** (> 3 levels) — use early returns, extract helpers
- **Duplicate code** — extract shared logic into functions/modules
- **God classes** (> 300 lines, > 10 methods) — split by responsibility
- **Feature envy** — method uses another class's data more than its own
- **Primitive obsession** — use domain types instead of raw strings/ints
- **Shotgun surgery** — one change requires touching many files → centralize
- **Dead code** — remove unused imports, functions, variables, commented-out code

## Refactoring Techniques

### Extract Method

Before: long function doing multiple things
After: small functions with descriptive names, each doing one thing

### Replace Conditional with Polymorphism

Before: `if type == "A": ... elif type == "B": ...`
After: Base class with `process()`, subclasses override

### Introduce Parameter Object

Before: `def create(name, email, phone, address, city, zip)`
After: `def create(user: UserInput)`

### Replace Magic Numbers/Strings

Before: `if status == 3:` or `timeout = 30`
After: `if status == Status.COMPLETED:` or `timeout = REQUEST_TIMEOUT_SECONDS`

### Dependency Injection

Before: `class Service: def __init__(self): self.db = Database()`
After: `class Service: def __init__(self, db: Database): self.db = db`

## Performance Optimization Checklist

1. **Measure first** — profile before optimizing (cProfile, py-spy, Chrome DevTools)
2. **Database queries** — N+1 queries, missing indexes, unnecessary joins
3. **Caching** — cache expensive computations, API responses, database results
4. **Async I/O** — don't block on network/disk operations
5. **Batching** — group database writes, API calls, file operations
6. **Lazy loading** — don't load what you don't need (imports, data, components)
7. **Connection pooling** — reuse database/HTTP connections
8. **Data structures** — use sets for lookups, deques for queues, generators for iteration

## Code Organization Principles

- **Single Responsibility** — each module/class does one thing well
- **DRY** — Don't Repeat Yourself, but don't over-abstract either
- **YAGNI** — You Aren't Gonna Need It — don't build for hypothetical futures
- **Composition over Inheritance** — prefer composing behaviors over class hierarchies
- **Explicit over Implicit** — clear code > clever code

## When NOT to Refactor

- Working code with no upcoming changes
- Code being replaced soon
- Under time pressure without test coverage
- Purely stylistic changes that add churn without value

## Readability Improvements

- Variable names: `user_count` not `n`, `is_valid` not `flag`
- Function names: `calculate_total_price()` not `calc()` or `process()`
- Comments: explain WHY, not WHAT (code should explain what)
- Consistent formatting: use automated formatters (Black, Prettier)
- Group related code: imports, constants, types, functions, classes
