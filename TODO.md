# TODO: Batch Inference + Multi-Collect

## Problema Attuale

1. **RSS Feed limitato**: Solo 15 articoli, nessuna paginazione
2. **Articoli persi**: Se >15/giorno, i vecchi vengono eliminati dal feed
3. **JSON errors**: Prompt >1MB con 200+ articoli causa `Invalid \uXXXX escape`
4. **Timeout Cloud Run**: BackgroundTasks terminati quando istanza scala a zero

## Soluzione: Batch Inference + Collect Multipli

### 1. Collect 4x/giorno

```
07:00 → /api/collect (articoli notturni)
12:00 → /api/collect (batch mattutino ~10:40)
18:00 → /api/collect (aggiunte pomeridiane)
23:00 → /api/collect (articoli serali)
```

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
│  Cloud Scheduler (4x/day: 07, 12, 18, 23)                       │
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
│  Cloud Function (triggered by Batch Job completion)             │
│         │                                                        │
│         ▼                                                        │
│  process-batch-results                                          │
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
- [ ] Aggiungere 3 scheduler aggiuntivi in Terraform (12:00, 18:00, 23:00)
- [ ] Verificare che dedup funzioni correttamente

### Phase 2: Batch Inference
- [ ] Installare `google-genai` SDK
- [ ] Creare `BatchInferenceService` in `src/behind_bars_pulse/ai/batch.py`
- [ ] Implementare `/api/generate-batch` endpoint
- [ ] Creare JSONL builder per tutti i prompt
- [ ] Testare con un batch piccolo

### Phase 3: Cloud Function Callback
- [ ] Creare Cloud Function `process-batch-results`
- [ ] Configurare trigger su completamento batch job
- [ ] Implementare parsing risultati e save to DB

### Phase 4: Cleanup
- [ ] Rimuovere vecchio `/api/generate` real-time (o tenerlo per debug)
- [ ] Aggiornare documentazione
- [ ] Monitoring e alerting

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
