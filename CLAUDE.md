# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BehindBarsPulse is an automated Italian-language newsletter about the Italian prison system and justice reform. It combines RSS feed processing with LLM-based content generation (Google Gemini API) to produce daily and weekly newsletters with narrative continuity, distributed via AWS SES.

## Running the Project

```bash
# Install dependencies
uv sync

# Collect and enrich articles (updates narrative context)
uv run python -m behind_bars_pulse collect

# Generate newsletter (daily, archives without sending)
uv run python -m behind_bars_pulse generate

# Generate for a specific date
uv run python -m behind_bars_pulse generate --date 2026-01-07 --days-back 7

# Send weekly digest to subscribers
uv run python -m behind_bars_pulse weekly
uv run python -m behind_bars_pulse weekly --dry-run  # Preview without sending

# Run tests
uv run pytest

# Check code quality
uv run ruff check src/ tests/
uv run ruff format --check .
uvx ty check src/
```

**Prerequisites:**
- Python 3.13+
- `.env` file with `GEMINI_API_KEY` for AI features
- `.env` file with `ses_usr` and `ses_pwd` for AWS SES SMTP authentication

## Architecture

```
RSS Feeds → Fetch/Extract → Enrich (AI) → Extract Stories/Characters
                                                ↓
                                      Narrative Context (JSON)
                                                ↓
                                   [DB + Embeddings if configured]
                                                ↓
Generate Press Review (AI) → Generate Content (AI) → Review (AI) → Render → Send
```

### Project Structure

```
BehindBarsPulse/
├── pyproject.toml           # Project config, dependencies
├── previous_issues/         # Archived newsletters (AI context)
├── data/
│   ├── narrative_context.json    # Story/character tracking
│   └── collected_articles/       # Daily article collections
├── src/behind_bars_pulse/
│   ├── __main__.py          # CLI entry point
│   ├── config.py            # Pydantic Settings
│   ├── models.py            # Article, NewsletterContent, PressReview
│   ├── collector.py         # Daily article collection + DB save
│   ├── ai/
│   │   ├── service.py       # AIService (Gemini structured output)
│   │   └── prompts.py       # System prompts
│   ├── narrative/
│   │   ├── models.py        # StoryThread, KeyCharacter, FollowUp
│   │   └── storage.py       # JSON persistence
│   ├── newsletter/
│   │   └── generator.py     # Pipeline orchestration
│   ├── db/                  # Optional database layer
│   │   ├── models.py        # SQLAlchemy ORM (with pgvector)
│   │   ├── session.py       # Async session management
│   │   └── migrations/      # Alembic migrations
│   ├── services/
│   │   └── newsletter_service.py  # DB + embeddings
│   └── email/
│       ├── sender.py        # SMTP/SES + archiving
│       └── templates/       # Jinja2 templates
└── tests/
```

### Core Components

| Module | Purpose |
|--------|---------|
| `collector.py` | Article collection, enrichment, narrative extraction, DB save |
| `ai/service.py` | Gemini API with structured output (JSON schema validation) |
| `ai/prompts.py` | System prompts for all AI tasks |
| `narrative/models.py` | StoryThread, KeyCharacter, FollowUp Pydantic models |
| `newsletter/generator.py` | Pipeline orchestration |
| `email/sender.py` | Rendering, archiving, SMTP delivery |
| `services/newsletter_service.py` | Embedding generation, DB persistence |

### AI Pipeline (ai/service.py)

Uses **Gemini structured output** with `response_json_schema` for guaranteed valid JSON:

1. **`enrich_articles()`** - Extracts author, source, summary
2. **`extract_stories()`** - Identifies ongoing narrative threads
3. **`extract_entities()`** - Identifies key characters and positions
4. **`detect_followups()`** - Identifies upcoming events to track
5. **`generate_press_review()`** - Categorizes articles with **integrated editorial commentary** (cites sources by name, synthesizes perspectives)
6. **`generate_newsletter_content()`** - Title, subtitle, opening/closing
7. **`review_newsletter_content()`** - Style polish

