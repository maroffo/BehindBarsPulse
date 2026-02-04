# TODO - Riprendere da qui

## Il Bollettino - Implementato (2026-02-03)

### Fase 1: Database e Modelli
- [x] Migration Alembic `006_add_bulletins.py`
- [x] ORM models: `Bulletin`, `EditorialComment` in `db/models.py`
- [x] Pydantic models in `bulletin/models.py`
- [x] Repository: `BulletinRepository`, `EditorialCommentRepository`

### Fase 2: Generazione Bollettino
- [x] `BULLETIN_PROMPT` in `ai/prompts.py`
- [x] `BulletinGenerator` class con generate() e extract_editorial_comments()
- [x] `AIService.generate_bulletin()` con structured output
- [x] Test unitari: `test_bulletin.py` (9 test)

### Fase 3: API e Routes Web
- [x] `POST /api/bulletin` - OIDC protected (Cloud Scheduler)
- [x] `POST /api/bulletin-admin` - admin token protected
- [x] `GET /bollettino` - ultimo bollettino
- [x] `GET /bollettino/{date}` - bollettino specifico
- [x] `GET /bollettino/archivio` - lista bollettini
- [x] Templates: `bulletin.html`, `bulletin_archive.html`, `bulletin_empty.html`

### Fase 4: Ricerca Unificata
- [x] Filtri: Tutto | Articoli | Commenti Editoriali
- [x] `EditorialCommentRepository.search_by_embedding()`
- [x] UI filtri in `search.html`

### Fase 5: Automazione (DA FARE)
- [ ] Cloud Scheduler job alle 8:00
- [ ] Terraform per scheduler

### Fase 6: Backfill e Polish (DA FARE)
- [ ] Script per estrarre commenti da newsletter esistenti
- [ ] Importare in `editorial_comments`

---

## Completato

### Fix OIDC Cloud Scheduler (2026-02-03)
- ✅ Cloud Scheduler usava Cloud Run URL come OIDC audience
- ✅ App validava contro custom domain `https://behindbars.news`
- ✅ Aggiunta variabile `oidc_audience` al modulo `cloud_scheduler`
- ✅ Passato `https://behindbars.news` come audience in prod
- ✅ Terraform apply completato - tutti e 3 i job aggiornati
- ✅ Test manuale job collect: 200 OK

### Fix Newsletter Format (sessione precedente)
- ✅ `published_date` estratto da RSS e propagato attraverso la pipeline
- ✅ Template web matchano formato email (article-link, article-link-meta)
- ✅ Sanitizzazione NUL characters per PostgreSQL
- ✅ Newsletter 2026-01-07 rigenerata con successo

## Prossimi passi post-Bollettino

- Monitorare i job schedulati per confermare funzionamento continuo
- Considerare commit delle modifiche Terraform
