# Training API

A self-hosted workout tracking API with an Apple Watch training queue. Store workout history, query analytics, and queue structured workouts for delivery to Apple Watch via WorkoutKit.

Built with FastAPI, PostgreSQL, and SQLAlchemy. Includes an optional MCP (Model Context Protocol) server for AI assistant integration.

## Features

- **Workout storage** — CRUD API for workouts with activity type, distance, duration, heart rate, splits, and arbitrary JSONB data
- **Analytics** — Summary endpoints with aggregation by week, month, or year
- **Training queue** — Queue structured workouts (intervals, warmup/cooldown, pace alerts) for sync to Apple Watch via an iOS companion app
- **Workout actions** — Edit or delete workouts already synced to Apple Watch via pending action queue
- **Device inventory** — Track what workouts are currently on the user's Apple Watch
- **Missed workout feedback** — Record and query feedback when users miss scheduled workouts, with pattern detection for coaching
- **MCP server** — Let AI assistants query your training data and create workouts via natural language

## Quick Start

### Prerequisites

- Docker and Docker Compose

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/training-api.git
cd training-api
cp backend/config/.env.example backend/config/.env
```

Edit `backend/config/.env` and set a random `API_KEY`:

```ini
DATABASE_URL=postgresql+psycopg://training-api:training-api@db:5432/training-api
API_KEY=your-secret-api-key-here
ENVIRONMENT=LOCAL
```

### 2. Start

```bash
make up        # or: docker compose up -d
```

The API will be available at `http://localhost:8001`. Database migrations run automatically on startup.

### 3. Verify

```bash
curl http://localhost:8001/api/health
```

## API

All endpoints (except health) require a `Bearer` token in the `Authorization` header matching the `API_KEY` you configured.

### Workouts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/workouts` | Create or upsert a workout |
| `GET` | `/api/workouts` | List workouts (filters: `activity_type`, `start_after`, `start_before`, `limit`, `offset`) |
| `GET` | `/api/workouts/summary` | Aggregated stats by period (`week`/`month`/`year`) and activity type |
| `GET` | `/api/workouts/{id}` | Get workout detail |
| `GET` | `/api/workouts/{id}/splits` | Get per-split breakdown |
| `GET` | `/api/workouts/{id}/heartrate` | Get heart rate samples |
| `DELETE` | `/api/workouts/{id}` | Delete a workout |

### Training Queue

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/queue` | Queue a structured workout |
| `GET` | `/api/queue` | List queue items (filter by `status`) |
| `GET` | `/api/queue/pending` | List pending items |
| `PATCH` | `/api/queue/{id}/status` | Update item status (`pending` / `fetched` / `completed`) |
| `DELETE` | `/api/queue/{id}` | Delete a queue item |
| `GET` | `/api/workouts/queue` | App-facing: get pending workouts as WorkoutKit compositions |
| `DELETE` | `/api/workouts/queue/{id}` | App-facing: remove item after sync |

### Workout Actions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/workouts/actions` | List pending edit/delete actions |
| `POST` | `/api/workouts/actions` | Create an edit or delete action |
| `POST` | `/api/workouts/actions/batch` | Create multiple actions at once |
| `DELETE` | `/api/workouts/actions/{id}` | Acknowledge a processed action |

### Device Inventory

| Method | Endpoint | Description |
|--------|----------|-------------|
| `PUT` | `/api/workouts/inventory` | Sync full on-device workout snapshot (idempotent replace) |
| `GET` | `/api/workouts/inventory` | Get stored inventory |

### Missed Workout Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/workouts/feedback` | Record feedback for a missed workout (upsert by `workoutId`) |
| `GET` | `/api/workouts/feedback` | Retrieve feedback history (filters: `since`, `limit`, `action`) |

## MCP Server (optional)

The `mcp/` directory contains a [FastMCP](https://github.com/jlowin/fastmcp) server that exposes training data to AI assistants (e.g., Claude).

### Setup

```bash
cd mcp
cp config/.env.example config/.env
```

Edit `mcp/config/.env` — set `TRAINING_API_KEY` to match the backend's `API_KEY`:

```ini
TRAINING_API_URL=http://localhost:8001
TRAINING_API_KEY=your-secret-api-key-here
```

### Run

```bash
uv run start
```

Or configure it in your MCP client (e.g., Claude Desktop) as a stdio transport.

## Development

```bash
make up       # Start containers
make down     # Stop containers
make build    # Rebuild images
make logs     # Tail container logs
make migrate  # Run database migrations manually

# Create a new migration after changing models
make create_migration m="add new column"
```

### Project Structure

```
├── docker-compose.yml          # PostgreSQL + API orchestration
├── Makefile                    # Dev shortcuts
├── backend/
│   ├── Dockerfile              # Multi-stage Python 3.13 build
│   ├── pyproject.toml          # Dependencies (uv/hatch)
│   ├── config/.env.example     # Environment template
│   ├── app/
│   │   ├── main.py             # FastAPI app
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── auth.py             # Bearer token auth
│   │   ├── database.py         # SQLAlchemy setup
│   │   ├── models/             # ORM models
│   │   ├── routes/             # API endpoints
│   │   └── schemas/            # Pydantic request/response models
│   └── migrations/             # Alembic migrations
└── mcp/
    ├── pyproject.toml          # MCP dependencies
    ├── config/.env.example     # MCP environment template
    └── app/
        ├── main.py             # FastMCP server
        ├── tools/              # MCP tool definitions
        └── services/           # API client
```

## License

MIT
