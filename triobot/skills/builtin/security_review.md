---
name: security_review
description: Security review checklist and patterns for authentication, input validation, secrets management, XSS, CSRF, and API protection
alwaysLoad: false
---

# Security Review

Comprehensive security checklist and patterns for web applications.

## When to Use

- Implementing authentication or authorization
- Handling user input or file uploads
- Creating new API endpoints
- Working with secrets or credentials
- Implementing payment features
- Storing or transmitting sensitive data

## 1. Secrets Management

**Never** hardcode API keys, tokens, or passwords. Always use environment variables.

```typescript
const apiKey = process.env.API_KEY
if (!apiKey) throw new Error('API_KEY not configured')
```

Checklist:
- [ ] No hardcoded secrets in source code
- [ ] `.env.local` in .gitignore
- [ ] No secrets in git history
- [ ] Production secrets in hosting platform

## 2. Input Validation

Always validate with schemas before processing:

```typescript
import { z } from 'zod'

const Schema = z.object({
  email: z.string().email(),
  name: z.string().min(1).max(100),
})

const validated = Schema.parse(input)
```

File uploads: check size limits, allowed types, and extensions. Error messages should not leak internal details.

## 3. SQL Injection Prevention

**Never** concatenate user input into SQL queries. Always use parameterized queries or ORM methods.

```typescript
// GOOD
await db.query('SELECT * FROM users WHERE email = $1', [email])

// BAD
await db.query(`SELECT * FROM users WHERE email = '${email}'`)
```

## 4. Authentication

- Store tokens in httpOnly cookies, not localStorage (XSS vulnerable)
- Set cookies with `HttpOnly; Secure; SameSite=Strict`
- Always verify authorization before sensitive operations
- Implement role-based access control
- Enable Row Level Security in databases

## 5. XSS Prevention

- Sanitize user-provided HTML with libraries like DOMPurify
- Configure Content Security Policy headers
- Use framework built-in protections (React auto-escapes)
- Never use `dangerouslySetInnerHTML` with unsanitized content

## 6. CSRF Protection

- Use CSRF tokens on state-changing operations
- Set `SameSite=Strict` on all cookies
- Verify origin headers on mutations

## 7. Rate Limiting

Apply rate limiting to all API endpoints. Use stricter limits on expensive operations (search, auth, payments).

```typescript
// 100 requests per 15 minutes for general API
// 10 requests per minute for search
// 5 requests per minute for login attempts
```

## 8. Sensitive Data

**Logging:**
- Never log passwords, tokens, card numbers, or secrets
- Redact sensitive fields: `{ email, userId }` not `{ email, password }`

**Error messages:**
- Generic for users: "An error occurred"
- Detailed only in server logs
- Never expose stack traces or SQL errors to clients

## 9. Dependency Security

```bash
npm audit          # Check vulnerabilities
npm audit fix      # Fix automatically
npm outdated       # Check for updates
```

Always commit lock files. Use `npm ci` in CI/CD.

## 10. Security Testing

```typescript
test('requires authentication', async () => {
  const res = await fetch('/api/protected')
  expect(res.status).toBe(401)
})

test('requires admin role', async () => {
  const res = await fetch('/api/admin', {
    headers: { Authorization: `Bearer ${userToken}` }
  })
  expect(res.status).toBe(403)
})

test('rejects invalid input', async () => {
  const res = await fetch('/api/users', {
    method: 'POST',
    body: JSON.stringify({ email: 'not-valid' })
  })
  expect(res.status).toBe(400)
})
```

## Pre-Deployment Checklist

- [ ] No hardcoded secrets
- [ ] All inputs validated
- [ ] SQL queries parameterized
- [ ] User content sanitized (XSS)
- [ ] CSRF protection enabled
- [ ] Proper token handling (httpOnly cookies)
- [ ] Authorization checks in place
- [ ] Rate limiting on all endpoints
- [ ] HTTPS enforced
- [ ] CSP and security headers configured
- [ ] No sensitive data in error responses or logs
- [ ] Dependencies up to date
- [ ] CORS properly configured
- [ ] File uploads validated

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Web Security Academy](https://portswigger.net/web-security)

Security is not optional. One vulnerability can compromise the entire platform.
