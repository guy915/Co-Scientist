# Co-Scientist Frontend

React + Vite + TypeScript + Tailwind CSS + shadcn/ui frontend for the Co-Scientist API server.

## Tech Stack

- **Vite** - Build tool and dev server
- **TypeScript** - Type safety
- **Tailwind CSS v4** - Utility-first CSS framework (modern setup, no PostCSS config needed)
- **shadcn/ui** - Component library based on Radix UI
- **Bun** - Package manager and runtime
- **lucide-react** - Icon library
- **date-fns** - Date/time utilities
- **react-markdown** - Markdown rendering

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) installed (v1.0+)
- Node.js 18+ (for compatibility)

### Installation

```bash
# Install dependencies
bun install
```

### Development

```bash
# Start development server
bun run dev
```

The development server will start at http://localhost:5173/

### Build

```bash
# Build for production
bun run build
```

The build output will be in the `dist/` directory.

### Preview Production Build

```bash
# Preview production build locally
bun run preview
```

## Optional Environment Variables
To override default api backend, create a `.env` file in the frontend directory:

```env
VITE_API_BASE_URL=http://localhost:8008
```
localhost:8008  is default.

To change text blurbs to a new non-scientific (non-hypothesis) domain, create your src/domains/<key>.json 
file and add `VITE_DOMAIN` to `.env` file before starting/building UI.

## API Integration

The frontend communicates with the Co-Scientist API backend through:

- **API Client** (`src/api/client.ts`) - REST API functions
- **useSSE Hook** (`src/hooks/useSSE.ts`) - Server-Sent Events for real-time updates

### Key API Functions

- `generateHypotheses()` - Non-streaming hypothesis generation
- `createStreamingURL()` - Create SSE connection for streaming
- `cancelGeneration()` - Cancel ongoing generation
- `checkHealth()` - Check backend health

## Available Components

### Base Components (shadcn/ui)

Currently configured and ready to use:
- Button, Card, Accordion, Badge, Dialog, Progress, etc.

To add more shadcn/ui components:

```bash
bunx shadcn@latest add [component-name]
```

Example:
```bash
bunx shadcn@latest add button
bunx shadcn@latest add card
bunx shadcn@latest add accordion
```

## Custom Hooks

### useSSE

React hook for Server-Sent Events connection:

```typescript
import { useSSE } from '@/hooks/useSSE';

const { status, close } = useSSE({
  url: 'http://localhost:8008/generate/stream',
  onMessage: (event) => {
    const data = JSON.parse(event.data);
    console.log('Received:', data);
  },
  onError: (error) => {
    console.error('SSE Error:', error);
  },
  enabled: true
});
```

## Type Definitions

### Hypothesis

```typescript
interface Hypothesis {
  text: string;
  score: number;
  elo_rating: number;
  reviews: Review[];
  evolution_history: string[];
  win_count: number;
  loss_count: number;
}
```

### AgentOutput

```typescript
interface AgentOutput {
  name: string;
  content: string;
  parsed: any;
  timestamp: number;
  phase?: string;
  iteration?: number;
}
```

See `src/types/` for complete type definitions.

## Styling

### Tailwind CSS v4

Use Tailwind utility classes for styling:

```tsx
<div className="p-4 rounded-lg border">
  <h1 className="text-2xl font-bold">Title</h1>
</div>
```

### CSS Variables & Theme Configuration

Theme colors are defined using the `@theme` directive in `src/index.css`:

```css
@theme {
  --color-background: 0 0% 100%;
  --color-foreground: 0 0% 3.9%;
  --color-primary: 0 0% 9%;
  /* ... more colors */
}
```

All theme variables are prefixed with `--color-` in Tailwind v4. Use them in your styles:

```tsx
<div style={{ backgroundColor: 'hsl(var(--color-background))' }}>
  Content
</div>
```

