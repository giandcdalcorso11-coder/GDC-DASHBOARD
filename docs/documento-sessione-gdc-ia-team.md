# Documento di Sessione — GDC IA TEAM

**Versione:** 13
**Ultimo aggiornamento:** 2026-11-14 13:25

## Vision

GDC IA TEAM è il sistema di automazione che supporta l'attività Instagram di @giandcdalcorso (Gianluca Dal Corso, atleta professionista di beach volley, Nazionale Italiana, base Pescara) e la ricerca di sponsorizzazioni per il suo profilo. È composto da 7 "agenti":

- **A1 — Data Collector**: raccolta automatica dati Instagram (Python/GitHub Actions, nessuna interazione).
- **A2 — Analyst**: report mensile di performance.
- **A3 — Planner**: piano editoriale del mese successivo.
- **A4 — Brief & Script**: brief dei post pianificati (apertura mese) + consulenza creativa continua per il resto del mese.
- **A5 — Ricerca aziende**: individuazione aziende per sponsorizzazione.
- **A6 — Media kit & relazioni commerciali**: produzione media kit, gestione trattative.
- **A7 — Mail generator**: bozze Gmail automatiche, follow-up.

Il tutto gira sopra una webapp PWA ("GDC WORKSPACE", servita da GitHub Pages sul repo pubblico `GDC-DASHBOARD`), Supabase come base dati/stato, Google Drive come storage file, Google/Gmail/Instagram Graph API come integrazioni esterne.

**Direzione attuale**: Gianluca ha lavorato finora con A2-A7 come Progetti Claude.ai (chat con prompt dedicati), con un passaggio manuale "scarica da chat → carica su Drive" per ogni file prodotto, percepito come macchinoso — soprattutto per il gruppo A1-A4 (la "catena editoriale" mensile). Si è deciso di **prendere in mano A1-A4 e lavorarci direttamente da Claude Code**, ripensando l'architettura: output in HTML invece di pptx/docx (serviti da GitHub Pages, contenuto vero protetto su Supabase dietro il login esistente), trigger verso una sessione Claude Code dedicata invece che verso un Progetto Claude.ai. A5-A7 e il lato "GDC Studio" (stampa 3D, side business separato nella stessa webapp) **non sono in perimetro** e non vanno toccati in questo lavoro.

Vincolo esplicito: nessun costo API a consumo aggiuntivo — si resta dentro l'abbonamento Claude Pro già pagato.

## Pipeline

### Step 1 — Robustezza stato agenti (pallini home page)

**Stato:** completato

**Obiettivo:** i pallini di stato degli agenti nella home (`page_home_v25.html`) devono riflettere in modo affidabile cosa sta succedendo davvero, senza restare bloccati in stati non veri.

