# TODO: Batch Inference + Multi-Collect

## Problema Attuale

1. **RSS Feed limitato**: Solo 15 articoli, nessuna paginazione
2. **Articoli persi**: Se >15/giorno, i vecchi vengono eliminati dal feed
3. **JSON errors**: Prompt >1MB con 200+ articoli causa `Invalid \uXXXX escape`
4. **Timeout Cloud Run**: BackgroundTasks terminati quando istanza scala a zero

## Soluzione: Batch Inference + Collect Multipli

### 1. Collect ogni 30 minuti

```
*/30 * * * * → /api/collect (48x/giorno)
```

Con RSS feed limitato a 15 articoli e batch pubblicati ~10:40, collect ogni 30 min garantisce di non perdere nulla anche nei giorni più intensi.

Deduplicazione già implementata in `collector.py:249-254` (skip se URL esiste in DB).

### 2. Batch Inference Vertex AI

**Vantaggi:**
- 50% costo rispetto a real-time
- Nessun timeout (24h per completare)
- Retry automatici
- Structured output supportato (stesso formato API)

**JSONL Format:**
```jsonl
{"request": {"contents": [...], "generationConfig": {"responseSchema": {...}, "responseMimeType": "application/json"}}}
```

**Python SDK:**
```python
from google import genai
from google.genai.types import CreateBatchJobConfig, JobState

client = genai.Client()
job = client.batches.create(
    model="gemini-2.5-flash",
    src="gs://bucket/input.jsonl",
    config=CreateBatchJobConfig(dest="gs://bucket/output")
)
```

### 3. Architettura Target

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY FLOW                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Cloud Scheduler (every 30 min)                                 │
│         │                                                        │
│         ▼                                                        │
│  /api/collect (real-time, ~30s)                                 │
│    - Fetch RSS (15 articoli)                                    │
│    - Skip duplicati (by URL in DB)                              │
│    - Enrich con AI (author, source, summary)                    │
│    - Save to DB con embedding                                   │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Cloud Scheduler (1x/day: 08:00)                                │
│         │                                                        │
│         ▼                                                        │
│  /api/generate-batch                                            │
│    1. Query articoli del giorno da DB                           │
│    2. Prepara JSONL con tutti i prompt:                         │
│       - newsletter_content                                       │
│       - press_review                                             │
│       - stories_extraction                                       │
│       - entities_extraction                                      │
│       - followups_detection                                      │
│    3. Upload JSONL to GCS                                       │
│    4. Submit Vertex AI Batch Job                                │
│    5. Return job_id                                             │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Vertex AI Batch Job completes                                  │
│         │                                                        │
│         ▼                                                        │
│  Writes .jsonl to GCS (batch_jobs/*/output/)                    │
│         │                                                        │
│         ▼                                                        │
│  Cloud Function (triggered by GCS Object Finalize)              │
│    1. Download results from GCS                                 │
│    2. Parse responses                                           │
│    3. Render HTML/TXT                                           │
│    4. Save newsletter to DB                                     │
│    5. Upload to GCS                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Tasks

### Phase 1: Multi-Collect (quick win)
- [x] Cambiare scheduler a `*/30 * * * *` in Terraform
- [ ] Verificare che dedup funzioni correttamente
- [ ] Deploy e monitorare per qualche giorno

### Phase 2: Batch Inference
- [x] `google-genai` SDK già installato
- [x] Creare `BatchInferenceService` in `src/behind_bars_pulse/ai/batch.py`
  - `build_jsonl_request()` - costruisce singola request JSONL
  - `build_newsletter_batch()` - assembla tutti i prompt per newsletter
  - `upload_batch_input()` - carica JSONL su GCS
  - `submit_batch_job()` - invia job a Vertex AI
  - `get_job_status()` - controlla stato job
  - `download_batch_results()` - scarica risultati
  - `parse_batch_results()` - parse in NewsletterContent e PressReview
- [x] Implementare `/api/generate-batch` endpoint
  - Query articoli da DB (ultimi N giorni)
  - Costruisce JSONL con prompt (content, press_review)
  - Upload a GCS e submit job
  - Ritorna job_id per tracking
- [x] Implementare `/api/batch-job/{job_name}` per check status
- [ ] Testare con batch piccolo

### Phase 3: Cloud Function Callback
- [x] Creare `functions/process-batch/main.py`
  - Triggered by GCS Object Finalize (`batch_jobs/*/output/*.jsonl`)
  - Download risultati da GCS
  - Parse JSON responses
  - Render HTML/TXT con `html.escape()` (XSS prevention)
  - Save newsletter to DB + GCS
  - Global DB engine per connection reuse
- [x] Terraform per Cloud Function
  - `infra/modules/cloud_function/main.tf`
  - Service account con permessi GCS + Cloud SQL + Secret Manager
  - GCS Object Finalize trigger (più affidabile di audit logs)

### Phase 4: Cleanup & Scheduler Update
- [x] Aggiornare scheduler per chiamare `/api/generate-batch` invece di `/api/generate`
- [x] Tenere `/api/generate` per debug/regenerate manuale
- [ ] Monitoring: alert se batch job fallisce

## References

- [Batch inference with Gemini](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/batch-prediction-gemini)
- [Batch from Cloud Storage](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/batch-prediction-from-cloud-storage)
- [python-genai SDK](https://googleapis.github.io/python-genai/)

## Notes

- Feed RSS: `https://ristretti.org/index.php?format=feed&type=rss`
- 15 articoli fissi, pubblicati in batch ~10:40
- User-Agent richiesto (403 senza)
- GCS bucket: `playground-maroffo-behindbars-prod-assets`
- Project: `playground-maroffo`
