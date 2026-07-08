---
name: coding_standards
description: Universal coding standards and best practices for TypeScript, JavaScript, React, and Node.js development
alwaysLoad: false
---

# Coding Standards and Best Practices

Universal coding standards applicable across projects with TypeScript, JavaScript, React, and Node.js.

## When to Use

- Starting a new project or module
- Reviewing code for quality
- Refactoring to follow conventions
- Enforcing naming, formatting, or structure
- Onboarding new contributors

## Core Principles

### 1. Readability First
Code is read more than written. Clear names, self-documenting code, consistent formatting.

### 2. KISS (Keep It Simple)
Simplest solution that works. No over-engineering. No premature optimization.

### 3. DRY (Don't Repeat Yourself)
Extract common logic. Create reusable components. Share utilities.

### 4. YAGNI (You Aren't Gonna Need It)
Don't build features before they're needed. Start simple, refactor when required.

## Naming Conventions

```typescript
// Variables: descriptive camelCase
const searchQuery = 'election'
const isAuthenticated = true

// Functions: verb-noun pattern
async function fetchData(id: string) { }
function calculateSimilarity(a: number[], b: number[]) { }
function isValidEmail(email: string): boolean { }

// Constants: UPPER_SNAKE_CASE
const MAX_RETRIES = 3
const DEBOUNCE_DELAY_MS = 500
```

## TypeScript Best Practices

```typescript
// Use proper types, not 'any'
interface Item {
  id: string
  name: string
  status: 'active' | 'resolved' | 'closed'
  created_at: Date
}

// Immutability: use spread operator
const updated = { ...item, name: 'New Name' }
const updatedArray = [...items, newItem]
// NEVER: item.name = 'New' or items.push(newItem)
```

## Error Handling

```typescript
async function fetchData(url: string) {
  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    return await response.json()
  } catch (error) {
    console.error('Fetch failed:', error)
    throw new Error('Failed to fetch data')
  }
}
```

## Async/Await

```typescript
// Parallel when possible
const [users, items, stats] = await Promise.all([
  fetchUsers(),
  fetchItems(),
  fetchStats()
])

// NOT sequential when unnecessary
```

## React Best Practices

### Component Structure
```typescript
interface ButtonProps {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  variant?: 'primary' | 'secondary'
}

export function Button({ children, onClick, disabled = false, variant = 'primary' }: ButtonProps) {
  return (
    <button onClick={onClick} disabled={disabled} className={`btn btn-${variant}`}>
      {children}
    </button>
  )
}
```

### State Updates
```typescript
// Functional update for state based on previous
setCount(prev => prev + 1)  // GOOD
setCount(count + 1)          // BAD: can be stale
```

### Conditional Rendering
```typescript
{isLoading && <Spinner />}
{error && <ErrorMessage error={error} />}
{data && <DataDisplay data={data} />}
```

### Memoization
```typescript
const sorted = useMemo(() => items.sort(...), [items])
const handler = useCallback((q: string) => setQuery(q), [])
```

## Input Validation

```typescript
import { z } from 'zod'

const CreateSchema = z.object({
  name: z.string().min(1).max(200),
  description: z.string().min(1).max(2000),
  endDate: z.string().datetime(),
})

// Validate before processing
const validated = CreateSchema.parse(body)
```

## File Organization

```
src/
  app/           # Routes and pages
  components/    # React components
    ui/          # Generic UI
    forms/       # Form components
  hooks/         # Custom hooks
  lib/           # Utilities and configs
  types/         # TypeScript types
  styles/        # Global styles
```

## Comments

```typescript
// GOOD: Explain WHY, not WHAT
// Use exponential backoff to avoid overwhelming the API during outages
const delay = Math.min(1000 * Math.pow(2, retryCount), 30000)

// BAD: Stating the obvious
// Increment counter
count++
```

## Code Smells to Avoid

1. **Long functions** (>50 lines) -- split into smaller functions
2. **Deep nesting** (5+ levels) -- use early returns
3. **Magic numbers** -- use named constants
4. **Copy-paste code** -- extract to shared utilities
5. **Using `any` type** -- define proper interfaces

## Testing

```typescript
// AAA Pattern: Arrange, Act, Assert
test('calculates similarity correctly', () => {
  const v1 = [1, 0, 0]
  const v2 = [0, 1, 0]
  const result = calculateSimilarity(v1, v2)
  expect(result).toBe(0)
})

// Descriptive names
test('returns empty array when no items match query', () => { })
test('throws error when API key is missing', () => { })
```

## Key Principle

Code quality is not negotiable. Clear, maintainable code enables rapid development and confident refactoring.