**Decisioni progettuali:**
- Aggiunto uno stato "errore" reale (prima il vocabolario era solo queued/working/done/riposo/sleep).
- `a1_monthly.py` ora garantisce sempre una scrittura finale su `agent_states` (done o error), avvolgendo il corpo reale (rinominato `_run()`) in un try/except dentro `main()`.
- Aggiunta in `mapState()` (JS) una scadenza di 3 ore per lo stato `working`: oltre quella soglia il pallino passa a "errore" invece di restare bloccato su "in corso" (copre anche il caso limite di un processo ucciso dal runner prima di poter scrivere qualunque cosa, non solo le eccezioni Python catturate).
- Scelta di design per "errore": riusa la palette visiva già esistente di "queued" (rosso) sui loghi/card per non dover introdurre una sesta variante di colore per ognuno dei 7 loghi SVG animati — si distingue solo via testo (chip "⚠ Errore" vs "⏸ In attesa") e via pillola manuale dedicata. Compromesso accettato per tenere il cambiamento minimale; da rivedere se in futuro servisse una distinzione visiva più marcata.
- Rimosso il codice morto verificato via grep (zero chiamate reali): `setStato()`, `STATO_CYCLE`, `STATO_LABELS`. `renderActionsSimple()` invece NON è stato toccato: è richiamata da `loadStates()` (righe 843-844 prima dell'edit) — è uno stub voluto per A5/A6, non codice morto, come indicato dal suo stesso commento.
- A2/A3/A4 non scrivono oggi nessuno stato automatico su `agent_states` (solo manuale via click pillola) — la correzione vera per questi tre resta nel rebuild (Step 5), non patchata qui.
- Override manuale: confermato da Gianluca — tenere `setStatoRaw` come valvola di emergenza, non rimuoverlo.

**Criterio di completamento:** un run fallito di A1 Monthly produce uno stato "errore" visibile e non resta bloccato su "in corso"; nessun pulsante della home richiama più codice morto. — Verificato: sintassi Python (`py_compile`) e JS (`node --check` sullo script estratto) entrambe pulite dopo le modifiche; verifica funzionale su un run reale fallito ancora da fare al prossimo run di A1 Monthly (il prossimo tentativo utile è legato anche allo Step 2, token scaduto).

**Note (cronologia dello step):**
- [2026-11-12] Diagnosi completa: causa radice individuata leggendo `a1_monthly.py` (nessun try/except attorno a `main()`, stato "working" scritto come prima riga senza rete di sicurezza) e `page_home_v25.html` (`mapState()` senza scadenza per "working"; `setStatoRaw` permette override manuale diretto su Supabase). Confermato via grep che solo `a1_monthly.py` scrive su `agent_states` tra tutti gli script — A2/A3/A4 scrivono solo su `activity_log`. Fix concordato con Gianluca, lavoro avviato.
- [2026-11-13] Fix implementato e pushato (commit `4fd6076`): `a1_monthly.py` ristrutturato (`main()` + `_run()` + try/except → stato "error" + `log_activity`); `page_home_v25.html` aggiornato (nuovo stato "error" in `mapState`/`CFG`/`PRI`/`STATO_PILLS`, scadenza 3h su "working", rimozione codice morto confermato via grep). Gianluca ha confermato esplicitamente di procedere con tutte le risposte di default proposte da Claude in questa sessione, inclusa questa: override manuale mantenuto. Scope A1-only (A2/A3/A4 al rebuild) confermato implicitamente, nessuna obiezione.

### Step 2 — Token Instagram scaduto + bug silenzioso A1 Stories Daily

**Stato:** completato

**Obiettivo:** il rinnovo del token Instagram torna a funzionare prima della scadenza reale (non dopo), e A1 Stories Daily non segnala più "successo" quando in realtà non ha salvato nulla.

**Decisioni progettuali:**
- Il token è scaduto per davvero il 31/10/2026 — un token scaduto non si può rinnovare via refresh, serve un nuovo login manuale Meta da parte di Gianluca (passaggio che richiede browser, non automatizzabile da script).
- **Scoperta chiave (supera la lettura iniziale "bug di margine/timing" del 12/11):** non è un problema di margine. Confrontando i log reali di più run consecutivi di `ig_token_refresh.py` (19/10: "mancano 12.2 giorni" → nuova scadenza ottenuta 2026-10-31T18:20:21; 26/10: "mancano 5.2 giorni" → nuova scadenza ottenuta **di nuovo, identica al secondo**, 2026-10-31T18:20:21), risulta che la chiamata `fb_exchange_token` su questo token non ha mai davvero spostato la scadenza in avanti — ha solo confermato lo stesso conto alla rovescia verso una scadenza fissa legata all'ultimo login manuale reale. Il meccanismo di "auto-rinnovo settimanale" è risultato verde per mesi senza funzionare davvero. Non ancora verificato se questo sia un limite intrinseco di questo tipo di token/endpoint Meta o un dettaglio risolvibile — lo sapremo osservando se il prossimo rinnovo, dopo il login manuale di Gianluca, sposta davvero la data.
- `a1_stories_daily.py`: un errore OAuth 400 veniva interpretato come "nessuna story attiva" e lo script usciva con successo — da inizio novembre non venivano salvate stories, senza nessun alert perché il workflow risultava verde. **Fix applicato**: rimosso il try/except che catturava qualunque `HTTPError` in `fetch_active_stories()` — ora un errore reale fa fallire lo script in modo visibile, il caso legittimo di lista vuota resta gestito come prima.
- `ig_token_refresh.py`: trovato un secondo bug indipendente — `update_supabase_token_status()` sovrascriveva `expires_at` con `null` ad ogni tentativo fallito, perdendo la visibilità sull'ultima scadenza nota buona. **Fix applicato**: su fallimento lo script ora legge e riscrive il valore già presente invece di azzerarlo.

**Criterio di completamento:** `a1_stories_daily.py` segnala (fallimento visibile) se riceve un errore di autenticazione — fatto e verificato con un run reale; `ig_token_refresh.py` riesce davvero a spostare la scadenza in avanti partendo da un login reale — verificato con un run reale (vedi sotto). Entrambi confermati.

**Decisione/nota finale:** il mistero del "perché l'exchange restituiva sempre la stessa scadenza fissa" resta senza una spiegazione certa (non confermabile dall'esterno via log — potrebbe essere un limite Meta non documentato su rinnovi ripetuti senza un login fresco, o un effetto collaterale di un problema precedente non identificato). Non è bloccante: con un login reale appena fatto, il rinnovo settimanale riparte da una base sana e ora scrive sempre uno stato visibile (errore se fallisce, scadenza reale se riesce — grazie ai due fix di questo step). Da tenere d'occhio nelle prossime settimane tramite i pallini di stato (Step 1) invece che assumere "funziona per sempre".

**Note (cronologia dello step):**
- [2026-11-12] Trovato durante l'audit completo dei 10 GitHub Actions workflow del repo: `A1 Monthly` fallito il 2/11 (stesso token morto), `IG Token Refresh` fallito 2 volte consecutive (2/11, 9/11), `A1 Stories Daily` sempre verde ma silenziosamente inattivo da inizio mese. Audit ha anche rilevato che i workflow con cron frequente (ogni 30 min / ogni ora: `A1 MBS Watcher`, `Pipeline Watcher`) girano in realtà ogni 7-9 ore — limite di scheduling lato GitHub Actions sotto carico, non un bug nostro, solo da tenerne conto.
- [2026-11-13] Letti i log reali di 5 run consecutivi di `ig_token_refresh.py` (5/10, 12/10, 19/10, 26/10, 2/11) — scoperta la vera causa radice (vedi sopra, non un bug di margine). Pushati i fix per `a1_stories_daily.py` (commit `0f6863e`) e per la perdita di visibilità su `expires_at` in `ig_token_refresh.py` (stesso commit).
- [2026-11-13, pomeriggio] Gianluca ha fatto il login manuale Meta via Graph API Explorer (app "GDC IA TEAM"), ottenuto un nuovo token short-lived, scambiato per long-lived via `fb_exchange_token`, aggiornato il secret `IG_ACCESS_TOKEN` su GitHub. Verifica con due run reali lanciati da Claude Code: `a1_stories_daily.yml` → successo, risposta IG reale "nessuna story attiva" (non più l'errore OAuth); `ig_token_refresh.yml` → successo, nuova scadenza ottenuta **2027-01-12** (quasi 60 giorni da oggi, non più la vecchia data fissa del 31/10) — conferma che il rinnovo funziona correttamente quando riparte da un login reale. Step chiuso.

### Step 3 — Tassonomia DIVULGAZIONE

**Stato:** completato

**Obiettivo:** la serie "Capiamo la Sabbia" ha una categoria primaria propria (DIVULGAZIONE) coerente su tutti i documenti/script che la leggono.

**Decisioni progettuali:**
- Trovata incongruenza reale tra i 4 prompt agente: A3 (v12) assume già l'esistenza di una categoria primaria DIVULGAZIONE; A1 (v4), A2 (v14) e A4 (v6) la classificano ancora come combinazione GDC STUFF (primaria) + SPORT (secondaria).
- Decisione di Gianluca: creare DIVULGAZIONE come quarta categoria primaria vera. Secondaria = GDC STUFF (per mantenere traccia del marchio sotto cui vive la serie).
- Beneficio collaterale: A2 e A4 oggi isolano la serie leggendo il nome del post via regex sulla caption — con la categoria dedicata possono filtrare direttamente sul campo categoria, più robusto.
- Vanno aggiornati: A1 (regola di classificazione automatica), A2 (sezioni che leggono/normalizzano categorie, slide/sezione serie), A4 (tabella categorie di riferimento). A3 non necessita modifiche.

**Criterio di completamento:** tutti e 4 i documenti/script concordano su DIVULGAZIONE come quarta categoria primaria; il riconoscimento della serie non dipende più dal solo nome del post. — Verificato su tutti e 4: `a1_monthly.py` (codice, commit `f224802`), `Agente1_auto_prompt` (docx, v4→v5), `Agente2_auto_prompt` (md, v14→v15), `Agente4_auto_prompt` (md, v6→v7); A3 confermato già corretto, non toccato.

**Note (cronologia dello step):**
- [2026-11-12] Decisione presa dopo discussione con Gianluca, inclusa correzione di un'inversione primaria/secondaria che Gianluca aveva scritto a parole ("Sport primaria, GDC Stuff secondaria") rispetto a quanto documentato in A1/A2/A4 (GDC STUFF primaria, SPORT secondaria) — chiarito che la documentazione corrente è quella corretta, resa comunque superata dalla nuova categoria dedicata.
- [2026-11-13] Implementato ovunque. `a1_monthly.py`: `CATEGORIE_GDC` ora a 4 valori, la serie si auto-classifica DIVULGAZIONE/GDC STUFF invece di GDC STUFF/SPORT (si riflette automaticamente nella dropdown di convalida del foglio Excel). Documenti prompt aggiornati: A2 v15 — normalizzazione, placeholder colore DIVULGAZIONE=D9B77E (stesso hex della palette teal di A3, per coerenza), riconoscimento serie ora basato sulla categoria invece che solo sul nome, rimossa la logica di sotto-righe "di cui/esclusa serie" (non più necessaria: DIVULGAZIONE è una categoria a sé nella tabella per-categoria); A4 v7 — nuova riga DIVULGAZIONE in tabella categorie, aggiornata sez. 7; A1 (documento tecnico .docx) v5 — tabella 6.0 aggiornata, nota sulla convalida a 4 valori, aggiunta riga changelog v5. Le 3 copie aggiornate (A1 v5 docx, A2 v15 md, A4 v7 md) consegnate a Gianluca via file.
- [2026-11-13, più tardi] Chiarito con Gianluca: fino a quando la sessione Claude Code dedicata (Step 8) non è pronta, continuerà a lanciare i cicli mensili reali di A2/A3/A4 dai Progetti Claude.ai come fa oggi — quindi i prompt aggiornati vanno comunque ricaricati lì (l'istruzione di prima sessione era corretta, solo non motivata bene). In più, ha chiesto di mettere i 4 prompt anche su GitHub (`docs/prompts/`, posizione provvisoria prima del riordino dello Step 6) così restano leggibili da qualunque sessione Claude Code futura senza dipendere dagli upload di questa conversazione. Segnalato che il repo è pubblico prima di pushare (playbook operativo e link cartelle Drive visibili a chiunque, nessun segreto vero) — confermato "pubblici va bene", pushato (commit `a888677`), incluso anche Agente3_auto_prompt_v12.md (invariato) per avere i 4 insieme.

### Step 4 — Schermata di categorizzazione post

**Stato:** completato (manca solo il suggerimento AI, rimandato — vedi sotto)

**Obiettivo:** Gianluca categorizza i post del mese (oggi: celle gialle manuali in uno spreadsheet) da un'interfaccia comoda nella webapp, con suggerimento automatico.

**Decisioni progettuali:**
- Categoria primaria: elenco fisso (ora 4 valori incluso DIVULGAZIONE) + suggerimento di Claude + possibilità di modifica manuale.
- Categoria secondaria: menù a tendina filtrato per categoria primaria selezionata + suggerimento di Claude + possibilità di testo libero; ogni testo libero nuovo inserito si aggiunge al menù per le volte successive (vocabolario che cresce, non si fraziona in varianti).
- Vocabolario di partenza per la secondaria (estratto da A4 v6, sez. 2): SPORT → Torneo/Gara, Allenamento, Nazionale, Viaggio/Trasferta; RELATION → Coppia, Famiglia, Amici; GDC STUFF → Stampa 3D, Elettronica/Coding, Prodotto finito, Making of.
- Diventa un passaggio esplicito e visibile della pipeline (es. "Ottobre: 2 post da categorizzare"), non più invisibile come oggi — gate prima che A2 possa partire sensatamente.

**Criterio di completamento:** Gianluca può categorizzare un mese intero dalla webapp senza aprire lo spreadsheet; i valori usati si accumulano nel menù secondario nel tempo. — **Verificato end-to-end con dati reali**: i 7 post di Ottobre 2026 sono tutti categorizzati (4 a mano + 3 di serie automatici), il vocabolario secondario è cresciuto con i 2 valori liberi inseriti da Gianluca ("Gdc stuff" sotto RELATION, "Premiazioni" sotto SPORT), disponibili in tendina da subito. Resta solo il "suggerimento di Claude" della decisione originale, non ancora presente (vedi sotto).

**Decisione presa in corso d'opera:** il "suggerimento di Claude" previsto nel design originale non può essere una vera chiamata API dalla webapp (violerebbe il vincolo "zero costo extra" — pagina statica, nessun backend). Deciso di costruire comunque lo schema pronto (colonne `categoria_primaria_suggerita`/`categoria_secondaria_suggerita` su `posts`, mostrate in UI se presenti) ma lasciarle vuote per ora — le popolerà la sessione Claude Code dedicata (Step 8) quando esisterà, usando l'abbonamento Pro invece di una chiamata a pagamento. Oggi la schermata è quindi solo manuale, senza suggerimento pre-compilato.

**Note (cronologia dello step):**
- [2026-11-14] Creato lo schema Supabase (tabelle `posts` e `categoria_secondaria_vocabolario`, migrazione applicata e registrata in `supabase/migrations/`). Estesa `a1_monthly.py` con `sync_posts_to_supabase()`: scrive su Supabase solo i post ORIGINALE non-serie, senza includere le colonne categoria nel payload per non sovrascrivere mai una scelta già fatta da Gianluca in un rerun del mese (verificato con un test diretto sul database prima di fidarsi della logica). Costruita la pagina `app/agenti/a1-analytics/categorizza.html` (primaria a 4 bottoni, secondaria a tendina che cresce con testo libero, episodi di serie esclusi perché già automatici) e collegata da una nuova card in `page_agent_a1_v1.html` con conteggio dinamico "N post da categorizzare". Verificati sintassi JS/Python e tutti i link del repo (53 controllati, 0 rotti) prima del push.

### Step 5 — Schema Supabase + pagine HTML (dashboard A2, calendari A3/A4)

**Stato:** in corso — scomposto in sotto-punti, fatti 1 e 2 su un piano di 5 (per agente, fino in fondo, uno alla volta: A2 prima di A3/A4)

**Obiettivo:** A2, A3 e A4 (solo apertura mese) producono pagine HTML invece di pptx/pdf, con lo stesso contenuto/struttura/voce di oggi; il contenuto vero vive su Supabase protetto da login, i template sono pubblici su GitHub Pages.

**Decisioni progettuali:**
- Pagina cliccando il logo di A2: piccola dashboard con numeri/grafici che si riempiono mese per mese (stile GDC), letti da una tabella Supabase leggera e strutturata, separata dal contenuto narrativo del report.
- Pagine di A3/A4: niente grafici (non hanno dati numerici da rappresentare allo stesso modo) — un calendario/elenco semplice di mesi, ognuno con link al proprio documento.
- Il report/piano/brief aperto cliccando un mese resta lo stesso contenuto prodotto oggi — cambia solo il contenitore (HTML invece di pptx/pdf).
- Motivazione privacy: il repo GitHub è pubblico (verificato), quindi i template/shell HTML restano vuoti e pubblici; i dati veri (metriche, testo dei report) vivono in Supabase dietro lo stesso sistema di login/sessione già usato dal resto della webapp (stesso comportamento di scadenza token già presente).
- Scomposizione dello step in 5 sotto-punti, un agente alla volta fino in fondo (schema → pagina → riscrittura prompt → prova con un mese vero) prima di passare al successivo, stessa lezione imparata allo Step 4: (1) schema KPI mensili su Supabase per A2; (2) pagina dashboard A2; (3) riscrittura prompt A2 (v15→v16) per generare HTML/Supabase invece di pptx; (4) stesso lavoro per A3 (calendario); (5) stesso lavoro per A4 (solo apertura mese).

**Criterio di completamento:** apertura di un mese passato mostra lo stesso contenuto che oggi è nel pptx/pdf corrispondente, ma come pagina HTML raggiungibile solo da sessione autenticata.

**Note (cronologia dello step):**
- [2026-11-13] Step discusso e deciso, non ancora iniziato. Ricevuti e letti integralmente i 4 prompt agente (A1 v4, A2 v14, A3 v12, A4 v6) come base per la ricostruzione fedele dei contenuti.
- [2026-11-14] Punto 1: creata tabella `kpi_mensili` su Supabase (RLS `authenticated_all_kpi_mensili`); `a1_monthly.py` ora sincronizza la riga del mese (stessi valori già calcolati per lo Sheet "KPI Medi", nessun calcolo duplicato) tramite `sync_kpi_to_supabase()`, chiamata da `_run()` dopo `compile_sheet_kpi()`. Verificato con una run reale sul branch (A1 Monthly, Ottobre 2026): riga sincronizzata correttamente, valori coerenti con l'Excel.
- [2026-11-14] Punto 2: creata `app/agenti/a2-analyst/dashboard_kpi.html`, raggiungibile dalla nuova card "Dashboard KPI" nelle Azioni di A2. Mostra, per ogni metrica di `kpi_mensili` (gruppi Post/Stories), il valore del mese corrente, il delta % vs il mese precedente (colorato in base a se la metrica è "meglio se alta", neutro per Sentiment Score che non ha una direzione ovvia) e uno sparkline SVG con l'andamento su tutti i mesi sincronizzati (compare dal secondo mese disponibile). Nessun calcolo nuovo: legge solo `kpi_mensili`. Mergiato su main per essere testabile dal sito reale.
- [2026-11-14] Backfill storico: scaricato il foglio Google "Instagram_Analytics_GDC" (via Drive, export xlsx) e letti i 10 mesi reali già presenti nello Sheet "KPI Medi" (Gennaio→Ottobre 2026 — A1 li ha sempre scritti lì, solo non ancora sincronizzati su Supabase prima di oggi). Inseriti su `kpi_mensili` i 9 mesi mancanti (Gennaio-Settembre, Ottobre già sincronizzato dalla run reale di oggi) con `on conflict (mese) do nothing`. La dashboard di A2 mostra ora lo storico completo con gli sparkline popolati su tutti i 10 mesi, non solo da oggi in avanti.

### Step 6 — Riorganizzazione cartelle GitHub

**Stato:** in corso — avviata in anticipo rispetto allo Step 5 (vedi decisione sotto), parziale

**Obiettivo:** la struttura del repo (oggi completamente piatta) rispecchia quella già ordinata di Drive, per agente.

**Decisioni progettuali:**
- Struttura Drive di riferimento (confermata via audit): cartella radice "GDC IA TEAM" → AGENTE 1.2, AGENTE 2, AGENTE 3, AGENTE 4, AGENTE 6 (con sottocartella Aziende), AGENTE 7 — ognuna con le proprie sottocartelle.
- Proposta struttura GitHub: `index.html`/`manifest.json`/`sw.js` restano in root (vincolo PWA); nuova cartella `app/` per le pagine esistenti (incluso `app/agenti/a1-analytics/`, `a2-analyst/`, `a3-planner/`, `a4-brief/`); nuova cartella `editoriale/` per gli output mensili HTML; nuova cartella `docs/` per la documentazione di progetto (vedi sotto); `scripts/` e `icons/` invariate.
- Spostare le pagine esistenti richiede aggiornare `manifest.json` (start_url), il redirect di `index.html`, e tutti i link interni tra pagine — da fare con attenzione e verifica di navigazione dopo, non è un'operazione a costo zero.
- Trovata una cartella sospetta su Drive, `processed/` dentro AGENTE 6 (creata dal service account), che contraddice la decisione documentata "A7 non usa una cartella processed/" — da controllarne il contenuto prima di decidere se eliminarla.
- **Il documento di sessione vive in `docs/documento-sessione-gdc-ia-team.md`** (questo file), deciso esplicitamente da Gianluca come posto fisso nel repo invece che fuori, dato che finora si lavorava dai Progetti Claude.ai senza repo.

**Criterio di completamento:** tutte le pagine esistenti funzionano dai nuovi percorsi, nessun link interno rotto, nuove pagine editoriali già nella struttura definitiva.

**Note (cronologia dello step):**
- [2026-11-12] Audit completo struttura Drive vs GitHub eseguito. Confermato repo pubblico (verificato via fetch diretto). Cartella `docs/` creata in questa sessione per ospitare questo documento.
- [2026-11-13] Gianluca ha chiesto di anticipare la riorganizzazione (invece di farla insieme allo Step 5) per far nascere le pagine nuove già nel posto giusto. Eseguita solo la parte a basso rischio: `page_home_v25.html` e `page_hub_v1.html` → `app/`; le quattro pagine agente → `app/agenti/a{1,2,3,4}-{analytics,analyst,planner,brief}/`. Lasciati deliberatamente in root (zero rischio di toccare automazioni fuori perimetro): `index.html`/`manifest.json`/`sw.js` (vincolo PWA), `page_login_v6.html` (bootstrap PWA — spostarlo avrebbe richiesto toccare il link di login/redirect in ogni singola pagina del repo, incluse quelle A5-A7 fuori perimetro, per un guadagno minimo), `page_agent_a5/a6/a7_v1.html`, `page_company_v2.html`, `page_pipeline_v1.html`, `gdc_studio.html`, `gdc_reset_tool.html` — i primi tre sono referenziati da `WEBAPP_BASE` dentro script Python di A5-A7 (`a7_followup.py`, `pipeline_notify.py`) che non si è voluto toccare in questo giro. Aggiornati tutti i link che puntano da/verso i file spostati (incluse le pagine rimaste in root). Scritto ed eseguito un verificatore automatico che risolve ogni link relativo contro il filesystem reale (50 link, 0 rotti) — ha anche scovato un errore reale fatto durante l'edit (profondità sbagliata nel link di login dalle pagine agente, 2 livelli invece di 3). Verificata anche sintassi Python/JS su tutti i file toccati. Push fatto sul branch di lavoro, non su main — il sito live su GitHub Pages non è impattato finché non c'è merge. Resta da fare: cartella `editoriale/` per gli output mensili (Step 5), eventuale riordino di A5-A7/company/pipeline/login (non ancora deciso se necessario).

### Step 7 — Trasporto dati storici da Drive

**Stato:** da fare — dopo Step 5/6

**Obiettivo:** la webapp ricostruita parte già popolata con la storia reale (report/piani/brief passati), non vuota.

**Decisioni progettuali:**
- Da eseguire dopo che schema Supabase, pagine HTML e nuova struttura cartelle sono pronti — i contenuti storici vanno importati direttamente nel formato definitivo, non migrati due volte.
- Dettagli di importazione (quali mesi, come convertire pptx/pdf esistenti in contenuto Supabase/HTML) ancora da definire.

**Criterio di completamento:** la dashboard di A2 mostra grafici reali anche per i mesi passati già esistenti su Drive, non solo da oggi in avanti; i calendari di A3/A4 mostrano i mesi già pianificati in passato.

**Note (cronologia dello step):**
- [2026-11-12] Step aggiunto alla pipeline su richiesta esplicita di Gianluca, non ancora iniziato.

### Step 8 — Bottone trigger verso sessione Claude Code dedicata

**Stato:** da fare

**Obiettivo:** un bottone nella webapp apre la sessione Claude Code dedicata ad A1-A4 con il messaggio del mese già pronto da incollare.

**Decisioni progettuali:**
- Versione iniziale: bottone che apre il link della sessione Claude Code dedicata + copia il messaggio negli appunti (stesso meccanismo già in uso oggi per i Progetti Claude.ai, solo puntato a una sessione Claude Code invece che a un Progetto) — Gianluca incolla lui.
- Versione più automatica (notifica il giorno 1 del mese: "vuoi iniziare l'analisi di [mese]? Sì / Più tardi / No") valutata come miglioria futura, non nella prima versione — richiederebbe probabilmente passare dal semplice "copia e incolla" a un meccanismo che crea/avvia la sessione in automatico (es. una piccola funzione server-side), perché un tap su una notifica non può aprire da solo una chat interattiva.
- La sessione Claude Code dedicata ad A1-A4 è separata da questa (stesso repo, già confermato funzionare con lo stesso pattern in un altro progetto di Gianluca).
- Requisiti identificati per far lavorare la sessione dedicata: accesso al repo (automatico), le istruzioni degli agenti (i 4 prompt, già raccolti), i dati del mese da A1 (consigliato: `a1_monthly.py` scrive anche una copia dati nel repo, evitando di dover passare credenziali Google alla sessione dedicata), un connector Supabase (non chiavi in chiaro) se la sessione deve scrivere i report.

**Criterio di completamento:** un click nella webapp porta a una sessione Claude Code pronta, con solo da incollare e inviare.

**Note (cronologia dello step):**
- Nessuna nota ancora — step discusso e deciso, non ancora iniziato.

### Step 9 — Pagina Impostazioni/notifiche

**Stato:** da fare — priorità più bassa

**Obiettivo:** nuova pagina "Impostazioni" nella webapp con interruttori per attivare/disattivare le notifiche push per categoria.

**Decisioni progettuali:**
- Idea originale di Gianluca, mai realizzata finora per la difficoltà di modificare la webapp dai Progetti Claude.ai — ora che si lavora da Claude Code con push/rimozione file diretta, è un buon momento per affrontarla.
- Trovata su Supabase una tabella `user_settings` (user_id + campo `settings` jsonb) già esistente ma con 0 righe e non collegata a nulla nel codice attuale — possibile scaffolding abbandonato di un tentativo precedente. Confermato con Gianluca: si riusa questa tabella (ha già la forma giusta: user_id + jsonb) invece di costruirne una nuova.

**Criterio di completamento:** da definire nel dettaglio quando si arriva allo step (categorie di notifiche da esporre, granularità).

**Note (cronologia dello step):**
- [2026-11-12] Trovata `user_settings` durante l'audit Supabase generale. Non ancora deciso se riusarla.
- [2026-11-13] Deciso: si riusa `user_settings` — confermato da Gianluca insieme alle altre risposte di default di questa sessione.

## Storico sessioni

### [2026-11-14 13:25] Step 5 avviato — schema KPI mensili + dashboard A2 + backfill storico (punti 1-2 su 5)

**Riepilogo:** Deciso di spezzare lo Step 5 in 5 sotto-punti (un agente alla volta, fino in fondo) per evitare di costruire tutto insieme e trovare bug ovunque come rischiato allo Step 4; fatti i primi due (sincronizzazione dei KPI mensili su Supabase e la pagina dashboard di A2 che li legge) più il backfill dei 9 mesi storici già presenti nel foglio Google di A1, così la dashboard parte subito con lo storico reale completo invece che con un solo mese.

**Cosa è stato fatto:**
- Creata la tabella Supabase `kpi_mensili` (RLS `authenticated_all_kpi_mensili`, stesso pattern delle altre tabelle agent-facing), migrazione registrata in `supabase/migrations/20261114_add_kpi_mensili.sql`.
- `a1_monthly.py`: `compile_sheet_kpi()` ora ritorna la riga calcolata; nuova `sync_kpi_to_supabase()` la scrive su `kpi_mensili` via upsert su `mese` — nessun calcolo duplicato, solo sincronizzazione dei valori già prodotti per lo Sheet "KPI Medi". Verificato lanciando A1 Monthly reale sul branch: riga "Ottobre 2026" sincronizzata con valori coerenti con l'Excel (ER 6,68%, reach medio post 2944, ecc.).
- Nuova pagina `app/agenti/a2-analyst/dashboard_kpi.html`: per ogni metrica (gruppi "Post" e "Stories") mostra il valore del mese corrente, il delta % vs il mese precedente (colore in base a se la metrica è "meglio se alta"; neutro per Sentiment Score, che non ha una direzione ovvia) e uno sparkline SVG con l'andamento su tutti i mesi sincronizzati — il grafico compare da solo dal secondo mese disponibile, senza bisogno di altri interventi. Letta la skill dataviz del progetto prima di scrivere il codice dei grafici (un'unica tinta per serie, nessun doppio asse, tooltip nativo per punto).
- Aggiunta la card "Dashboard KPI" nelle Azioni di A2, che apre la nuova pagina.
- Verificato: sintassi Python/JS, tutti i link del repo (56, 0 rotti) con lo script già scritto in una sessione precedente, prima del push. Fast-forward merge su `main` per renderla testabile dal sito reale.

**File consegnati/modificati:**
- `supabase/migrations/20261114_add_kpi_mensili.sql` (nuovo)
- `scripts/a1_monthly.py` (modificato: `compile_sheet_kpi()`, nuova `sync_kpi_to_supabase()`, chiamata in `_run()`)
- `app/agenti/a2-analyst/dashboard_kpi.html` (nuovo)
- `app/agenti/a2-analyst/page_agent_a2_v3.html` (modificato: nuova card "Dashboard KPI")
- Tabella `kpi_mensili` su Supabase: backfill diretto via SQL dei 9 mesi storici (nessun file di codice coinvolto, solo dati)

---

### [2026-11-14 11:20] Step 4 completato e verificato end-to-end — trovati e risolti 2 bug veri, categorizzazione reale confermata

**Riepilogo:** Costruita la schermata di categorizzazione post con il relativo schema Supabase; Gianluca l'ha provata subito sul sito vero (merge su `main` fatto in giornata), e per testarla con dati veri abbiamo fatto girare A1 Monthly su Ottobre 2026 caricando io stesso il CSV MBS che mi aveva dato — il run reale ha fatto emergere due bug che nessun test sintetico avrebbe trovato, entrambi risolti e riverificati con un secondo run reale.

**Cosa è stato fatto:**
- Creato lo schema Supabase per la categorizzazione: tabella `posts` (specchio dei post ORIGINALE, letto/scritto dalla webapp) e `categoria_secondaria_vocabolario` (vocabolario che cresce), RLS identica al pattern già in uso (`authenticated`, true/true). Migrazione applicata e registrata in `supabase/migrations/` (prima volta che questo repo traccia le migrazioni, non esisteva una convenzione).
- `a1_monthly.py`: nuova `sync_posts_to_supabase()` — upsert dei soli post ORIGINALE non-serie, senza toccare le colonne categoria sui rerun (verificato con un test diretto sul database, non solo per ragionamento: inserite righe finte, simulato un secondo upsert senza le colonne categoria, confermato che il valore esistente resta intatto). Per gli episodi della serie le categorie restano sempre incluse nel payload.
- Nuova pagina `app/agenti/a1-analytics/categorizza.html`: categoria primaria a 4 bottoni fissi, secondaria a tendina filtrata sulla primaria + testo libero che si aggiunge al vocabolario per le volte successive. Gli episodi di "Capiamo la Sabbia" non compaiono (già classificati in automatico). Stesso pattern di autenticazione (`sbFetch`/`gdcToken`) del resto della webapp.
- `page_agent_a1_v1.html`: nuova card "Categorizza post" con conteggio dinamico "N post da categorizzare" via query `count=exact` su Supabase.
- Verificati sintassi JS/Python su tutti i file toccati e tutti i link del repo con lo script scritto ieri (53 link, 0 rotti) prima del push.

**Decisioni prese:**
- Contesto: il design originale dello Step 4 prevedeva un "suggerimento di Claude" per la categoria, ma la webapp è una pagina statica senza backend e il vincolo è zero costo API aggiuntivo.
  Decisione: costruire lo schema già pronto per il suggerimento (colonne dedicate, mostrate in UI se presenti) ma lasciarlo vuoto per ora — lo popolerà la sessione Claude Code dedicata (Step 8), usando l'abbonamento Pro invece di una chiamata a pagamento.
  Alternative scartate: chiamata API diretta dal browser (violerebbe il vincolo di costo); nessuna preparazione dello schema (avrebbe richiesto una migrazione in più in futuro).
  Da rivedere se: lo Step 8 arrivasse a un'architettura diversa da quella immaginata (bottone che apre una sessione Claude Code con messaggio precompilato).

- Merge su `main` (fast-forward, nessun conflitto — `main` non si era mosso dall'inizio di questa sessione). Gianluca ha provato la pagina sul sito vero: corretto, vuota (nessun post ancora sincronizzato finché A1 Monthly non gira). Per provarla con dati veri, Gianluca ha fornito il CSV MBS di ottobre: l'ho caricato io stesso su Drive nella cartella giusta con il nome atteso dallo script (bypassando il caricamento manuale, stesso identico percorso di lettura di A1), poi lanciato A1 Monthly via workflow_dispatch.
- **Bug: upsert Supabase falliva quando il mese aveva sia episodi di serie sia post normali**
  **Sintomo:** primo run reale di A1 Monthly su Ottobre 2026 (7 post, 1 di serie) — `⚠ Errore sync posts su Supabase: 400 PGRST102 "All object keys must match"`.
  **Causa:** PostgREST rifiuta un batch di insert dove gli oggetti non hanno tutti le stesse chiavi; i post di serie hanno 3 chiavi categoria in più degli altri (per design, per non sovrascrivere mai una categoria già scelta a mano sui post normali).
  **Fix applicato:** `sync_posts_to_supabase()` divisa in due chiamate separate (post normali / post di serie), ciascuna internamente uniforme. Riverificato con un secondo run reale: `Supabase posts: 7 post ORIGINALE sincronizzati`, zero errori.
- **Bug: la UI nascondeva gli episodi di serie dal campo sbagliato**
  **Sintomo:** controllando i dati reali appena sincronizzati, 2 dei 4 episodi di serie del mese (caption scritte senza il trattino previsto, es. "Capiamo la sabbia EP2" invece di "Capiamo la sabbia - EP.2") comparivano come "da categorizzare" nella UI, pur essendo già classificati DIVULGAZIONE/GDC STUFF da A1.
  **Causa:** `classifica_serie()` in `a1_monthly.py` riconosce l'appartenenza alla serie dal solo prefisso della caption (nessun trattino richiesto) ma estrae il numero episodio con una regex più rigida che il trattino lo richiede — comportamento corretto e già documentato (fallback "Episodio Serie vuoto"). La pagina `categorizza.html` però usava proprio "episodio_serie is null" per decidere se un post fosse di serie, scambiando "numero non leggibile" per "non è serie".
  **Fix applicato:** filtro spostato su `categoria_primaria = 'DIVULGAZIONE'` (il segnale che A1 scrive sempre e solo per la serie, affidabile indipendentemente dal numero episodio) in `categorizza.html` e semplificato lo stesso controllo in `page_agent_a1_v1.html`. Confermato visivamente da Gianluca sulla pagina vera: 4 post normali mostrati come da categorizzare, i 3 episodi di serie correttamente nascosti.
- Gianluca ha categorizzato a mano i 4 post dal sito vero. Verificato su Supabase: tutti e 7 i post di Ottobre hanno ora categoria primaria+secondaria; il vocabolario secondario è cresciuto con 2 valori liberi nuovi inseriti da Gianluca durante la prova ("Gdc stuff" sotto RELATION, "Premiazioni" sotto SPORT). Osservazione non problematica: uno dei 4 post categorizzati a mano ("Campionato italiano di beach volley...") è tematicamente un episodio della serie ma la sua caption non inizia con "Capiamo la Sabbia" — A1 non l'aveva riconosciuto in automatico, Gianluca l'ha classificato DIVULGAZIONE/GDC STUFF a mano. Esattamente il caso d'uso per cui serviva una schermata manuale accanto all'automazione.

**File consegnati/modificati:** `scripts/a1_monthly.py`, `app/agenti/a1-analytics/categorizza.html` (nuovo), `app/agenti/a1-analytics/page_agent_a1_v1.html`, `supabase/migrations/20261114_add_posts_categorization.sql` (nuovo), `docs/documento-sessione-gdc-ia-team.md`; schema Supabase: tabelle `posts` e `categoria_secondaria_vocabolario` (ora con dati reali di Ottobre 2026); Drive: caricato `Oct-01-2026_Oct-31-2026_1520066349931563.csv` in "Archivio docs MBS".

---

### [2026-11-13 17:52] Step 1, 2, 3 completati e Step 6 avviato — stati agenti robusti, token Instagram rinnovato, tassonomia DIVULGAZIONE ovunque, prime pagine riorganizzate

**Riepilogo:** Prima sessione di lavoro vero sul codice (le precedenti erano solo analisi/pianificazione): chiusa la robustezza degli stati agenti (Step 1); nello Step 2 scoperta — leggendo i log reali di più run — che il rinnovo automatico del token Instagram non ha mai funzionato davvero (un conto alla rovescia confermato ogni settimana verso una scadenza fissa, non un vero sposta-scadenza); Gianluca ha poi fatto il login manuale Meta e il rinnovo è stato verificato funzionante con due run reali lanciati da Claude Code; nello Step 3 la categoria DIVULGAZIONE è stata propagata in tutti e 4 i documenti/script della catena A1-A4.

**Cosa è stato fatto:**
- Step 1 implementato e pushato (commit `4fd6076`): `a1_monthly.py` — `main()` ora avvolge il corpo reale (rinominato `_run()`) in un try/except che scrive stato "error" su qualunque eccezione invece di lasciare "working" bloccato per sempre; `page_home_v25.html` — nuovo stato "error" reale in `mapState`/`CFG`/`PRI`/`STATO_PILLS`, scadenza di 3 ore sullo stato "working" (oltre la soglia passa a "error"), rimosso codice morto verificato via grep (`setStato`, `STATO_CYCLE`, `STATO_LABELS`).
- Decisioni aperte dello Step 1 risolte: Gianluca ha confermato esplicitamente di procedere con le risposte di default proposte (override manuale mantenuto; tabella `user_settings` riusata per lo Step 9) — commit `7682bd9`.
- **Bug: rinnovo automatico token Instagram non ha mai davvero funzionato**
  **Sintomo:** `ig_token_refresh.py` risultava verde per mesi, ma il token è scaduto comunque il 31/10/2026.
  **Causa:** confrontando i log di 5 run consecutivi (5/10 → 2/11), i rinnovi del 19/10 e del 26/10 hanno restituito **la stessa identica scadenza** (2026-10-31T18:20:21) invece di una nuova finestra di 60 giorni — la chiamata `fb_exchange_token` su questo token conferma solo il conto alla rovescia verso una scadenza fissa legata all'ultimo login manuale, non la estende. Non ancora chiaro se sia un limite intrinseco del tipo di token/endpoint usato o risolvibile diversamente — verificabile solo dopo il prossimo login manuale di Gianluca.
  **Fix applicato:** nessuno per la causa radice (richiede prima il login manuale e poi un'osservazione empirica del rinnovo successivo); risolto però un bug indipendente nello stesso script, vedi sotto.
- **Bug: perdita di visibilità sulla scadenza nota in caso di fallimento**
  **Sintomo:** nessuno diretto — scoperto leggendo il codice durante l'indagine sul bug sopra.
  **Causa:** `update_supabase_token_status()` in `ig_token_refresh.py` scriveva sempre `expires_at` nel payload, anche `None` sui fallimenti, azzerando ogni volta l'unica informazione affidabile sul countdown reale.
  **Fix applicato:** su fallimento lo script ora legge e riscrive il valore già presente su Supabase invece di sovrascriverlo con null. Commit `0f6863e`.
- **Bug: A1 Stories Daily segnalava successo anche su errore di autenticazione**
  **Sintomo:** nessuna story salvata da inizio novembre, workflow sempre verde.
  **Causa:** `fetch_active_stories()` in `a1_stories_daily.py` catturava qualunque `HTTPError` (incluso l'OAuth 400 del token scaduto) e lo trattava come "nessuna story attiva".
  **Fix applicato:** rimosso il try/except — un errore reale ora fa fallire lo script in modo visibile; il caso legittimo di lista vuota (risposta 200 senza stories) resta gestito come prima. Commit `0f6863e`.
- Gianluca ha fatto il login manuale su Meta (Graph API Explorer, app "GDC IA TEAM"): generato un nuovo token short-lived con i permessi necessari, scambiato per long-lived via `fb_exchange_token`, aggiornato a mano il secret `IG_ACCESS_TOKEN` su GitHub.
- Verifica con due run reali lanciati da Claude Code via `workflow_dispatch`: `a1_stories_daily.yml` → successo, risposta IG reale "nessuna story attiva" (non più l'errore OAuth); `ig_token_refresh.yml` → successo, nuova scadenza **2027-01-12** (quasi 60 giorni da oggi) — conferma che il meccanismo di rinnovo funziona bene ripartendo da un login reale. La domanda "perché prima restituiva sempre la stessa scadenza fissa" resta senza una spiegazione certa, ma non più bloccante — da monitorare nelle prossime settimane.
- Propagata DIVULGAZIONE come quarta categoria primaria (secondaria GDC STUFF) in tutti e 4 i documenti/script: `a1_monthly.py` (codice); documento tecnico A1 (.docx, v4→v5, editato via skill docx — unzip/merge_runs/edit XML/rezip/valida/rendering PDF di verifica); prompt A2 (md, v14→v15); prompt A4 (md, v6→v7). A3 confermato già corretto. Nei prompt A2/A4 colto anche il beneficio collaterale già previsto: il riconoscimento della serie "Capiamo la Sabbia" passa dal solo nome del post al campo categoria dedicato, più robusto. Le 3 copie aggiornate (A1 v5, A2 v15, A4 v7) consegnate a Gianluca come file e tutti e 4 i prompt (incluso A3 invariato) committati su GitHub in `docs/prompts/` — Gianluca ha confermato che possono stare nel repo pubblico (nessun segreto vero, solo playbook operativo e link Drive).
- Controllata la cartella sospetta `processed/` dentro AGENTE 6 su Drive (dall'audit precedente): confermata vuota (0 file, residuo del service account mai usato) — eliminata da Gianluca manualmente.
- Anticipata la riorganizzazione cartelle GitHub (Step 6, prima prevista insieme allo Step 5) su richiesta di Gianluca: spostate in `app/` e `app/agenti/a{1,2,3,4}-xxx/` solo le pagine home/hub/A1-A4, lasciando deliberatamente fuori tutto il lato A5-A7/company/pipeline/login/GDC Studio per non dover toccare le loro automazioni Python. Aggiornati tutti i link interni di conseguenza, verificati con uno script scritto per l'occasione che risolve ogni link contro il filesystem reale (ha trovato un errore reale fatto durante l'edit, poi corretto).

**Decisioni prese:**
- Contesto: fino a quando dura la transizione (Step 8 non pronto), come gestire i cicli mensili reali di A2/A3/A4.
  Decisione: restano sui Progetti Claude.ai come oggi, con i prompt aggiornati ricaricati manualmente da Gianluca.
  Alternative scartate: congelare/rimandare i cicli in attesa del nuovo sistema — scartata perché Gianluca vuole continuità operativa nel frattempo.
- Contesto: dove far vivere i 4 prompt agente in modo persistente e leggibile da future sessioni Claude Code, dato che il repo GDC-DASHBOARD è pubblico.
  Decisione: pubblicarli così come sono in `docs/prompts/` nel repo pubblico — confermato da Gianluca dopo aver segnalato che contengono il playbook operativo e i link alle cartelle Drive (ma nessun segreto vero).
  Alternative scartate: repo privato, o un repo separato solo per i prompt — non valutate necessarie da Gianluca.
  Da rivedere se: in futuro uno dei prompt dovesse contenere dati davvero sensibili (es. credenziali, dati personali di terzi).

**File consegnati/modificati:** `app/page_home_v25.html` (ex `page_home_v25.html`), `app/page_hub_v1.html` (ex `page_hub_v1.html`), `app/agenti/a1-analytics/page_agent_a1_v1.html`, `app/agenti/a2-analyst/page_agent_a2_v3.html`, `app/agenti/a3-planner/page_agent_a3_v1.html`, `app/agenti/a4-brief/page_agent_a4_v1.html` (tutte e quattro ex root), `page_agent_a5_v1.html`, `page_agent_a6_v1.html`, `page_agent_a7_v1.html`, `page_company_v2.html`, `page_pipeline_v1.html`, `page_login_v6.html`, `gdc_studio.html` (solo link aggiornati, restano in root), `sw.js`, `scripts/a1_monthly.py`, `scripts/ig_token_refresh.py`, `scripts/a1_stories_daily.py`, `.gitignore`, `docs/documento-sessione-gdc-ia-team.md`, `docs/prompts/Agente1_auto_prompt_v5.docx`, `docs/prompts/Agente2_auto_prompt_v15.md`, `docs/prompts/Agente3_auto_prompt_v12.md`, `docs/prompts/Agente4_auto_prompt_v7.md`; consegnati anche a Gianluca come file (A1 v5, A2 v15, A4 v7) per ricaricarli nei Progetti Claude.ai.

---

### [2026-11-12 22:29] Analisi completa del sistema, decisione di ricostruire A1-A4 da Claude Code, audit infrastruttura

**Riepilogo:** Prima sessione documentata: dall'analisi iniziale della webapp e del flusso Claude Projects → Drive (percepito come macchinoso), attraverso ricerche su API Instagram/GitHub/architettura, fino alla decisione di ricostruire la catena editoriale A1-A4 lavorando direttamente da Claude Code con output HTML protetti da Supabase, con audit completi di GitHub Actions, struttura Drive/GitHub e Supabase che hanno fatto emergere problemi reali e urgenti (token Instagram scaduto, bug silenzioso su A1 Stories Daily, pallini di stato agenti non affidabili).

**Cosa è stato fatto:**
- Analisi dell'architettura esistente (pagine webapp, script Python, workflow GitHub Actions, pipeline aziende A5-A7) — sistema più automatizzato del previsto (A1 e A7 già completamente automatici).
- Ricerca sui nuovi strumenti dell'API Instagram (repost via API ora possibile come solo conteggio, non dettaglio — il CSV manuale da Meta Business Suite resta necessario) e su progetti GitHub comparabili (nessun equivalente diretto trovato; utili come riferimento: `md2pptx`, pattern di approvazione umana in agenti di scheduling open source).
- Diagnosticata la causa storica del limite "file binari grandi non caricabili via connector MCP" (base64 troncato, documentato allo Step 15 della storia del progetto) che ha originato la regola "Gianluca carica sempre a mano su Drive".
- Esplorate e scartate più soluzioni per il trasferimento file (mail come imbuto, sincronizzazione Drive Desktop, automazione browser di claude.ai) a favore di: lavorare direttamente da Claude Code sullo stesso repo, con output HTML invece di binari.
- Letti e analizzati integralmente i 4 prompt agente (A1 v4, A2 v14, A3 v12, A4 v6), trovando un'incongruenza reale di tassonomia tra A3 (già con categoria DIVULGAZIONE) e A1/A2/A4 (ancora senza).
- **Bug: A1 Monthly fallito, repost Instagram inattivi da inizio mese**
  **Sintomo:** run di A1 Monthly del 2/11 fallito; `A1 Stories Daily` sempre verde ma non salva stories da inizio novembre; `IG Token Refresh` fallito 2 volte consecutive.
  **Causa:** token Instagram scaduto per davvero il 31/10/2026 (non più rinnovabile via refresh, serve nuovo login manuale); `ig_token_refresh.py` ha un bug di margine/timing (tenta il rinnovo quando il token è già scaduto); `a1_stories_daily.py` interpreta un errore OAuth 400 come "nessuna story attiva" invece di segnalarlo.
  **Fix applicato:** nessuno ancora — diagnosi completa, intervento pianificato come Step 2 della pipeline.
- **Bug: pallini di stato agenti nella home spesso in stati sbagliati**
  **Sintomo:** Gianluca trova spesso i pallini di stato (queued/working/done/riposo/sleep) in stati che non corrispondono alla realtà.
  **Causa:** `a1_monthly.py` scrive `stato='working'` senza try/except attorno a `main()` — un crash lascia lo stato bloccato su "in corso" per sempre; `mapState()` lato webapp applica una scadenza automatica a `done`/`riposo` ma non a `working`; A2/A3/A4 non scrivono mai automaticamente il proprio stato (solo click manuale); presente anche codice morto (`setStato`/`STATO_CYCLE`) da un design precedente.
  **Fix applicato:** non ancora — diagnosi completa e fix concordato, lavoro avviato come Step 1 della pipeline (in corso).
- Audit completo dei 10 workflow GitHub Actions del repo (via API, run reali e log) — trovata anche una discrepanza sistemica: i workflow a cadenza frequente (ogni 30 min/ogni ora) girano in pratica ogni 7-9 ore, limite di scheduling GitHub Actions sotto carico.
- Audit struttura Google Drive (via ricerca diretta) confrontata con la struttura piatta di GitHub — trovata una cartella sospetta (`processed/` sotto AGENTE 6) in contraddizione con una decisione documentata in passato.
- Audit completo Supabase (tabelle, policy di sicurezza, performance) — confermato pulito per la parte GDC IA TEAM; trovato un progetto completamente estraneo e abbandonato (generatore di thumbnail YouTube, tabelle `thumb_*`) e tre tabelle scaffolding mai collegate (`user_settings`, `pipeline_states`, `drive_cache`).

**Decisioni prese:**
- Contesto: come eliminare il passaggio manuale "scarica da Claude Projects → carica su Drive" per la catena editoriale A1-A4.
  Decisione: lavorare direttamente da una sessione Claude Code dedicata sullo stesso repo; output in HTML (non più pptx/pdf/docx) servito da GitHub Pages; contenuto vero su Supabase dietro il login esistente, template pubblico vuoto.
  Alternative scartate: automazione via API Anthropic a pagamento (scartata per vincolo "zero costo extra"); automazione browser di claude.ai (scartata per rischio ToS e fragilità); mail come imbuto di trasferimento file; sincronizzazione Drive Desktop (scartate perché Gianluca lavora da dispositivi diversi e i file hanno destinazioni diverse).
  Da rivedere se: il vincolo "zero costo extra" cambiasse, o se emergessero limiti concreti nel lavorare da sessioni Claude Code multiple sullo stesso repo.
- Contesto: come trattare la serie "Capiamo la Sabbia" nella tassonomia categorie.
  Decisione: nuova categoria primaria dedicata "DIVULGAZIONE" (secondaria "GDC STUFF"), allineando A1/A2/A4 a quanto A3 già assumeva.
  Alternative scartate: mantenere la combinazione a due campi (GDC STUFF primaria + SPORT secondaria) già in uso in A1/A2/A4.
- Contesto: come gestire la categorizzazione mensile dei post (oggi manuale su celle gialle di uno spreadsheet).
  Decisione: schermata dedicata nella webapp, suggerimento automatico + conferma umana, con categoria secondaria a tendina che si espande con le nuove voci inserite a mano.
  Alternative scartate: automazione piena senza conferma (rischio di inquinare analisi che richiedono giudizio editoriale); restare sullo spreadsheet con interfaccia solo abbellita.
- Contesto: ambito di A4 nel rebuild.
  Decisione: automatizzare solo la parte "apertura mese" (brief PDF→HTML); il lavoro libero post per post durante il mese resta conversazione Claude Code non automatizzata.
  Alternative scartate: nessuna — emerso leggendo il prompt di A4, non una vera alternativa valutata e scartata.

**File consegnati/modificati:** nessun file di codice modificato in questa sessione (solo analisi/pianificazione); creata la cartella `docs/` e questo documento (`docs/documento-sessione-gdc-ia-team.md`).

**Impatto su Vision/Pipeline:** Vision e Pipeline create per la prima volta in questa sessione (documento inesistente prima, essendosi lavorato finora da Progetti Claude.ai senza repository).

---
