---
name: frontend_patterns
description: Frontend development patterns for React, Next.js, state management, performance optimization, and accessible UI
alwaysLoad: false
---

# Frontend Development Patterns

Modern frontend patterns for React, Next.js, and performant user interfaces.

## When to Use

- Building React components (composition, props, rendering)
- Managing state (useState, useReducer, Zustand, Context)
- Implementing data fetching (SWR, React Query, server components)
- Optimizing performance (memoization, virtualization, code splitting)
- Working with forms (validation, controlled inputs)
- Building accessible, responsive UI

## Component Patterns

### Composition Over Inheritance
```typescript
export function Card({ children, variant = 'default' }: CardProps) {
  return <div className={`card card-${variant}`}>{children}</div>
}

export function CardHeader({ children }) {
  return <div className="card-header">{children}</div>
}

// Usage
<Card>
  <CardHeader>Title</CardHeader>
  <CardBody>Content</CardBody>
</Card>
```

### Compound Components
Use React Context to share state between related components (Tabs, Accordion, etc.) without prop drilling.

### Render Props
```typescript
export function DataLoader<T>({ url, children }: {
  url: string
  children: (data: T | null, loading: boolean, error: Error | null) => ReactNode
}) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    fetch(url).then(r => r.json()).then(setData).catch(setError).finally(() => setLoading(false))
  }, [url])

  return <>{children(data, loading, error)}</>
}
```

## Custom Hooks

### Toggle Hook
```typescript
export function useToggle(initial = false): [boolean, () => void] {
  const [value, setValue] = useState(initial)
  const toggle = useCallback(() => setValue(v => !v), [])
  return [value, toggle]
}
```

### Debounce Hook
```typescript
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}
```

### Data Fetching Hook
```typescript
export function useQuery<T>(key: string, fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(false)

  const refetch = useCallback(async () => {
    setLoading(true)
    try { setData(await fetcher()) }
    catch (e) { setError(e as Error) }
    finally { setLoading(false) }
  }, [fetcher])

  useEffect(() => { refetch() }, [key])
  return { data, error, loading, refetch }
}
```

## State Management

### Context + Reducer
For shared state across components, combine useReducer with Context. Define typed actions and a reducer function, wrap with a Provider.

### When to Use What
- **useState:** Simple local state
- **useReducer:** Complex local state with multiple actions
- **Context:** State needed by many components
- **Zustand/Jotai:** Global state with performance needs

## Performance

### Memoization
```typescript
const sorted = useMemo(() => items.sort(...), [items])
const handler = useCallback((q: string) => setQuery(q), [])
const MemoCard = React.memo(({ item }) => <div>{item.name}</div>)
```

### Code Splitting
```typescript
const HeavyChart = lazy(() => import('./HeavyChart'))

<Suspense fallback={<Skeleton />}>
  <HeavyChart data={data} />
</Suspense>
```

### Virtualization for Long Lists
Use `@tanstack/react-virtual` for lists with hundreds+ items. Only render visible rows plus a small overscan buffer.

## Form Handling

- Use controlled inputs with state
- Validate with schema libraries (Zod)
- Show inline errors
- Break long forms into steps with progress indicators
- Use appropriate input types for mobile keyboards

## Error Boundaries

```typescript
class ErrorBoundary extends React.Component {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallback error={this.state.error} onRetry={() => this.setState({ hasError: false })} />
    }
    return this.props.children
  }
}
```

## Accessibility

### Keyboard Navigation
Handle ArrowDown, ArrowUp, Enter, Escape for dropdowns and menus. Use proper ARIA roles (`combobox`, `listbox`, `dialog`).

### Focus Management
Save focus before opening modals, restore on close. Use `tabIndex={-1}` for programmatic focus targets.

## Animation

Use Framer Motion for declarative animations:
- `initial`, `animate`, `exit` for mount/unmount
- `AnimatePresence` for exit animations
- `motion.div` for animated elements

## Key Principle

Choose patterns that fit your project complexity. Start simple, add layers when the complexity demands it.
