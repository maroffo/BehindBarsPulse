# BehindBarsPulse

**BehindBarsPulse** is an automated Italian-language newsletter about the Italian prison system and justice reform. It combines RSS feed processing with LLM-based content generation to produce daily and weekly newsletters with narrative continuity.

## Features

- **Daily Newsletter Generation**: Collects articles from [Ristretti Orizzonti](https://ristretti.org/), enriches them with AI-generated summaries, and produces a curated newsletter
- **Narrative Memory System**: Tracks ongoing stories, key characters, and follow-up events across issues, creating continuity and context
- **Weekly Digest**: Synthesizes the week's coverage into a cohesive summary highlighting major narrative arcs
- **AI-Powered Content**: Uses Google Gemini (via Vertex AI) for article summarization, categorization, and editorial commentary

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.13 |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| AI/LLM | Google Gemini 3 (Vertex AI) |
| Data Validation | Pydantic v2 |
| Email Delivery | AWS SES (SMTP) |
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

## Usage

BehindBarsPulse provides four CLI commands:

```bash
# Collect and enrich articles (run daily, e.g., 6:00 AM)
uv run python -m behind_bars_pulse collect

# Generate and send daily newsletter
uv run python -m behind_bars_pulse generate
uv run python -m behind_bars_pulse generate --dry-run  # Preview without sending

# Generate and send weekly digest (run weekly, e.g., Sunday 8:00 AM)
uv run python -m behind_bars_pulse weekly
uv run python -m behind_bars_pulse weekly --dry-run

# View narrative context status
uv run python -m behind_bars_pulse status
```

### Typical Workflow

1. **Daily collection** (cron: every morning)
   - Fetches RSS feed
   - Enriches articles with AI summaries
   - Extracts and updates narrative context (stories, characters, follow-ups)
   - Saves to `data/collected_articles/`

2. **Daily generation** (cron: after collection)
   - Loads collected articles
   - Uses narrative context for continuity
   - Generates newsletter with AI commentary
   - Sends via email, archives to `previous_issues/`

3. **Weekly digest** (cron: Sunday)
   - Loads past 7 days of archived newsletters
   - Synthesizes major narrative arcs
   - Highlights upcoming events and trends

## Architecture

```
RSS Feed → Fetch → Enrich (AI) → Extract Stories/Characters
                                        ↓
                              Narrative Context (JSON)
                                        ↓
Generate Content (AI) → Review (AI) → Render (Jinja2) → Archive → Send (SES)
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
│   ├── narrative/
│   │   ├── models.py        # StoryThread, KeyCharacter, FollowUp
│   │   ├── storage.py       # JSON persistence
│   │   └── matching.py      # Story matching logic
│   ├── newsletter/
│   │   ├── generator.py     # Daily newsletter pipeline
│   │   └── weekly.py        # Weekly digest generator
│   ├── feeds/
│   │   └── fetcher.py       # RSS fetching
│   └── email/
│       ├── sender.py        # SMTP/SES delivery
│       └── templates/       # Jinja2 templates
├── data/                    # Runtime data
│   ├── narrative_context.json
│   └── collected_articles/
├── previous_issues/         # Archived newsletters
└── tests/
```

## Narrative Memory System

The narrative memory system tracks:

- **Story Threads**: Ongoing narratives (e.g., "Decreto Carceri" legislative process) with impact scores and mention counts
- **Key Characters**: Important figures with their roles and evolving positions
- **Follow-ups**: Upcoming events and deadlines to monitor

This enables the newsletter to:
- Reference previous coverage: *"Come abbiamo seguito nelle ultime settimane..."*
- Track story evolution: *"Il Ministro Nordio, che la settimana scorsa aveva dichiarato X, oggi..."*
- Alert readers to upcoming events: *"Ricordiamo che domani è previsto..."*

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
