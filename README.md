# BehindBarsPulse

**BehindBarsPulse** is an automated Italian-language newsletter about the Italian prison system and justice reform. It combines RSS feed processing with LLM-based content generation to produce daily bulletins and weekly digests with narrative continuity.

## Features

- **Il Bollettino (Daily)**: Automated daily editorial commentary on prison news, generated at 8:00 AM with thematic press review categories
- **Digest Settimanale (Weekly)**: Weekly digest sent to subscribers via email, synthesizing daily bulletins into narrative arcs
- **Narrative Memory System**: Tracks ongoing stories, key characters, and follow-up events across issues
- **Statistics Dashboard**: Prison incident visualization (suicides, assaults, protests) and capacity data by facility/region
- **Semantic Search**: pgvector-powered search across articles and editorial content
- **AI-Powered Content**: Google Gemini for article summarization, categorization, and editorial commentary
- **Facility Normalization**: Deduplicates prison name variations for accurate statistics
- **Structured Output**: Gemini's `response_json_schema` guarantees valid JSON, eliminating parsing errors

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.13 |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| AI/LLM | Google Gemini 3 (Vertex AI) |
| Database | PostgreSQL 16 + pgvector |
| Web Framework | FastAPI + Jinja2 |
| Data Validation | Pydantic v2 |
| Email Delivery | AWS SES (SMTP) |
| Infrastructure | Terraform (GCP Cloud Run + Cloud SQL) |
| Logging | structlog |
| Testing | pytest |

## Installation

```bash
# Clone the repository
git clone https://github.com/maroffo/BehindBarsPulse.git
cd BehindBarsPulse

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Required Environment Variables

```bash
# Google Cloud (Vertex AI)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# AWS SES
ses_usr=your-ses-username
ses_pwd=your-ses-password
```

## Local Development with Docker

The easiest way to run the full stack locally:

```bash
# Start database
docker compose up -d db

# Run migrations
docker compose --profile migrate up migrate

# Start web app (builds image)
docker compose up -d --build

# View logs
docker compose logs -f web

# Stop everything
docker compose down

# Reset database
docker compose down -v
```

The web app will be available at http://localhost:8000

## Usage

BehindBarsPulse provides CLI commands and scheduled Cloud Run endpoints:

```bash
# Collect and enrich articles (run daily, e.g., 6:00 AM)
# Saves to DB with embeddings if configured
uv run python -m behind_bars_pulse collect

# Generate and send weekly digest (run weekly, e.g., Sunday 8:00 AM)
# Reads daily bulletins from DB for the past week
uv run python -m behind_bars_pulse weekly
uv run python -m behind_bars_pulse weekly --dry-run

# View narrative context status
uv run python -m behind_bars_pulse status
```

Daily bulletins are generated via Cloud Scheduler calling `POST /api/bulletin` (OIDC-authenticated).

### CLI Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview without sending email |
| `--date YYYY-MM-DD` | Reference date for collection or digest |

### Typical Workflow

1. **Daily collection** (Cloud Scheduler, 6:00 AM)
   - Fetches RSS feed, enriches articles with AI
   - Extracts stories, characters, follow-ups into narrative context
   - Saves articles to DB with embeddings

2. **Daily bulletin** (Cloud Scheduler, 8:00 AM)
   - Generates press review with thematic categories from collected articles
   - Generates editorial commentary using narrative context
   - Saves bulletin to DB, publishes on web at `/bollettino/`

3. **Weekly digest** (Cloud Scheduler, Sunday)
   - Loads past 7 days of daily bulletins from DB
   - Synthesizes major narrative arcs
   - Sends to subscribers via email (AWS SES)

## Architecture

```
RSS Feed → Fetch → Enrich (AI) → Extract Stories/Characters
                                        ↓
                              Narrative Context (JSON)
                                        ↓
