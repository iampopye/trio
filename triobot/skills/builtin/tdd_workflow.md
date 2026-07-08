---
name: tdd_workflow
description: Test-driven development workflow with unit, integration, and E2E testing patterns targeting 80%+ coverage
alwaysLoad: false
---

# Test-Driven Development Workflow

Follow TDD principles with comprehensive test coverage across unit, integration, and E2E tests.

## When to Use

- Writing new features or functionality
- Fixing bugs
- Refactoring existing code
- Adding API endpoints
- Creating new components

## Core Principles

### 1. Tests BEFORE Code
Always write tests first, then implement code to make them pass.

### 2. Coverage Requirements
- Minimum 80% coverage (unit + integration + E2E)
- All edge cases covered
- Error scenarios tested
- Boundary conditions verified

### 3. Test Types

**Unit Tests:** Individual functions, component logic, pure functions, utilities
**Integration Tests:** API endpoints, database operations, service interactions
**E2E Tests (Playwright):** Critical user flows, complete workflows, UI interactions

## TDD Workflow

### Step 1: Write User Stories
```
As a [role], I want to [action], so that [benefit]
```

### Step 2: Generate Test Cases
```typescript
describe('Search', () => {
  it('returns relevant results for query', async () => { })
  it('handles empty query gracefully', async () => { })
  it('falls back when service unavailable', async () => { })
  it('sorts by relevance score', async () => { })
})
```

### Step 3: Run Tests (They Should Fail)
```bash
npm test  # All red -- nothing implemented yet
```

### Step 4: Implement Minimal Code
Write just enough to make tests pass.

### Step 5: Run Tests Again
```bash
npm test  # All green
```

### Step 6: Refactor
Improve code quality while keeping tests green. Remove duplication, improve naming, optimize.

### Step 7: Verify Coverage
```bash
npm run test:coverage  # Confirm 80%+
```

## Testing Patterns

### Unit Tests (Jest/Vitest)
```typescript
import { render, screen, fireEvent } from '@testing-library/react'

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByText('Click me')).toBeInTheDocument()
  })

  it('calls onClick', () => {
    const handler = jest.fn()
    render(<Button onClick={handler}>Click</Button>)
    fireEvent.click(screen.getByRole('button'))
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
```

### API Integration Tests
```typescript
describe('GET /api/items', () => {
  it('returns items', async () => {
    const response = await GET(new NextRequest('http://localhost/api/items'))
    const data = await response.json()
    expect(response.status).toBe(200)
    expect(Array.isArray(data.data)).toBe(true)
  })

  it('validates query params', async () => {
    const response = await GET(new NextRequest('http://localhost/api/items?limit=invalid'))
    expect(response.status).toBe(400)
  })
})
```

### E2E Tests (Playwright)
```typescript
test('user can search and filter', async ({ page }) => {
  await page.goto('/')
  await page.fill('input[placeholder="Search"]', 'test')
  await page.waitForResponse(r => r.url().includes('/api/search'))
  const results = page.locator('[data-testid="result-card"]')
  await expect(results.first()).toContainText(/test/i)
})
```

## File Organization

```
src/
  components/
    Button/
      Button.tsx
      Button.test.tsx
  app/api/
    items/
      route.ts
      route.test.ts
tests/e2e/
  search.spec.ts
  auth.spec.ts
```

## Mocking External Services

Mock databases, caches, and external APIs in unit tests to ensure isolation:

```typescript
jest.mock('@/lib/database', () => ({
  db: {
    from: jest.fn(() => ({
      select: jest.fn(() => Promise.resolve({ data: [mockItem], error: null }))
    }))
  }
}))
```

## Common Mistakes

**Test implementation details:**
```typescript
// BAD: testing internal state
expect(component.state.count).toBe(5)
// GOOD: test user-visible behavior
expect(screen.getByText('Count: 5')).toBeInTheDocument()
```

**Brittle selectors:**
```typescript
// BAD
await page.click('.css-xyz')
// GOOD
await page.click('[data-testid="submit"]')
```

**Dependent tests:**
```typescript
// BAD: tests share state
// GOOD: each test sets up its own data
```

## Coverage Thresholds

```json
{
  "coverageThresholds": {
    "global": {
      "branches": 80,
      "functions": 80,
      "lines": 80,
      "statements": 80
    }
  }
}
```

## Best Practices

1. Write tests first (TDD)
2. One assertion per test when practical
3. Descriptive test names explaining what's tested
4. Arrange-Act-Assert structure
5. Mock external dependencies
6. Test edge cases (null, undefined, empty, large)
7. Test error paths, not just happy paths
8. Keep tests fast (unit < 50ms each)
9. Clean up after tests
10. Review coverage reports for gaps

Tests are not optional. They are the safety net that enables confident refactoring and reliable production deployments.
