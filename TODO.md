# TODO - BehindBarsPulse

## Obiettivo
Piattaforma di monitoraggio del sistema penitenziario italiano con bollettino quotidiano, newsletter settimanale, statistiche e ricerca semantica.

---

## Piano di Implementazione

### Fase 6: Stats e Data Quality ✅
- [x] Fix facility name normalization (deduplicazione istituti)
- [x] `utils/facilities.py` con alias mappings
- [x] Repository methods normalizzano nomi prima di aggregare
- [x] Endpoint API `/api/normalize-facilities` per cleanup dati
- [x] Script `scripts/normalize_facilities.py` per analisi/fix batch

### Fase 7: Bollettino con Press Review ✅
- [x] Migration 007 per colonna `press_review` JSONB
- [x] BulletinGenerator genera categorie tematiche con commento editoriale
- [x] Template bollettino mostra articoli raggruppati per categoria
- [x] Articoli correlati con formato card search

### In Corso
- [ ] Test responsive (manual)
- [ ] Deploy con facility normalization
- [ ] Backfill: normalizzare dati esistenti in produzione

### Future
- [ ] RAG per commento editoriale con contesto storico
- [ ] Alert automatici per facility con alta recidività incidenti
- [ ] Export dati CSV per giornalisti

---

## Note Tecniche

### Bollettino con articoli categorizzati
Caricare articoli dal DB nel route `/bollettino/{date}` e raggrupparli per categoria nel template.

### Struttura URL finale
```
/                       → HP (progetto + ultimo bollettino + ultima newsletter)
/iscriviti              → Form iscrizione
/edizioni               → Overview bollettini + newsletter
/edizioni/bollettino    → Archivio bollettini
/edizioni/newsletter    → Archivio newsletter
/bollettino/{date}      → Singolo bollettino con articoli
/latest                 → Redirect a ultima newsletter (backwards compat)
/archive/{date}         → Singola newsletter (backwards compat)
/articles               → Lista articoli
/article/{id}           → Dettaglio articolo (senza contenuto)
/stats                  → Statistiche
/search                 → Ricerca
```

---

## Completato (storico)

### Il Bollettino - Implementato (2026-02-04)
- [x] Migration Alembic `006_add_bulletins.py`
- [x] ORM models: `Bulletin`, `EditorialComment`
- [x] `BulletinGenerator`, `BULLETIN_PROMPT`
- [x] API endpoints e routes web
- [x] Cloud Scheduler alle 8:00 (`bulletin-daily`)
- [x] Primo bollettino generato

### Fix precedenti
- [x] OIDC Cloud Scheduler audience fix
- [x] Newsletter format e sanitizzazione NUL
- [x] Type safety e datetime.utcnow → datetime.now(UTC)