Daily Bulletin:  Press Review (AI) → Editorial (AI) → Review (AI) → DB → Web
Weekly Digest:   Bulletins from DB → Synthesize (AI) → Render (Jinja2) → Email (SES)
```

### Project Structure

```
BehindBarsPulse/
├── src/behind_bars_pulse/
│   ├── __main__.py          # CLI entry point
│   ├── config.py            # Pydantic Settings
│   ├── models.py            # Core data models
│   ├── collector.py         # Daily article collection
│   ├── ai/
│   │   ├── service.py       # Gemini AI service
│   │   └── prompts.py       # System prompts
│   ├── db/                  # Database layer
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   ├── session.py       # Async session management
│   │   ├── repository.py    # Data access layer
│   │   └── migrations/      # Alembic migrations
│   ├── web/                 # Web frontend
│   │   ├── app.py           # FastAPI application
│   │   ├── routes/          # API routes
│   │   ├── templates/       # Jinja2 templates
│   │   └── static/          # CSS/JS assets
│   ├── services/            # Business logic
│   │   ├── newsletter_service.py  # DB persistence + embeddings
│   │   └── wayback_service.py     # Wayback Machine archival
│   ├── narrative/
│   │   ├── models.py        # StoryThread, KeyCharacter, FollowUp
│   │   ├── storage.py       # JSON persistence
│   │   └── matching.py      # Story matching logic
│   ├── newsletter/
│   │   ├── generator.py     # Legacy daily newsletter pipeline
│   │   └── weekly.py        # Weekly digest (from daily bulletins)
│   ├── feeds/
│   │   └── fetcher.py       # RSS fetching
│   └── email/
│       ├── sender.py        # SMTP/SES delivery
│       └── templates/       # Jinja2 templates
├── infra/                   # Terraform IaC
│   ├── modules/             # Reusable modules
│   │   ├── cloud_run/       # Cloud Run service
│   │   ├── cloud_sql/       # PostgreSQL + pgvector
│   │   ├── networking/      # VPC + connectors
│   │   ├── secrets/         # Secret Manager
│   │   └── storage/         # GCS buckets
│   └── environments/        # dev/prod configs
├── data/                    # Runtime data
│   ├── narrative_context.json
│   └── collected_articles/
├── previous_issues/         # Archived newsletter previews
├── docker-compose.yml       # Local development
├── Dockerfile               # Container image
└── tests/
```

## Web Frontend

The web frontend at `behindbars.news` provides:

- **Home**: Project overview with latest bollettino
- **Il Bollettino**: Daily AI-generated editorial commentary with thematic press review categories
- **Edizioni**: Browse past bulletins by date
- **Articles**: Searchable article database with semantic search (pgvector)
- **Statistics**: Prison incident dashboard with charts (by type, region, facility) and capacity data
- **Search**: HTMX-powered instant search across articles and editorial content

### Semantic Search

Articles are embedded using Vertex AI's `text-multilingual-embedding-002` model (768 dimensions, optimized for Italian). Search queries find semantically similar articles, not just keyword matches.

## Narrative Memory System

The narrative memory system tracks:

- **Story Threads**: Ongoing narratives (e.g., "Decreto Carceri" legislative process) with impact scores and mention counts
- **Key Characters**: Important figures with their roles and evolving positions
- **Follow-ups**: Upcoming events and deadlines to monitor

This enables daily bulletins and weekly digests to:
- Reference previous coverage: *"Come abbiamo seguito nelle ultime settimane..."*
- Track story evolution: *"Il Ministro Nordio, che la settimana scorsa aveva dichiarato X, oggi..."*
- Alert readers to upcoming events: *"Ricordiamo che domani è previsto..."*

## Embedding Use Cases (Future)

Articles are embedded using Vertex AI's `text-multilingual-embedding-002` model (768 dimensions, optimized for Italian). Planned applications:

| Use Case | Description |
|----------|-------------|
| **RAG** | Retrieve historical context before generating AI commentary |
| **Deduplication** | Skip near-duplicate articles across days (cosine similarity > 0.95) |
| **Related Articles** | "See also" suggestions based on semantic similarity |
| **Story Detection** | Cluster related articles into narrative threads automatically |
| **Trend Analysis** | Track topic evolution over time via embedding drift |
| **Chatbot** | Q&A interface over historical coverage |

## Development

```bash
# Run tests
uv run pytest

# Code quality checks
uv run ruff check src/ tests/
uv run ruff format .
uvx ty check src/

# Full validation
uv run ruff check . && uv run ruff format --check . && uvx ty check src/ && uv run pytest
```

## Project Goals

1. **AI Experimentation**: Explore LLM capabilities for automated journalism and content curation
2. **Awareness**: Highlight challenges in the Italian prison system and justice reform
3. **Narrative Continuity**: Demonstrate how AI can maintain editorial memory across publications

## License

This project is for personal use. Licensing details will be added as the project develops.

---

*BehindBarsPulse is inspired by a commitment to technology and social justice. Developed with care in Geremeas, Sardinia.*
