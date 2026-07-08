---
name: backend_patterns
description: Backend architecture patterns for APIs, databases, caching, error handling, auth, rate limiting, and background jobs
alwaysLoad: false
---

# Backend Development Patterns

Architecture patterns and best practices for scalable server-side applications.

## When to Use

- Designing REST or GraphQL API endpoints
- Implementing repository, service, or controller layers
- Optimizing database queries (N+1, indexing, connection pooling)
- Adding caching (Redis, in-memory, HTTP cache headers)
- Setting up background jobs or async processing
- Building middleware (auth, logging, rate limiting)

## Repository Pattern

```typescript
interface Repository<T> {
  findAll(filters?: Filters): Promise<T[]>
  findById(id: string): Promise<T | null>
  create(data: CreateDto): Promise<T>
  update(id: string, data: UpdateDto): Promise<T>
  delete(id: string): Promise<void>
}
```

Abstract data access from business logic. Swap implementations without changing services.

## Service Layer Pattern

```typescript
class ItemService {
  constructor(private repo: ItemRepository) {}

  async search(query: string, limit = 10): Promise<Item[]> {
    // Business logic here
    const results = await this.repo.findByQuery(query, limit)
    return results.sort((a, b) => b.score - a.score)
  }
}
```

Business logic separated from data access and HTTP concerns.

## Middleware Pattern

```typescript
export function withAuth(handler: Handler): Handler {
  return async (req, res) => {
    const token = req.headers.authorization?.replace('Bearer ', '')
    if (!token) return res.status(401).json({ error: 'Unauthorized' })
    try {
      req.user = await verifyToken(token)
      return handler(req, res)
    } catch {
      return res.status(401).json({ error: 'Invalid token' })
    }
  }
}
```

## Database Patterns

### Query Optimization
- Select only needed columns, not `*`
- Use appropriate indexes
- Limit result sets

### N+1 Prevention
```typescript
// BAD: N queries
for (const item of items) {
  item.author = await getUser(item.authorId)  // N queries
}

// GOOD: Batch fetch
const authorIds = items.map(i => i.authorId)
const authors = await getUsers(authorIds)  // 1 query
const authorMap = new Map(authors.map(a => [a.id, a]))
items.forEach(i => { i.author = authorMap.get(i.authorId) })
```

### Transactions
Use database transactions for operations that must succeed or fail together.

## Caching Strategies

### Cache-Aside Pattern
```typescript
async function getItem(id: string): Promise<Item> {
  const cached = await cache.get(`item:${id}`)
  if (cached) return JSON.parse(cached)

  const item = await db.items.findById(id)
  if (item) await cache.setex(`item:${id}`, 300, JSON.stringify(item))
  return item
}
```

Always invalidate cache on writes.

## Error Handling

### Centralized Error Handler
```typescript
class ApiError extends Error {
  constructor(public statusCode: number, message: string) {
    super(message)
  }
}

function errorHandler(error: unknown): Response {
  if (error instanceof ApiError) {
    return json({ error: error.message }, { status: error.statusCode })
  }
  if (error instanceof ValidationError) {
    return json({ error: 'Validation failed', details: error.errors }, { status: 400 })
  }
  console.error('Unexpected:', error)
  return json({ error: 'Internal server error' }, { status: 500 })
}
```

### Retry with Exponential Backoff
```typescript
async function fetchWithRetry<T>(fn: () => Promise<T>, maxRetries = 3): Promise<T> {
  for (let i = 0; i < maxRetries; i++) {
    try { return await fn() }
    catch (err) {
      if (i < maxRetries - 1) {
        await new Promise(r => setTimeout(r, Math.pow(2, i) * 1000))
      } else throw err
    }
  }
}
```

## Authentication and Authorization

### JWT Validation
Verify tokens, check expiry, extract user claims. Always use environment variables for secrets.

### Role-Based Access Control
```typescript
const rolePermissions = {
  admin: ['read', 'write', 'delete', 'admin'],
  moderator: ['read', 'write', 'delete'],
  user: ['read', 'write']
}

function hasPermission(user, permission) {
  return rolePermissions[user.role].includes(permission)
}
```

## Rate Limiting

Track requests per identifier (IP or user) within a time window. Return 429 when exceeded with Retry-After header.

## Background Jobs

Use a queue pattern for expensive operations:
- Add job to queue instead of blocking the request
- Process asynchronously
- Handle failures with retries

## Structured Logging

```typescript
const entry = {
  timestamp: new Date().toISOString(),
  level: 'info',
  message: 'Request processed',
  requestId: crypto.randomUUID(),
  method: 'GET',
  path: '/api/items'
}
```

Log structured JSON. Include request IDs for tracing. Never log secrets or sensitive data.

## Key Principles

- Choose patterns that fit your complexity level
- Start simple, add layers as needed
- Repository + Service pattern scales well for most applications
- Cache reads, invalidate on writes
- Always handle errors at the boundary
- Log everything you need for debugging, nothing sensitive
