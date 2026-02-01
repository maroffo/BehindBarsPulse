# Gemini AI Integration

This document describes how BehindBarsPulse uses Google Gemini for content generation.

## Models Used

| Model | Purpose |
|-------|---------|
| `gemini-3-flash-preview` | All text generation (content, press review, enrichment) |
| `text-multilingual-embedding-002` | Article embeddings (768 dimensions, Italian-optimized) |

## Structured Output

All LLM calls use Gemini's **structured output** feature with `response_json_schema` to guarantee valid JSON responses:

```python
from pydantic import TypeAdapter
from google.genai import types

# Generate JSON schema from Pydantic models
schema = TypeAdapter(list[PressReviewCategory]).json_schema()

config = types.GenerateContentConfig(
    system_instruction=system_prompt,
    response_mime_type="application/json",
    response_json_schema=schema,  # Guarantees valid JSON matching schema
)
```

This eliminates JSON parsing errors that occurred with plain text responses.

## AI Pipeline Functions

### Article Enrichment (`enrich_articles`)
- **Input**: Raw articles with title, link, content
- **Output**: Author, source, summary for each article
- **Schema**: `ArticleInfo` model

### Narrative Extraction

Three functions for narrative continuity:

1. **`extract_stories()`**: Identifies ongoing story threads
   - Input: Articles + existing stories
   - Output: New stories, updates to existing stories

2. **`extract_entities()`**: Identifies key characters
   - Input: Articles + existing characters
   - Output: New characters, position updates

3. **`detect_followups()`**: Identifies upcoming events
   - Input: Articles + active story IDs
   - Output: Events with expected dates

### Press Review (`generate_press_review`)
- **Input**: Enriched articles
- **Output**: Categorized articles with **integrated editorial commentary**
- **Key Feature**: Comments synthesize multiple sources by name

Example output:
```
"Il 2025 si chiude con un bilancio drammatico. Damiano Aliprandi su Il Dubbio
parla di 'anno in cui le carceri hanno toccato il fondo', documentando 80 suicidi.
Giovanni Ferrara per l'ANSA conferma i numeri ufficiali del DAP..."
```

### Newsletter Content (`generate_newsletter_content`)
- **Input**: Press review + narrative context + previous issues
- **Output**: Title, subtitle, opening paragraph, closing paragraph

### Content Review (`review_newsletter_content`)
- **Input**: Generated newsletter content
- **Output**: Polished version with consistent style

## Prompts

All prompts are in Italian and stored in `src/behind_bars_pulse/ai/prompts.py`:

- `ARTICLE_INFO_PROMPT` - Article metadata extraction
- `STORY_EXTRACTION_PROMPT` - Narrative thread identification
- `ENTITY_EXTRACTION_PROMPT` - Character identification
- `FOLLOWUP_DETECTION_PROMPT` - Event detection
- `PRESS_REVIEW_PROMPT` - Category synthesis with editorial commentary
- `NEWSLETTER_CONTENT_PROMPT` - Opening/closing generation
- `REVIEW_PROMPT` - Style consistency check

## Embeddings

Articles are embedded for semantic search and future features:

```python
from google import genai

client = genai.Client()
response = client.models.embed_content(
    model="text-multilingual-embedding-002",
    contents=text,
    config={"output_dimensionality": 768}
)
embedding = response.embeddings[0].values
```

**Use Cases:**
- **RAG**: Retrieve historical context before generating commentary
- **Deduplication**: Skip near-duplicate articles (cosine similarity > 0.95)
- **Related Articles**: Find similar coverage for "See also" section
- **Story Detection**: Cluster articles into narrative threads
- **Trend Analysis**: Track topic evolution over time with embedding drift
- **Chatbot**: Power a Q&A interface over historical coverage

## Rate Limiting

Configurable sleep between API calls to avoid rate limits:

```python
# config.py
ai_sleep_between_calls: int = 30  # seconds
```

## Authentication

Uses Google Application Default Credentials:

```bash
gcloud auth application-default login
# OR
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

Project: `iungo-ai`, Region: `us-central1`
