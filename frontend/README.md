# React frontend

React + TypeScript + Vite, React Router, Radix Themes (light jade/slate theme).
FastAPI and the native Codex/OpenCode integrations remain on the host. There is
no Node process or Docker dependency in a normal installation: FastAPI serves
the committed production bundle from `src/agent_web/ui` alongside `/api/v1`.

## Development

Node 22.12+ (or 20.19+) is needed only to develop/build the frontend:

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
```

Vite runs on port 5173 and proxies HTTP and WebSocket `/api` requests to the
native backend at `127.0.0.1:8765`. Start that backend with the root start script.
Production uses one origin and one port, with no CORS configuration needed.

```sh
npm run build --prefix frontend
npm exec --prefix frontend -- playwright install chromium
npm test --prefix frontend
```

Commit the rebuilt `src/agent_web/ui` with every frontend change. This makes
clones, Python wheels and Git updates work without npm on the destination.
Vite owns this directory; do not edit generated assets manually. Hashed assets
are served under `/assets`; the HTML entry point is revalidated on reload.

## Navigation and updates

- `/`: project chooser; `/projects/:projectId`: conversations in one project.
- `/projects/:projectId/chats/:sessionId`: focused, refreshable chat.
- `/projects/:projectId/chats/new`: draft; a session is created on first submit.
- Missing/archived chats return to the chooser with an explanation.
- Navigation is a modal drawer with focus trapping, Escape dismissal and full
  chat width on mobile. All persistent changes use the existing REST API.
- `useChat` owns connection cleanup, exponential reconnect, visibility/online
  recovery and a five-second persisted-history fallback. Cumulative stream
  events are reconciled by turn ID with authoritative history, never appended
  as duplicate deltas. Old requests are aborted on chat changes.
- Markdown continues to use the backend's existing safe renderer. User text
  and filenames are rendered by React as text. Cline stays read-only.

Three Playwright scenarios cover navigation/reload, live/reconnect/error, and
mobile/new-chat behavior against controlled REST/WebSocket responses. They
do not spend model tokens. Native-agent acceptance is checked separately in
the real browser. Voice recognition depends on browser support and a secure
context (localhost or HTTPS); plain LAN HTTP may not allow a microphone.
