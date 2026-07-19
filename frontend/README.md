# Loopback — Training Dashboard

Authenticated React dashboard for the training-api backend. Replaces the old
unauthenticated server-rendered dashboard (disabled for security).

- **Stack:** React 19 + TypeScript, Vite 8, React Compiler, TanStack Query,
  react-router, hand-rolled SVG charts, Leaflet (lazy chunk) for route maps.
- **Design:** implements `Training Dashboard.dc.html` from the claude.ai/design
  project.
- **Serving:** built `dist/` is baked into the backend Docker image at
  `/app/static` and served same-origin by FastAPI (no CORS, Funnel unchanged).

## Development

```bash
npm install
npm run dev        # Vite on :5173, proxies /api → localhost:8001
npx tsc -b         # typecheck
npm run build      # production build (also runs inside the Docker build)
```

## Notes

- `src/lib/types.ts` mirrors the API's wire casing **exactly** — it is
  intentionally inconsistent per resource (see CLAUDE.md). Don't normalize it.
- Auth: bearer token in localStorage (`loopback.*`); any 401 wipes local auth
  and returns to the login screen. Login is rate-limited 5/min/IP.
- The route map fetches CARTO dark tiles — the app's only external dependency.
