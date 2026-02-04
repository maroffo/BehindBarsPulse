# TODO - Refactoring UI e Bollettino

## Obiettivo
Ristrutturare il sito per dare senso alla distinzione Bollettino (quotidiano on-site) vs Newsletter (settimanale email), migliorare UX articoli, e creare una HP informativa.

---

## Piano di Implementazione

### Fase 1: Fix Bollettino Content ✅
- [x] Convertire markdown → HTML nel bollettino (usare markdown lib)
- [x] Caricare articoli del giorno precedente nel context del bollettino
- [x] Raggruppare articoli per categoria nel template bollettino
- [x] Aggiungere link agli articoli originali (come newsletter)

### Fase 2: Pagina Articolo - Rimuovere Contenuto ✅
- [x] Rimuovere sezione `article.content` dal template
- [x] Rendere prominente il pulsante "Leggi l'originale"
- [x] Mantenere: titolo, meta, riassunto, articoli correlati
- [x] Layout articoli correlati già esistente

### Fase 3: Nuova Navigazione ✅
- [x] Ristrutturare nav: Home | Edizioni | Articoli | Statistiche | Cerca
- [x] Creare pagina `/edizioni` con due sezioni:
  - Bollettini quotidiani (lista recenti + link archivio)
  - Newsletter settimanali (lista recenti + link archivio)
- [x] `/archive` → redirect 301 a `/edizioni/newsletter`
- [x] `/bollettino/archivio` → redirect 301 a `/edizioni/bollettino`
- [x] Aggiornati tutti i link interni

### Fase 4: Nuova Home Page ✅
- [x] Creare nuova HP con:
  - Hero: spiegazione progetto BehindBars
  - CTA iscrizione newsletter
  - Card ultimo bollettino quotidiano
  - Card ultima newsletter settimanale
- [x] Form iscrizione rimane su HP (più conversioni)

### Fase 5: Test e Deploy
- [x] Verificare tutti i link funzionanti
- [x] Test linting/format/type check passano
- [ ] Test responsive (manual)
- [ ] Deploy

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
