---
name: e2e_testing
description: Playwright E2E testing patterns including Page Object Model, configuration, CI/CD integration, and flaky test strategies
alwaysLoad: false
---

# E2E Testing Patterns

Comprehensive Playwright patterns for building stable, fast, and maintainable E2E test suites.

## When to Use

- Setting up Playwright E2E tests
- Building Page Object Models for test organization
- Configuring multi-browser test runs
- Debugging flaky tests
- Integrating E2E tests with CI/CD

## Test File Organization

```
tests/
  e2e/
    auth/
      login.spec.ts
      register.spec.ts
    features/
      browse.spec.ts
      search.spec.ts
  fixtures/
    auth.ts
    data.ts
  playwright.config.ts
```

## Page Object Model

```typescript
import { Page, Locator } from '@playwright/test'

export class ItemsPage {
  readonly page: Page
  readonly searchInput: Locator
  readonly itemCards: Locator

  constructor(page: Page) {
    this.page = page
    this.searchInput = page.locator('[data-testid="search-input"]')
    this.itemCards = page.locator('[data-testid="item-card"]')
  }

  async goto() {
    await this.page.goto('/items')
    await this.page.waitForLoadState('networkidle')
  }

  async search(query: string) {
    await this.searchInput.fill(query)
    await this.page.waitForResponse(r => r.url().includes('/api/search'))
  }

  async getItemCount() {
    return await this.itemCards.count()
  }
}
```

## Test Structure

```typescript
import { test, expect } from '@playwright/test'
import { ItemsPage } from '../../pages/ItemsPage'

test.describe('Item Search', () => {
  let itemsPage: ItemsPage

  test.beforeEach(async ({ page }) => {
    itemsPage = new ItemsPage(page)
    await itemsPage.goto()
  })

  test('should search by keyword', async () => {
    await itemsPage.search('test')
    const count = await itemsPage.getItemCount()
    expect(count).toBeGreaterThan(0)
  })

  test('should handle no results', async ({ page }) => {
    await itemsPage.search('xyznonexistent123')
    await expect(page.locator('[data-testid="no-results"]')).toBeVisible()
  })
})
```

## Configuration

```typescript
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['junit', { outputFile: 'playwright-results.xml' }]
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
  },
})
```

## Fixing Flaky Tests

### Common Causes and Fixes

**Race conditions:**
```typescript
// Bad: assumes element ready
await page.click('[data-testid="button"]')

// Good: auto-wait locator
await page.locator('[data-testid="button"]').click()
```

**Network timing:**
```typescript
// Bad: arbitrary timeout
await page.waitForTimeout(5000)

// Good: wait for specific condition
await page.waitForResponse(r => r.url().includes('/api/data'))
```

**Animation timing:**
```typescript
await page.locator('[data-testid="menu"]').waitFor({ state: 'visible' })
await page.waitForLoadState('networkidle')
await page.locator('[data-testid="menu"]').click()
```

### Quarantine Flaky Tests
```typescript
test('flaky: complex flow', async ({ page }) => {
  test.fixme(true, 'Flaky - Issue #123')
})
```

### Identify Flakiness
```bash
npx playwright test tests/search.spec.ts --repeat-each=10
```

## Artifacts

```typescript
// Screenshots
await page.screenshot({ path: 'artifacts/result.png' })
await page.screenshot({ path: 'artifacts/full.png', fullPage: true })

// Element screenshot
await page.locator('[data-testid="chart"]').screenshot({ path: 'artifacts/chart.png' })
```

## CI/CD Integration

```yaml
name: E2E Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npx playwright install --with-deps
      - run: npx playwright test
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
```

## Key Practices

- Use `data-testid` attributes for stable selectors
- Never use arbitrary timeouts -- wait for specific conditions
- Keep tests independent (each sets up its own data)
- Use Page Object Model for maintainability
- Capture artifacts on failure for debugging
- Run tests in parallel for speed