### Narrative Memory System

Tracks continuity across issues:

- **StoryThread**: Ongoing narratives (e.g., "Decreto Carceri") with keywords, impact scores
- **KeyCharacter**: Important figures with evolving positions
- **FollowUp**: Upcoming events and deadlines

Stored in `data/narrative_context.json`, automatically updated during collection.

### Embeddings (pgvector)

When DB is configured, articles are saved with 768-dimension embeddings using `text-multilingual-embedding-002`:

**Future Use Cases:**
- **RAG**: Retrieve historical context for AI commentary
- **Deduplication**: Skip near-duplicate articles across days
- **Related Articles**: "See also" suggestions
- **Story Detection**: Cluster related articles into threads
- **Trend Analysis**: Track topic evolution over time
- **Chatbot**: Answer questions about past coverage

## Configuration (config.py)

All settings via Pydantic Settings, loaded from `.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `gemini_api_key` | (required) | Gemini API key |
| `gemini_model` | `gemini-3-flash-preview` | Primary model |
| `embedding_model` | `text-multilingual-embedding-002` | Embedding model (768d) |
| `ai_sleep_between_calls` | `30` | Rate limiting (seconds) |
| `feed_url` | `ristretti.org` | RSS feed URL |
| `max_articles` | `100` | Max articles to fetch |
| `database_url` | (optional) | PostgreSQL connection string |

## Key Design Decisions

- **Structured Output**: Gemini's `response_json_schema` eliminates JSON parsing errors
- **Integrated Editorial**: Press review comments synthesize sources by name, not just list summaries
- **Closing Quote**: Newsletter ends with Voltaire-attributed quote on prisons and civilization
- **Auto DB Save**: Collector saves to DB with embeddings when configured, gracefully skips if not
- **Issue Date in Filenames**: Previews use issue date to avoid overwriting (e.g., `20260107_issue_preview.html`)

## Deployment

### Docker Build (Mac → Cloud Run)

On Mac, use `docker buildx` for cross-platform builds targeting linux/amd64:

```bash
# Build and push to GCR (use buildx on Mac for linux/amd64)
docker buildx build --platform linux/amd64 \
  -t gcr.io/playground-maroffo/behindbars:latest \
  --push .

# Deploy to Cloud Run
gcloud run deploy behindbars-prod \
  --image gcr.io/playground-maroffo/behindbars:latest \
  --region europe-west1 \
  --project playground-maroffo
```

### Database Migrations

**IMPORTANT:** Migrations CANNOT be run locally against Cloud SQL. Always use the `/api/migrate` endpoint after deploying new code with schema changes.

```bash
# After deploying code with new migrations:
curl -X POST "https://behindbars.news/api/migrate?admin_token=YOUR_GEMINI_API_KEY"
```

**Deployment workflow with migrations:**
1. Commit and push code (including new migration files)
2. Build and push Docker image
3. Deploy to Cloud Run
4. Call `/api/migrate` endpoint to apply migrations
5. Verify the app works

The local `.env` uses `DB_HOST=localhost`, which connects to a local PostgreSQL, NOT Cloud SQL. Never try to run `alembic upgrade` locally expecting it to affect production.

### Admin API Endpoints

Protected by `admin_token` (= GEMINI_API_KEY):

| Endpoint | Description |
|----------|-------------|
| `POST /api/migrate?admin_token=...` | Run Alembic migrations on Cloud SQL |
| `POST /api/regenerate?admin_token=...&collection_date=2026-01-07&days_back=3` | Regenerate newsletter |
| `POST /api/bulletin-admin?admin_token=...&issue_date=2026-02-04` | Regenerate bulletin |
| `POST /api/import-newsletters?admin_token=...` | Import newsletters from GCS |

## Language Note

All generated content (prompts and outputs) is in Italian. Comments and code are in English.
