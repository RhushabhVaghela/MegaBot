# MegaBot Dashboard UI

React 19 + TypeScript + Vite frontend for the MegaBot orchestrator.

## Stack

- **React 19** with TypeScript
- **Vite** for dev server and bundling
- **WebSocket** connection to the backend (`ws://localhost:8000/ws`)

## Structure

```
ui/
  src/
    components/    # UI components (ChatPanel, Sidebar, MemoryPanel, etc.)
    hooks/         # Custom hooks (useWebSocket, useMessages)
    types/         # TypeScript type definitions
    App.tsx        # Root component
    main.tsx       # Entry point
```

## Development

```bash
cd ui
npm install
npm run dev        # Starts Vite dev server on http://localhost:5173
```

The dev server proxies API requests to the MegaBot backend at `http://localhost:8000`.

## Build

```bash
npm run build      # Output in ui/dist/
```

## Testing

```bash
npm test
```
