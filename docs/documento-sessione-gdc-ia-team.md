# Documento di Sessione — GDC IA TEAM

**Versione:** 51
**Ultimo aggiornamento:** 2026-11-20 22:34

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

**Stato:** completato — tutti i 5 punti costruiti e verificati con run reali (A2, A3, A4).

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
- [2026-11-14] Punto 3a: creata tabella Supabase `report_mensili` (condivisa a2/a3/a4, `agente`+`mese` chiave, RLS identica al pattern già in uso) e nuova pagina `app/agenti/a2-analyst/report.html` — elenco mesi con report disponibili, apertura dentro un `<iframe srcdoc>` per isolare lo stile scuro del report dallo stile chiaro dell'app. Card "Report mensili" aggiunta alle Azioni di A2. Verificata la pipeline Supabase→iframe con una riga di test (scritta ed eliminata subito dopo, nessun dato reale coinvolto).
- [2026-11-14] Punto 3b: riscritto il prompt di A2 da v15 a v16 (nuovo file `Agente2_auto_prompt_v16.md`, v15 rimosso — stessa convenzione già in uso per gli altri agenti, un solo file per agente con lo storico nelle "Note di Versione" interne). Cambia solo il contenitore dell'output: pagina HTML autonoma scritta su Supabase (`report_mensili`, via connector MCP) invece di PPTX consegnato con `present_files` e caricato a mano su Drive. Tutta la sostanza progettuale (formule ER/viralità/sentiment, normalizzazione categorie, riconoscimento e regole della serie "Capiamo la Sabbia", badge, Top3, Mix Topic, Checklist Pre-Avvio) resta identica alla v15 — tradotte solo le parti tecniche: layout da coordinate PptxGenJS (pollici/pt) a CSS responsive (flexbox, breakpoint 600px); colori hex con '#' (convenzione invertita rispetto a PPTX, dove il '#' era vietato); rimossa la scala di altezza riga adattiva per le stories e il limite di altezza della tabella serie, non più necessari senza slide a altezza fissa (la pagina HTML scorre liberamente); Chiusura sessione riscritta per scrivere su Supabase invece di generare il file e aggiornato il link nel log `activity_log`.
- [2026-11-14] Punto 3c: Gianluca ha fatto girare A2 v16 per davvero su Ottobre 2026 (Claude.ai Projects) — report visibile sulla webapp, ma Mix Topic incompleto.

  **Bug: categorie inserite a mano dalla webapp invisibili ad A2 (e A3/A4)**

  **Sintomo:** nel report generato da A2, la sezione Mix Topic (basata su Categoria Primaria+Secondaria per post) risultava incompleta — solo i 3 episodi della serie "Capiamo la Sabbia" avevano categoria, gli altri 4 post ORIGINALE del mese no.

  **Causa:** la schermata di categorizzazione (Step 4) scrive le categorie scelte a mano solo sulla tabella Supabase `posts`. A2 (e A3/A4) leggono ancora il Google Sheet "Instagram_Analytics_GDC", non Supabase — e `compile_sheet_post()` in `a1_monthly.py` scriveva sempre le colonne Categoria vuote per i post non-serie (erano celle gialle pensate per la compilazione manuale diretta sul foglio, flusso superato dalla webapp). Verificato leggendo il Google Sheet reale: le 4 categorie mancanti su 7 post corrispondevano esattamente ai 4 post categorizzati a mano via webapp.

  **Fix applicato:** nuova `fetch_posts_categorization_overrides()` in `a1_monthly.py` — legge da Supabase le categorie del mese corrente; `compile_sheet_post()` le usa quando A1 non ha già riconosciuto automaticamente un post come episodio di serie. Verificato con una seconda run reale di A1 Monthly su Ottobre: il Google Sheet ora ha "GDC STUFF/Stampa 3D" e "RELATION/Gdc stuff" per i due post controllati (prima vuoti), serie ed episodi invariati, repost ancora correttamente vuoto. Prossimo passo: Gianluca rilancia A2 su Ottobre per vedere il Mix Topic corretto nel report.

  Nota: è un problema architetturale transitorio — con la migrazione completa (A1-A4 che leggono/scrivono tutti su Supabase, non più sul Google Sheet) questa doppia fonte di verità sparirà da sola. Per ora il fix sopra tiene i due sincronizzati.
- [2026-11-15] Gianluca ha verificato il report corretto (Mix Topic completo, numeri controllati a mano) e ha chiesto se ora — passati mesi dall'inizio del progetto e con l'output in HTML — fosse possibile avere le copertine reali dei post invece del placeholder colorato usato da sempre. Verificato con un run reale: l'API Instagram restituisce `media_url`/`thumbnail_url` per i post ORIGINALE — non è mai stato un limite di permessi o di tempo, semplicemente A1 non li richiedeva. Controllati anche i limiti del piano free Supabase (database 29/500 MB, storage 0/1 GB, egress 5 GB/mese) prima di procedere: nessun rischio concreto ai volumi di questo progetto (poche immagini al mese, un solo utilizzatore).

  Implementato: bucket pubblico Supabase Storage `post-covers`; nuova `upload_post_cover_image()` in `a1_monthly.py` — scarica la copertina giusta per tipo (frame per i Reel via thumbnail_url, prima slide per i caroselli via children[0], immagine diretta per i post singoli) e la ri-ospita sul bucket, perché gli URL di Instagram sono firmati e scadono; l'URL pubblico risultante va sia su Supabase (`posts.image_url`, nuova colonna) sia sul Google Sheet (nuova colonna 24 "Immagine URL"). Prompt A2 aggiornato (v16→v17, nuovo file `Agente2_auto_prompt_v17.md`): mostra l'immagine reale dentro un contenitore a dimensione fissa (`.gdc-cover`, 190×150px desktop / 100%×150px mobile) con `object-fit:cover` — qualsiasi proporzione reale della foto viene ritagliata per riempire esattamente lo stesso spazio del vecchio placeholder, mai una foto che deforma o sfonda il layout del blocco post; fallback al placeholder colorato via `onerror` se il link si rompe, o se la colonna è vuota (REPOST, o download temporaneamente fallito).

  Verificato con una run reale di A1 Monthly su Ottobre 2026: tutti i 7 post ORIGINALE hanno ricevuto un `image_url` valido, i file caricati sul bucket sono JPEG reali da 116–339 KB (controllato leggendo i metadati di `storage.objects`, non solo che la riga non fosse vuota), e la colonna 24 del Google Sheet risulta popolata correttamente (vuota solo per il repost, come atteso).
- [2026-11-15] Gianluca ha rilanciato A2 con il prompt v17: le immagini reali si vedono correttamente nel report. Nota per dopo (non bloccante, rimandata esplicitamente da Gianluca): le foto escono quadrate invece che nel rettangolo 190×150 previsto — da controllare in una sessione futura, non urgente.
- [2026-11-15] **Bug: pallino/logo di A2 in home bloccato su "in coda"** — Sintomo: dopo che A2 ha finito un report, l'icona/badge di A2 nella webapp restava rossa ("in coda") invece di passare a "completato". Causa: nessuno script scrive mai `agent_states` → 'done' per A2 — solo `a1_monthly.py` lo scrive 'ready' (in coda) quando A1 finisce; la riga non veniva più aggiornata dopo. Verificato leggendo `agent_states`: nella run appena fatta A2 aveva comunque scritto 'done' di propria iniziativa (ha il connector Supabase e ha dedotto da solo di doverlo fare, imitando A1) — corretto ma non garantito per i run futuri, perché non era nel prompt. Fix applicato: prompt A2 v17→v18 — Step 0 scrive `agent_states`→'working' prima di leggere i dati, Chiusura scrive `agent_states`→'done' con mese/n_post/n_stories (stessi campi letti dalla Tab Run della pagina di A2). Non ancora verificato con un nuovo run reale (il comportamento "giusto" di questa run specifica era già quello scritto spontaneamente da A2, non ancora quello scritto dal prompt v18).
- [2026-11-15] Punto 4 — A3: costruito lo stesso lavoro fatto per A2, adattato alla decisione già presa (A3/A4 niente grafici, solo calendario/elenco mesi). Riusata la tabella `report_mensili` esistente (già pensata per agente a2/a3/a4, nessuno schema nuovo necessario) — verificata con una riga di test (mese fittizio "Test collegamento"), rimasta da eliminare perché la conferma della `DELETE` non è arrivata in tempo (stesso comportamento già visto con il test di A2) — da confermare a Gianluca. Nuova `app/agenti/a3-planner/piano.html` (stesso meccanismo iframe di `report.html`), card "Piani editoriali" su A3, messaggio precompilato aggiornato (citava ancora file pptx su Drive — report A2 e piano precedente che con la v18 di A2 non esistono più lì).

  Prompt A3 v12→v13: oltre al cambio di contenitore (HTML su Supabase invece di PPTX, stessa logica della v16 di A2), anche l'**input** di A3 è cambiato — leggeva il report di A2 e il proprio piano precedente come file pptx su Drive, che con la migrazione di A2 non vengono più prodotti. Spostati su Supabase (`report_mensili`, letto tramite connector MCP). Incluse fin da subito (lezione della v18 di A2, qui anticipata) l'auto-segnalazione di stato su `agent_states` e la segnalazione di A4 pronto alla chiusura di A3 — completando la catena A1→A2→A3→A4. Di conseguenza anche il prompt di A2 è stato aggiornato (v18→v19): mancava la riga che segnala A3 pronto quando A2 finisce (stesso bug trovato ieri per A2, qui chiuso anche per lo step successivo della catena).

  Non ancora verificato con una run reale di A3 — prossimo passo prima di considerare il punto 4 chiuso.
- [2026-11-15] Punto 5 — A4: stesso lavoro, adattato alla natura particolare di A4 — a differenza di A2/A3 (un documento al mese), A4 produce un brief di apertura mese (sez. 1-4 del suo prompt) **più** lavoro libero post per post per il resto del mese (sez. 6), che non produce nessun documento e quindi non va migrato — resta conversazione pura, come già deciso nella sessione del 12/11 ("automatizzare solo la parte apertura mese; il lavoro libero resta conversazione non automatizzata"). Migrato solo il brief di apertura mese.

  Nuova `app/agenti/a4-brief/brief.html` (stesso meccanismo lista+iframe di `report.html`/`piano.html`), card "Brief mensili" su `page_agent_a4_v1.html`, messaggio precompilato riscritto (citava ancora piano A3 e report A2 come file pptx su Drive, non più prodotti dalla migrazione di A2/A3; i dati A1 restano sul Google Sheet, non toccati).

  Prompt A4 v7→v8 (nuovo file `Agente4_auto_prompt_v8.md`, v7 rimosso): cambio di contenitore (HTML su Supabase invece di PDF via `present_files` + upload manuale su Drive); input di piano A3 e report A2 spostato su Supabase (`report_mensili`, come già fatto per A3); aggiunta nuova sez. 4.3 con la struttura tecnica della pagina HTML (palette blu propria, card responsive, nessuno script/font esterno); incluse fin da subito (lezione di A2/A3) `agent_states`→'working' all'apertura e →'done' alla chiusura — nessuna riga 'ready' per un agente successivo, perché A4 è l'ultimo della catena A1→A4 migrata e A5-A7 non sono sequenziali a questo passaggio. Sezioni 5-9 (struttura brief per formato, lavoro post per post, serie Capiamo la Sabbia, revisione, tono) lasciate invariate in sostanza.

- [2026-11-15, più tardi] **Run reali di verifica — A3 e A4, Step 5 completato.** A3 (prompt v13) ha generato il piano di Novembre 2026 per davvero: scritto correttamente su `report_mensili` (21.613 caratteri, verificato leggendo l'HTML reale), `agent_states` a3→done e a4→ready. Durante la run A3 ha incontrato da solo il gap previsto per i mesi a cavallo della migrazione (piano A3 di Ottobre e report A2 di Settembre non esistono su Supabase, perché generati prima che A2/A3 iniziassero a scriverci) — l'ha gestito di propria iniziativa leggendo il piano di Ottobre direttamente dal vecchio file su Drive, segnalandolo sia in chat sia come nota esplicita dentro il piano stesso. Verificato anche che il piano contenga davvero le 7 sezioni previste dal prompt.

  A4 (prompt v8) ha incontrato lo stesso gap in modo più rigido: il prompt dice esplicitamente di fermarsi e comunicare se un dato obbligatorio manca (report A2 Settembre, piano A3 Ottobre), quindi si è fermato con `agent_states` bloccato su 'working' invece di risolverlo da solo come A3. Risolto passando ad A4 i link Drive diretti ai due file mancanti (stessa cartella e stesso nome file usati prima della migrazione) — A4 li ha letti e ha completato il brief. Verificato: `report_mensili` a4/Novembre 2026 scritta (19.744 caratteri, HTML ben formato), `agent_states` a4→done, `activity_log` con link a `brief.html?mese=Novembre%202026` (il primo link che punta al nuovo sistema invece che a una cartella Drive).

  **Nota per il futuro:** questo gap sui mesi a cavallo della migrazione è transitorio e non si ripresenterà — da Dicembre 2026 in avanti ogni piano/report/brief sarà già su Supabase quando il mese successivo lo richiede. Non è stato necessario nessun fix di prompt: il comportamento "fermati e comunica" di A4 era quello corretto e voluto, l'intervento giusto era fornire i dati mancanti, non modificare l'automazione.

  **Step 5 completato.** Tutti i 5 punti costruiti e verificati con run reali per A2, A3 e A4.

### Step 6 — Riorganizzazione cartelle GitHub + pulizia grafica/organizzazione

**Stato:** in corso — riorganizzazione cartelle completata per le pagine a basso rischio (nota 13/11); la pulizia grafica/UX, inizialmente rimandata a fine pipeline, è stata **anticipata su richiesta di Gianluca il 16/11** (prima passata: redesign home page — vedi nota sotto). Lo Step 8 non ha ancora avuto una prova reale completa, lo Step 9 non è iniziato: la pulizia grafica procede comunque in parallelo, non più strettamente "per ultima".

**Obiettivo:** la struttura del repo (oggi completamente piatta) rispecchia quella già ordinata di Drive, per agente.

**Decisioni progettuali:**
- Struttura Drive di riferimento (confermata via audit): cartella radice "GDC IA TEAM" → AGENTE 1.2, AGENTE 2, AGENTE 3, AGENTE 4, AGENTE 6 (con sottocartella Aziende), AGENTE 7 — ognuna con le proprie sottocartelle.
- Proposta struttura GitHub: `index.html`/`manifest.json`/`sw.js` restano in root (vincolo PWA); nuova cartella `app/` per le pagine esistenti (incluso `app/agenti/a1-analytics/`, `a2-analyst/`, `a3-planner/`, `a4-brief/`); nuova cartella `editoriale/` per gli output mensili HTML; nuova cartella `docs/` per la documentazione di progetto (vedi sotto); `scripts/` e `icons/` invariate.
- Spostare le pagine esistenti richiede aggiornare `manifest.json` (start_url), il redirect di `index.html`, e tutti i link interni tra pagine — da fare con attenzione e verifica di navigazione dopo, non è un'operazione a costo zero.
- Trovata una cartella sospetta su Drive, `processed/` dentro AGENTE 6 (creata dal service account), che contraddice la decisione documentata "A7 non usa una cartella processed/" — da controllarne il contenuto prima di decidere se eliminarla.
- **Il documento di sessione vive in `docs/documento-sessione-gdc-ia-team.md`** (questo file), deciso esplicitamente da Gianluca come posto fisso nel repo invece che fuori, dato che finora si lavorava dai Progetti Claude.ai senza repo.
- **Pulizia grafica/organizzazione (decisione del 15/11/2026, da fare per ultima):** Gianluca non è soddisfatto di alcuni aspetti emersi lavorando — es. per vedere la Dashboard KPI di A2 bisogna entrare in una scheda/card separata invece di vederla più direttamente; ci sono residui della versione precedente (pptx-era) non più usati che vanno individuati e rimossi. Nessun elenco esaustivo ancora raccolto: va fatto un audit dedicato quando si arriva a questo punto della pipeline, non solo questi due esempi.

**Criterio di completamento:** tutte le pagine esistenti funzionano dai nuovi percorsi, nessun link interno rotto, nuove pagine editoriali già nella struttura definitiva; passata la pulizia finale, nessun residuo della versione precedente e la navigazione rispecchia come Gianluca vuole usare la webapp (non solo come l'abbiamo costruita in ordine).

**Note (cronologia dello step):**
- [2026-11-12] Audit completo struttura Drive vs GitHub eseguito. Confermato repo pubblico (verificato via fetch diretto). Cartella `docs/` creata in questa sessione per ospitare questo documento.
- [2026-11-13] Gianluca ha chiesto di anticipare la riorganizzazione (invece di farla insieme allo Step 5) per far nascere le pagine nuove già nel posto giusto. Eseguita solo la parte a basso rischio: `page_home_v25.html` e `page_hub_v1.html` → `app/`; le quattro pagine agente → `app/agenti/a{1,2,3,4}-{analytics,analyst,planner,brief}/`. Lasciati deliberatamente in root (zero rischio di toccare automazioni fuori perimetro): `index.html`/`manifest.json`/`sw.js` (vincolo PWA), `page_login_v6.html` (bootstrap PWA — spostarlo avrebbe richiesto toccare il link di login/redirect in ogni singola pagina del repo, incluse quelle A5-A7 fuori perimetro, per un guadagno minimo), `page_agent_a5/a6/a7_v1.html`, `page_company_v2.html`, `page_pipeline_v1.html`, `gdc_studio.html`, `gdc_reset_tool.html` — i primi tre sono referenziati da `WEBAPP_BASE` dentro script Python di A5-A7 (`a7_followup.py`, `pipeline_notify.py`) che non si è voluto toccare in questo giro. Aggiornati tutti i link che puntano da/verso i file spostati (incluse le pagine rimaste in root). Scritto ed eseguito un verificatore automatico che risolve ogni link relativo contro il filesystem reale (50 link, 0 rotti) — ha anche scovato un errore reale fatto durante l'edit (profondità sbagliata nel link di login dalle pagine agente, 2 livelli invece di 3). Verificata anche sintassi Python/JS su tutti i file toccati. Push fatto sul branch di lavoro, non su main — il sito live su GitHub Pages non è impattato finché non c'è merge. Resta da fare: cartella `editoriale/` per gli output mensili (Step 5), eventuale riordino di A5-A7/company/pipeline/login (non ancora deciso se necessario).
- [2026-11-15] Gianluca ha chiesto di mettere in pipeline, per dopo aver finito tutti gli step di funzionamento, una pulizia di grafica/organizzazione delle sezioni — due esempi dati: navigazione della Dashboard KPI di A2 (oggi dentro una scheda separata, non piace) e residui della versione precedente non più usati. Non ancora iniziato per scelta esplicita: prima si finisce il funzionamento (Step 5 punti 4-5, poi 7, 8, 9), poi si riordina.
- [2026-11-16] **Supera la decisione del 15/11/2026** — Gianluca ha chiesto di anticipare comunque una prima passata di pulizia grafica (via mockup iterativo su Artifact, poi applicata al codice reale). Oggetto: `page_home_v25.html` e card A1. Criterio guida dato da Gianluca per ogni elemento dubbio: *"il pulsante serve? Se sì lo teniamo, se no lo togliamo."*

  **Cosa è cambiato:**
  - Pillola **Hub** (sinistra, punta rivolta a sinistra come un "torna indietro") e **Attiva notifiche** (destra, piena/accent finché non attive, poi neutra come Hub) — ordine invertito rispetto a prima. La punta della pillola Hub non usa un CSS `border` (si tagliava in modo innaturale sulla punta, verificato sul mockup): due livelli sovrapposti con lo stesso `clip-path`, quello esterno fa da bordo uniforme.
  - La card "Ciclo editoriale mensile" (Step 8) è diventata una pillola unica: bottone rotondo-pillola a sinistra (icona segnaposto per il simbolo Claude Code — non ho l'asset ufficiale, da sostituire quando disponibile) per aprire la sessione dedicata, etichetta centrale in grassetto, "Copia messaggio" a destra nella stessa forma, a specchio (icona verso il bordo esterno su entrambi, testo verso il centro).
  - Schede **A1/A2/A3/A4**: tolta la descrizione testuale sotto il titolo; angolo sinistro della card ora concentrico al box del logo (raggio 30px = raggio logo 20px + 10px di distanza bordo-card/bordo-logo, calcolato dai valori CSS reali, verificato sul mockup prima di applicarlo).
  - A1: rimossi i pulsanti "Avvia Run Manuale" e "→ Analytics GDC" (non superano il criterio "serve?" secondo Gianluca). Resta "Apri MBS" (invariato) + nuovo **"Carica CSV"**, che apre `agenti/a1-analytics/carica_mbs.html` (pagina nuova).
  - A2/A3/A4: tolti "Copia messaggio" e "→ A2/A3/A4 in Claude" dalla home (il percorso principale è ora il ciclo unico; il percorso singolo-agente resta disponibile ma si sposta in una tab della pagina del singolo agente — non ancora fatto, prossimo passo). Resta un solo pulsante, **dinamico**: "Vedi report/piano/brief — [mese più recente]", che interroga `report_mensili` per il mese più recente di quell'agente ad ogni caricamento pagina (nuova `loadLatestReports()`) invece di un link fisso — si aggiorna da solo ogni mese, nessun link da toccare a mano. `renderActions()`/`copyMsg()` (la vecchia logica a 3 pulsanti dipendente dallo stato) rimossi, non più usati.

  **Decisione presa in corso d'opera — MBS senza Drive:** Gianluca ha chiesto se fosse possibile scaricare il CSV di Meta Business Suite in modo automatico. Verificato: questa sessione non ha accesso browser a Meta (nessun Claude in Chrome/computer use disponibile in un ambiente cloud), e la ricerca del 12/11 aveva già confermato che l'API Instagram/Meta espone solo il conteggio dei repost, non i dettagli — l'export CSV dalla dashboard web resta necessario, non automatizzabile in modo affidabile (uno script che si loggasse da solo su Meta sarebbe fragile e rischioso lato ToS). **Deciso**: il passo manuale di export resta, ma la destinazione cambia — niente più cartella Drive con nome file esatto, upload diretto su Supabase Storage dalla webapp.
  - Creato bucket Supabase Storage privato `mbs-csv` + policy RLS `mbs_csv_authenticated_all` (ALL su `storage.objects` dove `bucket_id='mbs-csv'`, ruolo `authenticated`) — stesso pattern già in uso per `thumb-assets`.
  - Nuova pagina `app/agenti/a1-analytics/carica_mbs.html`: selettore mese/anno (default mese precedente) + drag&drop o file picker per il CSV, upload diretto via `POST .../storage/v1/object/mbs-csv/{anno}-{mese}.csv` con `x-upsert:true` (sovrascrivibile se ri-caricato).
  - **Non ancora fatto, segnalato esplicitamente nella pagina stessa**: `a1_monthly.py` legge ancora il CSV dei repost dalla cartella Drive, non da questo nuovo bucket — il caricamento funziona già or a, ma il lato lettura va aggiornato in un passaggio separato, da verificare con un run reale prima di fidarsene (stesso principio già seguito per ogni altra automazione di questo progetto: costruire e poi verificare con un caso vero, non solo a ragionamento).

  **Verifiche fatte:** sintassi JS di `page_home_v25.html` e `carica_mbs.html` (`node --check`); controllo automatico di tutti i link locali del repo (33 link, 0 rotti) dopo le modifiche; bucket e policy Supabase confermati con query diretta.

  **Residuo noto, non toccato in questo giro:** `MSGS.A2/A3/A4`, `PROJ`, `DRIVE`, `FILE_CUR`, `FILE_FMT` in `page_home_v25.html` sono rimasti nel codice ma non sono più referenziati da nessun pulsante della home (dead code) — restano usati da A5/A6/A7 (fuori perimetro, non toccati) per la parte `MSGS`. Pulizia completa rimandata a quando si affronta per intero la tab "percorso singolo agente" nelle pagine di A2/A3/A4.

### Step 7 — Trasporto dati storici da Drive

**Stato:** completato

**Obiettivo:** la webapp ricostruita parte già popolata con la storia reale (report/piani/brief passati), non vuota.

**Decisioni progettuali:**
- Da eseguire dopo che schema Supabase, pagine HTML e nuova struttura cartelle sono pronti — i contenuti storici vanno importati direttamente nel formato definitivo, non migrati due volte.
- Scope deciso con Gianluca: **tutto dall'inizio del progetto**, come se il workflow HTML/Supabase fosse sempre stato in uso — non solo un backfill parziale. Per ogni agente, tutti i mesi storici che precedono il primo mese già migrato con una run reale (Step 5): A2 fino a Settembre 2026 (Ottobre già reale), A3 fino a Ottobre 2026 (Novembre già reale), A4 fino a Ottobre 2026 (Novembre già reale).
- Metodo: per ogni mese, letto il documento originale da Drive (PDF, Google Doc o Google Slides secondo il mese), ricostruito il contenuto nell'HTML del template reale dell'agente (fedeltà di struttura/CSS garantita leggendo prima una riga reale già migrata da Supabase, non ricreando il template a memoria), poi scritto direttamente via `INSERT ... ON CONFLICT` su `report_mensili` — nessun file intermedio sul repo, i dati storici vivono solo su Supabase come i dati nuovi.
- Principio "cambia solo il contenitore": nessun dato numerico, nessuna frase, nessuna classificazione è stata corretta o aggiornata col senno di poi — ogni mese riflette fedelmente cosa l'agente aveva scritto in quel momento, inclusi i casi in cui un mese successivo ha corretto/superato quel dato (es. la serie "Capiamo la Sabbia" a Settembre 2026 resta classificata GDC STUFF/SPORT, la tassonomia DIVULGAZIONE introdotta dopo non è stata applicata retroattivamente).
- Dati OCR ambigui o mancanti (frequenti nei PDF più vecchi, soprattutto a due colonne): mai inventati. Dove il testo originale non permetteva una lettura certa (es. abbinamento data/ER di post multipli interlacciati in colonne diverse), ricostruita la combinazione più plausibile per cardinalità/ordine ma segnalata esplicitamente con una nota di trasparenza nell'HTML stesso, stesso pattern già usato dagli agenti veri quando manca un dato.

**Criterio di completamento:** la dashboard di A2 mostra grafici reali anche per i mesi passati già esistenti su Drive, non solo da oggi in avanti; i calendari di A3/A4 mostrano i mesi già pianificati in passato. — **Verificato**: `report_mensili` contiene ora 25 righe totali — A2 10 mesi (Gennaio-Ottobre 2026), A3 8 mesi (Aprile-Novembre 2026), A4 7 mesi (Maggio-Novembre 2026), confermato con query diretta sui conteggi e le lunghezze dell'HTML per ogni riga.

**Note (cronologia dello step):**
- [2026-11-12] Step aggiunto alla pipeline su richiesta esplicita di Gianluca, non ancora iniziato.
- [2026-11-15] Avviato su istruzione esplicita di Gianluca ("tutto dall'inizio del progetto... come se dall'inizio avessimo usato questo nuovo workflow"). Fatto inventario completo via ricerca Drive sulle tre cartelle agente: 22 documenti storici totali da convertire (A2: Gennaio-Settembre 2026, 9 mesi; A3: Aprile-Ottobre 2026, 7 mesi; A4: Maggio-Ottobre 2026, 6 mesi). Eseguita la conversione mese per mese, nell'ordine A2 → A3 → A4, usando per ciascun agente il template HTML reale già in produzione (fetchato una volta da una riga Supabase vera) come riferimento di struttura/CSS. Recuperata da un riavvio del processo di lavoro a metà Agosto 2026 (A2) senza perdita di dati, grazie alla natura idempotente degli upsert e alla checklist dei mesi tenuta come lista di task. Tutti i 22 mesi inseriti e verificati con una query finale di conteggio/lunghezza per agente — nessun documento mancante, nessun dato duplicato.

### Step 8 — Bottone trigger verso sessione Claude Code dedicata

**Stato:** in corso

**Obiettivo:** un bottone nella webapp apre la sessione Claude Code dedicata ad A1-A4 con il messaggio del mese già pronto da incollare.

**Decisioni progettuali:**
- Versione iniziale: bottone che apre il link della sessione Claude Code dedicata + copia il messaggio negli appunti (stesso meccanismo già in uso oggi per i Progetti Claude.ai, solo puntato a una sessione Claude Code invece che a un Progetto) — Gianluca incolla lui.
- Versione più automatica (notifica il giorno 1 del mese: "vuoi iniziare l'analisi di [mese]? Sì / Più tardi / No") valutata come miglioria futura, non nella prima versione — richiederebbe probabilmente passare dal semplice "copia e incolla" a un meccanismo che crea/avvia la sessione in automatico (es. una piccola funzione server-side), perché un tap su una notifica non può aprire da solo una chat interattiva.
- La sessione Claude Code dedicata ad A1-A4 è separata da questa (stesso repo, già confermato funzionare con lo stesso pattern in un altro progetto di Gianluca).
- Requisiti identificati per far lavorare la sessione dedicata: accesso al repo (automatico), le istruzioni degli agenti (i 4 prompt, già raccolti), i dati del mese da A1 (consigliato: `a1_monthly.py` scrive anche una copia dati nel repo, evitando di dover passare credenziali Google alla sessione dedicata), un connector Supabase (non chiavi in chiaro) se la sessione deve scrivere i report.
- **Scelta architetturale (confermata da Gianluca il 15/11):** sessione **persistente**, non una nuova ad ogni ciclo — stesso link fisso riusato ogni mese, continuità di contesto tra un mese e l'altro (accetta il compromesso di un contesto che cresce nel tempo, gestibile con autocompact).
- **Scope v1 (confermato da Gianluca il 15/11):** solo l'apertura mese (A2→A3→A4). La modalità itinerante di A4 (consulenza post per post durante il mese) resta esplicitamente fuori da questo step — non automatizzata, da valutare più avanti.
- Idee discusse ma non ancora decise per step futuri, oltre il perimetro attuale: integrare la modalità itinerante di A4 nella stessa sessione dedicata (se e quando deciso); una vision più a lungo termine di editing video e gestione/pubblicazione diretta dei post dalla stessa catena — entrambe segnalate da Gianluca come lavoro lungo e separato, da affrontare solo a fine pipeline.

**Criterio di completamento:** un click nella webapp porta a una sessione Claude Code pronta, con solo da incollare e inviare.

**Note (cronologia dello step):**
- [2026-11-15] Step avviato. Creata la sessione Claude Code dedicata e persistente (repo `giandcdalcorso11-coder/GDC-DASHBOARD`, branch `main`, stesso environment/connettori di questa sessione — Supabase, Google Drive, GitHub già disponibili senza configurazione aggiuntiva). Messaggio di setup iniziale le assegna il ruolo (eseguire A2→A3→A4 nell'ordine, leggendo i prompt in `docs/prompts/` e lo stato del progetto da `docs/documento-sessione-gdc-ia-team.md` prima di ogni ciclo, scrivendo una propria voce di storico dopo ogni ciclo eseguito, commit+push su `main`). Confermato pronta e in attesa (non esegue nulla finché Gianluca non chiede un mese specifico).
- [2026-11-15] Aggiunto il bottone nella webapp: nuova card "Ciclo editoriale mensile" in cima a `page_home_v25.html` (sopra la lista degli agenti, perché l'azione è trasversale A2→A3→A4, non di un singolo agente) con due pulsanti — "Apri sessione" (link fisso alla sessione dedicata) e "Copia messaggio" (riusa il popup generico `openMsg()` già esistente sulla pagina, nessun nuovo meccanismo). Messaggio precompilato (`MSG_CICLO`) generato con mese corrente/precedente dinamici, stesso pattern già in uso per gli altri messaggi della pagina.
- Non ancora verificato con un ciclo reale completo (Gianluca non ha ancora lanciato il primo ciclo dalla sessione dedicata) — prossimo passo per chiudere lo step.

### Step 9 — Pagina Impostazioni/notifiche

**Stato:** completato

**Obiettivo:** nuova pagina "Impostazioni" nella webapp con interruttori per attivare/disattivare le notifiche push, granulari per singola voce, più altre sezioni di utilità (dispositivi, stato automazioni, aspetto, account).

**Decisioni progettuali:**
- Idea originale di Gianluca, mai realizzata finora per la difficoltà di modificare la webapp dai Progetti Claude.ai — ora che si lavora da Claude Code con push/rimozione file diretta, è un buon momento per affrontarla.
- Trovata su Supabase una tabella `user_settings` (user_id + campo `settings` jsonb) già esistente ma con 0 righe e non collegata a nulla nel codice attuale — possibile scaffolding abbandonato di un tentativo precedente. Confermato con Gianluca: si riusa questa tabella (ha già la forma giusta: user_id + jsonb) invece di costruirne una nuova.
- Struttura scelta per le notifiche: un interruttore generale ("pausa" software, non disiscrizione reale del dispositivo) più un sottomenù con ogni notifica singola attivabile/disattivabile — inclusi A2/A3/A4 (prima assenti) e tutti i 13 step della pipeline commerciale singolarmente, ciascuno etichettato con chi lo esegue (A5.1/A5.2/A6.1/Pipeline Watcher/A6.2/A7).
- Per A2/A3/A4 (che girano nella sessione Claude Code, non via script GitHub Action) deciso di NON estendere la stessa catena trigger Postgres→pg_net→PAT→repository_dispatch già fragile (vedi Step 10) per le loro notifiche push: si userà invece un cron GitHub Actions che controlla periodicamente agent_states/activity_log, stesso pattern già solido di pipeline_watcher.py — non ancora implementato.

**Criterio di completamento:** gli script Python (a1_monthly.py, a7_followup.py, pipeline_notify.py, notify_failures.py) leggono le preferenze da `user_settings` prima di inviare una push, e il nuovo cron per A2/A3/A4 è stato scritto e collegato.

**Note (cronologia dello step):**
- [2026-11-12] Trovata `user_settings` durante l'audit Supabase generale. Non ancora deciso se riusarla.
- [2026-11-13] Deciso: si riusa `user_settings` — confermato da Gianluca insieme alle altre risposte di default di questa sessione.
- [2026-11-17] Mockup iterato (struttura tab, poi dettaglio notifiche con master+sottomenù granulare, poi correzione pillola "Home" per coerenza con lo stile reale) e poi implementato nella pagina reale `app/page_settings_v1.html` con le 5 tab (Notifiche, Dispositivi, Automazioni, Aspetto, Account), tutte con dati reali tranne il collegamento lato script. Aggiunto un pulsante a icona (ingranaggio) sulla home come punto di accesso. Rimane da fare: far leggere le preferenze agli script che inviano le push (oggi salvate ma ignorate) e costruire il nuovo cron per le notifiche A2/A3/A4.
- [2026-11-17, più tardi] **Step chiuso.** `a1_monthly.py`, `a7_followup.py`, `pipeline_notify.py` e `notify_failures.py` ora leggono `user_settings` (master + chiave specifica per ciascuna notifica) prima di ogni `webpush`, fail-open se la riga manca o la lettura fallisce. Costruito `scripts/a2a3a4_watcher.py` (cron orario, stesso principio di `pipeline_watcher.py`): confronta `agent_states.updated_at` con una nuova colonna di guardia `agent_states.last_notified_at` per A2/A3/A4 (che girano in sessione Claude Code, non via script — nessun evento su cui agganciarsi diversamente) e manda la push al primo completamento non ancora notificato. Verificato con due run reali su GitHub Actions: un run "pulito" (nessun output, corretto — i completamenti preesistenti erano stati marcati come già notificati in migrazione) e un run con un completamento simulato (disattivando temporaneamente `master` per non mandare una push fuorviante a Gianluca) che ha mostrato nei log esattamente il rilevamento + lo skip per preferenza disattivata attesi. Stato del database ripristinato dopo il test.

### Step 10 — Audit e miglioramento Team Commerciale (A5-A7)

**Stato:** in corso — fragilità trovate risolte o attribuite consapevolmente; migrazione schede aziendali completata (36/38); risolti i bug di coerenza emersi dalla migrazione (link rotto, messaggi/prompt ancora puntati su Drive); redesign grafico A1-A4→A5-A7 completato per tutte le pagine (home, A5, A6, A7); trovata e risolta trasversalmente (A1-A7 + home) una classe di bug sui colori di stato e sul tema chiaro/scuro, scoperta dal test manuale di Gianluca, incluso un residuo scoperto in sessione successiva sullo stato "riposo" in home; fatto un audit approfondito del funzionamento (non solo della grafica) di `page_pipeline_v1.html`/`page_company_v2.html`, direzione scelta e applicata (scala a 4 livelli verde/sabbia/sospesa/rosso, due date distinte per canale); header/navigazione di `page_pipeline_v1.html` allineato al resto dell'app e applicato al file reale; **redesign "pipeline a rami" di `page_company_v2.html` completato e applicato al file reale** (iterato su mockup fino alla v11, poi portato in produzione con migrazione dati Supabase) — sostituisce sia la vecchia timeline pipeline sia la sezione "Canali di contatto"; **header/navigazione di `page_company_v2.html` applicato al file reale** (indicatore "Connesso a Supabase", calendario popup, pill-row Home/Pipeline coerente col resto dell'app) e due vicoli ciechi di navigazione risolti (loop azienda↔scheda causato dall'unico uso rimasto di `history.back()` nell'app; link "Apri" di A6 verso i report A2 che apriva una nuova scheda perdendo il token di sessione); estesa la stessa pillola "torna indietro" coerente (senza freccetta nel testo) a 7 pagine secondarie (categorizza post, carica CSV, elenco/dettaglio report A2, dashboard KPI, scheda azienda, elenco/dettaglio piani editoriali, elenco/dettaglio brief mensili); risolto il bug preesistente dei pulsanti "Azioni rapide" (funzione `renderAzioni` orfana, puntava a elementi HTML non più esistenti dalla rimozione dei pulsanti di avanzamento manuale dentro le schede — rimossa insieme al codice morto associato)

**Obiettivo:** individuare e risolvere le fragilità nel workflow del team commerciale (A5 Pipeline, A6 Media Kit, A7 Mail Generator); valutare poi se applicare alle pagine A5-A7 lo stesso redesign già fatto per A1-A4.

**Decisioni progettuali:**
- **"Pipeline Notify fermo da 52 giorni" non era un bug.** Verificato testando il PAT direttamente dal database (RPC temporanea via `pg_net`, stessa chiamata del trigger reale, mai transitato fuori da Postgres): GitHub risponde 204, il PAT funziona. L'ultimo cambio di step in assoluto in tutta la pipeline commerciale è del 25/09 (LiberNovo) — coincide esattamente con l'ultima run di Pipeline Notify. Causa reale: da 52 giorni non c'è stata nessuna attività commerciale, non un guasto tecnico.
- **Fragilità A7 nota ma non corretta, su scelta esplicita di Gianluca:** `a7_gmail_drafter.py` (`find_pdf_for_attachment`), se il nome PDF nell'header `ATTACHMENT:` non combacia con nessun file in cartella, allega in silenzio il PDF più recente invece di segnalare un mismatch. Mai successo in pratica (struttura cartelle per azienda già protegge dal rischio più probabile) — lasciato com'è, rischio giudicato troppo teorico per giustificare la modifica.
- **Notifiche "azienda bloccata da troppo tempo" (stuck-step reminder) scartate**, su indicazione di Gianluca: userebbe poco l'app in questo periodo, sarebbero notifiche quasi ignorate. Il vero problema del basso rendimento della pipeline non è la cadenza dei promemoria ma il tasso di risposta alle mail — già affrontato separatamente nei prompt A5.2/A6.2 (contatto nominativo invece di casella generica, canali multipli LinkedIn/Instagram, sequenza di follow-up automatici).
- **Rischio credenziali generalizzato a tutta la catena**: stessa classe di rischio del PAT esiste anche per il service account Google e il refresh token Gmail — nessuno dei tre aveva un controllo proattivo prima di oggi.
- **`agent_states` non scritto da A5.1, A5.2, A6.1** — stesso identico bug già trovato e corretto per A2 (v18)/A3 (v13)/A4, semplicemente mai riportato qui perché questi tre prompt precedono il fix. Confermato sui dati reali: entrambi fermi su `stato: sleep` da giorni nonostante lavoro reale nel frattempo.
- **`agent_states` scartato esplicitamente per A6.2**: a differenza degli altri, A6.2 è una conversazione continuativa su una trattativa (si riaccumula nel tempo, spesso con più conversazioni attive insieme) — non ha un vero momento "done". Gianluca ha confermato: il pallino sarebbe comunque poco significativo per questo agente, non vale la complessità di un meccanismo a tempo. Lasciato senza segnalazione di stato.
- **Scheda aziendale di A5.2: da DOCX+Drive a pagina HTML su Supabase**, stesso principio già adottato per i report A2/A3/A4 — motivato sia dalla scomodità del download-e-trascina (specialmente da iPad/telefono, dove i file scaricati non si aprono in formato nativo) sia dalla possibilità di offrire un export PDF on-demand per il caso raro ma reale di un collaboratore che ha bisogno del documento. Conseguenza riconosciuta e gestita: A6.1 e A6.2 leggevano la scheda da Drive — aggiornati anch'essi per leggerla da Supabase, altrimenti si sarebbero rotti al primo utilizzo dopo il cambio di A5.2.
- **Media Kit di A6.1 lasciato invariato (PPTX + revisione manuale su Drive)**: a differenza della scheda, Gianluca corregge sempre a mano il PPTX in PowerPoint prima di esportarlo in PDF — un passaggio di editing reale, non solo una scomodità di formato. Convertirlo in HTML gli toglierebbe la possibilità di correggerlo come fa oggi.
- **Schede già prodotte su Drive da migrare al nuovo formato Supabase** — altrimenti A6.1/A6.2 non le troverebbero più riprendendo una trattativa già aperta. Stima iniziale sbagliata: la query su `drive_folder_scheda` ne indicava solo 16, ma un audit diretto della cartella Drive "Schede aziendali" ha trovato **38 sottocartelle aziendali reali** — le 22 mancanti risalgono a prima che A5.2 iniziasse a scrivere quella colonna, quindi invisibili da Supabase. **Migrate 36 su 38**; le uniche 2 senza scheda (LiberNovo, Commerciale Teatina Srl) hanno la cartella Drive vuota — nessun DOCX mai arrivato, segnalato a Gianluca come dato di fatto, non colmato con contenuto inventato.
- **Direzione scelta per le fragilità dell'audit su canali/follow-up**: niente automazione delle risposte via Gmail per ora (rischio di notifiche ignorate con un tasso di risposta reale già basso — scartato esplicitamente da Gianluca). Scelto invece: ogni canale (mail/LinkedIn/Instagram/futuri rami personalizzati) traccia due date distinte — "primo contatto" (fissa, mai sovrascritta) e "ultimo cambio di stato" (usata per il contatore giorni) — risolve alla radice il bug di `saveChannelNote()` già trovato.
- **Scala unica a 4 livelli**, applicata sia alla mail sia ai canali social: verde = tocca a loro, entro 21gg (soglia già in uso, non 14 come ricordava inizialmente Gianluca); sabbia = silenzio, oltre 21gg; bianco/nero ("Sospesa" — nome scelto da Gianluca al posto di "Morta", usato solo come termine di lavoro durante la progettazione) = oltre 60gg, fuori scala, canale considerato inattivo; rosso = tocca a me. Nella pipeline (vista lista) la bandierina di priorità a destra ora considera il canale più urgente tra tutti, non solo la mail. Migrazione Supabase `add_channel_primo_contatto_dates` (nuove colonne `linkedin_primo_contatto_date`/`instagram_primo_contatto_date`, con backfill dalle date già esistenti).
- **Redesign canali — cambio di direzione in corso.** La sezione "Canali di contatto" separata (appena applicata a `page_company_v2.html`) viene superata da una richiesta più ampia di Gianluca: reintegrare i canali nell'alberatura della pipeline 1-13 stessa, come se dallo step 6 il tronco si diramasse in più rami paralleli (mail + canali social + rami aggiunti a mano con testo libero) che si ricongiungono allo step 10. Decisioni emerse durante l'iterazione sul mockup (6 versioni, con feedback diretto incluso due schizzi a mano di Gianluca):
  - Storico eventi multi-voce, stesso modello su **tutti** i rami (non solo mail) — risponde al problema reale di scambi di mail con più eventi che oggi finiscono tutti schiacciati in un'unica nota/data sullo step "Gestita".
  - Colonne di pari peso per ogni ramo (non più un tronco dominante con corsie sottili laterali) — ogni ramo ha gli stessi 3 stadi (per la mail: Inviata/Risposta/Gestita; per gli altri: Contattato/Risposta/Gestito), ciascuno col proprio storico eventi.
  - Un pallino cliccato apre il dettaglio spingendo i pallini successivi verso destra (non un popup separato, non un overlay fluttuante — entrambe le alternative sono state provate e scartate su feedback diretto di Gianluca) e si fonde visivamente col pannello (bordo/titolo in comune, niente icona duplicata).
  - Le linee di collegamento (biforcazione dopo lo step 6, righe tra gli stadi, ricongiungimento allo step 10) si ridisegnano leggendo la posizione reale di ogni pallino nel DOM dopo ogni render, non calcolandola a formula fissa — necessario perché altrimenti si "spezzavano" visivamente quando un pannello spingeva i pallini successivi.
  - **Supera la decisione della prima metà di questa stessa sessione** (quando la matita doveva sbloccare "solo il tronco 1-13", lasciando i rami sempre modificabili): provando il mockup, Gianluca ha chiesto che a matita sbloccata il click su **qualunque** pallino (tronco o ramo) lo attivi/sposti direttamente; a matita bloccata il click apre invece lo storico eventi per sola consultazione/aggiunta note, su qualunque pallino.
  - Rimosso il collegamento visivo tra step 12 e 13: lo step 13 "Rifiutato" è un esito alternativo, non una prosecuzione sequenziale del 12.
  - Non ancora deciso (al momento della prima stesura di questa decisione): dove/come si inseriscono esattamente i rami personalizzati nello schema dati — **deciso poi in sessione successiva, vedi sotto**: colonna `lanes` jsonb dedicata.
- **Bivio spostato dallo step 6 allo step 4** (decisione successiva, in fase di rifinitura del mockup): gli step 5 "Testo mail" e 6 "Bozza" erano specifici del solo ramo mail (non ha senso parlare di "bozza Gmail" per un DM Instagram) — diventano i primi due stadi di **ogni** ramo (rinominati genericamente "Testo"/"Bozza"), portando ogni ramo da 3 a 5 stadi totali: Testo→Bozza→Inviata o Contattato→Risposta→Gestita o Gestito. Il tronco diventa quindi 1-4 + 10-13 (non più 1-6 + 10-13).
- **Rifiniture del mockup, in ordine, dal feedback diretto di Gianluca:** bordo pallino+scheda reso una forma continua senza "giunzione aperta" (prima il pallino mergiato perdeva il proprio bordo, lasciando un varco visibile); linee dei rami portate sotto ai pallini del tronco (6 e poi 4, e 10) tramite z-index invece che sopra; gating degli step 10-12 — restano bloccati finché nessun ramo raggiunge l'ultimo stadio ("9 · Gestita"), click con matita attiva mostra un avviso invece di avanzare — **tranne lo step 13 "Rifiutato", che resta sempre cliccabile** in qualsiasi momento, essendo un esito alternativo non sequenziale; numeri aggiunti a tutti i pallini di tutti i rami (prima solo Mail li mostrava); un solo pulsante "+" per aggiungere un ramo (crea comunque tutti e 5 gli stadi, non serve ripeterlo su ogni riga); contatori eventi estesi a **tutti** gli step (1-13, non solo i rami) e allineati in un'unica colonna a destra; tutti i pallini/step aprono una scheda con storico eventi quando la matita è spenta (non solo i rami); titoli allineati a sinistra invece che centrati, partendo tutti dalla stessa colonna.
  - **Bug: retrocedere nel tronco non azzerava i rami già avanzati.** Sintomo: tornando a uno step 1-6 con la matita, i rami restavano "avanti" anche se logicamente non avrebbero potuto esserlo prima del bivio. Fix nel mockup: tornare a uno step del tronco pre-bivio azzera lo stage di tutti i rami.
  - **Bug: step 13 "Rifiutato" attivava/segnava come fatti tutti i pallini precedenti.** Stessa causa del bug originale dell'audit (lo step 13 condivideva la stessa variabile "step attuale" di 1-12): fix applicato aggiungendo un flag indipendente (`rejected`), che non tocca più la posizione del tronco.
  - **Bug: attivare un ramo (es. Instagram) senza prima aver avanzato il tronco oltre il bivio lasciava i pallini 1-4 "indietro" visivamente.** Fix: attivare un ramo porta sempre il tronco almeno al bivio.
- **Decisione (fase di applicazione al file reale, su domanda esplicita a Gianluca): "ponte automatico" invece di migrazione completa.** Gli step 7/8 (ora parte del ramo Mail) sono scritti direttamente dall'automazione Gmail (A6/A7) tramite `step_5..step_9`/`step_N_date`/`step_notes[N]`; anche `page_pipeline_v1.html` legge queste stesse colonne per il follow-up. Due strade proposte: (a) migrazione completa anche del ramo Mail sulla nuova struttura dati, riscrivendo anche i prompt A6/A7 che scrivono su Supabase; (b) **ponte automatico (scelta da Gianluca)** — l'automazione continua a scrivere esattamente come oggi, la pagina azienda *legge* questi stessi campi e li traduce dal vivo nello stadio del ramo Mail, senza salvarli altrove. I nuovi campi jsonb si usano solo per le parti senza automazione (Instagram, LinkedIn, rami manuali, storico eventi extra del tronco). Conseguenza accettata e dichiarata a Gianluca: il ramo Mail, finché il prompt A6 non viene aggiornato, mostra un solo evento per stadio (quello scritto dall'agente), non uno storico multiplo come gli altri rami.
- **Schema dati scelto per l'applicazione reale** (tre nuove colonne su `companies`, additive, nessuna rimossa): `lanes` (jsonb, array di rami — Instagram/LinkedIn/manuali — ciascuno con `{id,label,short,color,stage,events[5]}`; il ramo Mail NON è qui, resta a ponte); `trunk_events` (jsonb, storico eventi extra per gli step 1-4/10-13, in aggiunta alla nota singola legacy già esistente, mai sovrascritta); `rejected` (bool, fix del bug step 13 anche sui dati reali).
- **Deviazione di sicurezza dal mockup, decisa autonomamente in fase di applicazione**: nel mockup, retrocedere nel tronco azzerava tutti i rami (vedi sopra). Su dati reali questo avrebbe potuto cancellare contatti Instagram/LinkedIn veri per un click sbagliato — **non portata in produzione**: sul file reale, retrocedere nel tronco lascia i rami intatti. Segnalata esplicitamente a Gianluca.
- **Migrazione dati reali eseguita** (56 aziende): le 10 aziende con `instagram_stato` valorizzato migrate nel nuovo formato `lanes` (con un evento "migrato dal vecchio sistema" come primo storico); l'unica azienda a `step_attuale=13` (GoPro) corretta — `rejected=true`, `step_attuale` riportato a 4 (i booleani `step_1..step_13` erano tutti `true` per via del bug stesso, quindi non utilizzabili per ricostruire la posizione reale pre-rifiuto: scelta una posizione conservativa, segnalata a Gianluca come imprecisione nota su questa singola riga storica).
- **Bug preesistente scoperto, non corrotto da questo lavoro e non ancora corretto**: la sezione "Azioni rapide" di `page_company_v2.html` chiama `document.getElementById('azioni-list')`/`'azioni-title'`, ma questi elementi non esistono nell'HTML attuale — la funzione fallisce silenziosamente (guard `if (!title || !list) return`), quindi i pulsanti di avanzamento rapido non vengono mai renderizzati. Segnalato a Gianluca, non toccato in questo giro (fuori scope, causa ignota se sia una regressione di una modifica precedente).

**Criterio di completamento:** le fragilità trovate sono risolte o scartate con una motivazione esplicita (fatto); le schede aziendali già su Drive sono migrate su Supabase senza perdita di contenuto (fatto, 36/38 — le 2 restanti non hanno mai avuto un DOCX reale), verificabile da A6.1/A6.2 su una trattativa reale già aperta (da fare); i bug di coerenza introdotti dalla migrazione sono risolti (fatto — vedi nota 2026-11-18); il redesign grafico già fatto per A1-A4 è valutato e applicato pagina per pagina ad A5-A7 (fatto, tutte e 4 le pagine applicate al file reale); l'audit del funzionamento reale di pipeline/azienda (non solo grafica) è fatto e discusso con Gianluca (fatto — direzione scelta e applicata, vedi Decisioni progettuali); header/navigazione allineati al resto dell'app su `page_pipeline_v1.html` e su `page_company_v2.html` (**fatto**, applicati ai file reali, inclusi i vicoli ciechi di navigazione risolti e la pillola "torna indietro" estesa a 7 pagine secondarie); redesign dei canali come rami dentro la pipeline 1-13 di `page_company_v2.html`, con storico eventi multi-voce e rami personalizzabili (**fatto** — mockup iterato fino alla v11, schema dati `lanes`/`trunk_events`/`rejected` creato, migrazione dati reali eseguita, applicato al file reale e verificato con Playwright su dati equivalenti ai reali instradati tramite Supabase).

**Note (cronologia dello step):**
- [2026-11-16] Audit eseguito su script e workflow GitHub Actions reali (a7_gmail_drafter.py, a7_followup.py, pipeline_watcher.py, pipeline_notify.py, notify_failures.py) più dati reali su Supabase. Trovato che "Pipeline Notify" non esegue da 52 giorni, 6 aziende bloccate allo step 3 da luglio/inizio settembre (bottleneck di processo, non bug). Lavoro sospeso qui per passare allo Step 9.
- [2026-11-17] Ripreso. Verificato (vedi sopra) che Pipeline Notify non è rotto. Costruito `scripts/credential_health_check.py` (cron giornaliero): testa PAT GitHub (via due RPC Postgres dedicate, `submit_github_pat_healthcheck` + `get_http_response_status` — una prima versione con un'unica RPC a polling sincrono via `pg_sleep` falliva contro lo `statement_timeout` di Supabase, risolto spostando il polling in Python), service account Google (`drive.about().get()`) e refresh token Gmail (`gmail.users().getProfile()`); scrive l'esito su `token_status` (stesso schema già usato per il token Instagram) e, se una fallisce, lascia che la rete di sicurezza `notify_failures.py` già esistente intercetti il workflow fallito — nessuna logica di push duplicata. Verificato con run reali su GitHub Actions dopo il fix.
- [2026-11-17] Ricevuti e letti i prompt di A5.1 (v6), A5.2 (v8) e A6.1 (v7) — mai inviati prima perché l'aggiornamento della webapp era partito solo sui primi 4 agenti. Applicato il fix `agent_states` a tutti e tre (v6→v7, v8→v9, v7→v8): `Step 0` scrive `working` prima di iniziare, una riga aggiuntiva scrive `done` alla chiusura — stesso pattern di A2/A3/A4. File consegnati a Gianluca e salvati in `docs/prompts/`.
- [2026-11-17] Ricevuti e letti i prompt di A6.1 (v7, già aggiornato sopra) e A6.2 (v10). Costruita l'infrastruttura per la scheda azienda in HTML: tabella `schede_aziendali` (company_id, html); caso "serve un PDF vero" gestito con tabella `scheda_pdf_requests` + trigger Postgres (`notify_scheda_pdf_requested`, stessa architettura del trigger pipeline già esistente) che avvisa GitHub via `repository_dispatch`; `scripts/export_scheda_pdf.py` (Playwright headless) renderizza la pagina, carica il PDF su un bucket Storage privato (`schede-pdf`) e scrive un link firmato (1h) sulla richiesta; nuova pagina webapp `app/page_scheda_azienda_v1.html` (visualizza la scheda, bottone "Esporta PDF" con polling); `page_company_v2.html` aggiornata (bottone "Scheda" al posto di "Cartella" per A5.2). Verificato con un test reale end-to-end (scheda finta, richiesta d'export, run GitHub Actions reale, PDF di 15KB caricato e scaricabile) — dati di test poi rimossi. Aggiornati di conseguenza i prompt: A5.2 v9→v10 (scrive la scheda su Supabase invece del DOCX, rimossa tutta la procedura cartella Drive), A6.1 v8→v9 e A6.2 v10→v11 (leggono la scheda da Supabase invece che da Drive). Tutto verificato con browser headless (nessun errore JS, bottone "Scheda" con link corretto) prima della consegna. File `.docx` inviati a Gianluca, versioni `.md` aggiornate in `docs/prompts/` (corretto anche un bug di conversione pre-esistente: alcune sottosezioni "Heading 2" sparivano silenziosamente invece di diventare intestazioni).
- [2026-11-17, più tardi] Gianluca ha fatto notare che le 16 schede già prodotte su Drive (prima del cambio di formato) vanno migrate su Supabase altrimenti A6.1/A6.2 non le troverebbero più riprendendo una trattativa aperta — confermato con query diretta (vedi Decisioni progettuali). Non ancora eseguita, prossimo passo di questo step.
- [2026-11-17/18] **Correzione importante**: Gianluca ha segnalato che la stima di 16 schede era sbagliata ("sono molte più di 16, controlla a fondo Drive"). Confermato: un audit diretto della cartella "Schede aziendali" su Drive (listando le sottocartelle, non interrogando `drive_folder_scheda`) ha trovato 38 sottocartelle aziendali reali. Migrate con 3 fork in sequenza (uno perso a metà da un riavvio del container, ripreso senza perdita di dati verificando prima cosa fosse già su Supabase) più 1 azienda completata a mano dopo essere stata per errore omessa da una lista. Risultato finale: 36/38 migrate, 2 (LiberNovo, Commerciale Teatina Srl) con cartella Drive confermata vuota — nessuna scheda mai prodotta per quelle due, segnalato a Gianluca. Step 10 chiuso su questo fronte; resta da fare la verifica con una trattativa reale (A6.1/A6.2 su un'azienda a step 7-9) prima di considerare l'intero step completato.
- [2026-11-18] **Bug di coerenza trovati dopo la migrazione.** Link "Scheda" rotto su `page_company_v2.html`: mancava il prefisso `app/` nell'href (la pagina vive in `app/page_scheda_azienda_v1.html`, non in root) — fix immediato. Più seria: una **seconda fonte di staleness Drive→Supabase**, indipendente da quella delle schede. A2 ha smesso di scrivere i report mensili su Drive (migrato a Supabase `report_mensili` allo Step 5), ma i prompt di A5.2 (v10) e A6.1 (v9) istruivano ancora a leggere "Report A2" da una cartella Drive morta da settembre 2026 (confermato controllando l'ultimo file modificato nella cartella). Corretti via fork dedicato: A5.2 v10→v11, A6.1 v9→v10 (sezione di lettura riscritta con la query SQL `SELECT mese, html FROM report_mensili WHERE agente='a2' ORDER BY anno DESC, mese_num DESC LIMIT 2`). Lo stesso fork ha segnalato di propria iniziativa un'eco dello stesso bug nei messaggi precompilati — trovati e corretti altri 4 punti (`page_home_v25.html`, `page_company_v2.html`, `page_agent_a5_v1.html`, `page_agent_a6_v1.html`) che citavano ancora il link Drive morto invece dell'istruzione Supabase.
- [2026-11-18] **Redesign grafico home: card A5/A6/A7 allineate allo stile già fatto per A1-A4.** Workflow mockup-first su Artifact (richiesto esplicitamente da Gianluca, con l'iPad come riferimento per verificare gli angoli concentrici schede/loghi). Rimossi descrizione/tag/etichetta "Caricamento..." morta; introdotto il pattern `agent-row`/`agent-mini-btn` (riga con 📋 Messaggio / 💬 Apri chat) per i sotto-agenti di A5/A6, già usato in `page_company_v2.html`; pillola "Pipeline Sponsorizzazioni" spostata dentro la banda Team Commerciale (sotto il titolo) su richiesta di Gianluca, con la stessa soluzione per "Ciclo editoriale" nella banda Team Social; corretto un bug di wrapping titolo su mobile (`.agent-title` ora va a riga quando serve invece di stringere/nascondere la pillola Supabase/Drive). Applicato alla pagina reale (`app/page_home_v25.html`).
- [2026-11-18] **Redesign completo della pagina di A5, in due passate.** Prima passata (diretta sul file reale): chrome di navigazione allineato ad A1-A4 (pillola Hub, sys-mini, pillola notifiche) — in corso ha anche corretto un bug collaterale (`sysMeta` referenziato da `loadA5()` ma rimosso dall'header, causava un falso stato "Offline"). Gianluca ha chiesto di tornare al workflow mockup-first per una revisione più profonda ("quello che hai fatto ora va quasi bene, ma riprendiamo il workflow con il mockup"). Seconda passata, su `mockup_a5_page_base.html` (6 iterazioni), con il feedback di Gianluca:
  - pillola Pipeline: forma a specchio (puntava a sinistra come "torna indietro", sbagliato per un'azione in avanti) spostata a destra, senza icona, testo ingrandito — nuove classi `.pill-hub-wrap-r`/`.pill-hub-r`;
  - pillola notifiche rimossa dalla pagina di A5 (gestione centralizzata da Impostazioni) — segnalato esplicitamente da Gianluca che va fatto anche su A1-A4/A6/A7, non ancora eseguito altrove;
  - hero card: A5.1 e A5.2 affiancate invece che una sotto l'altra, etichetta "Progetto in Claude.ai" al posto di "Claude.ai" generico, titolo uniformato alle altre pagine ("AGENTE 5 — Pipeline");
  - tab Azioni: colori neutralizzati (confusionari secondo Gianluca), raggruppata per sotto-agente come già fatto nella home, rimosso il pulsante "Apri Pipeline aziende" (duplicato della pillola in alto), icone "Apri progetto" uniformate (erano diverse tra A5.1 e A5.2);
  - tab Documenti rimossa (puntava solo a Drive, contenuti già raggiungibili altrove — proposta di Claude, confermata da Gianluca);
  - tab Lavoro e Pipeline unite, con una nuova card introduttiva "Come funziona" che spiega il workflow copia-messaggio→apri progetto→l'agente lavora→conferma risultato, e le card A5.1/A5.2 espanse con una riga "Risultato:" di chiusura.
  Mockup approvato, applicato interamente a `page_agent_a5_v1.html`: oltre ai punti sopra, corrette anche (stessa classe di bug delle note precedenti) le righe residue del tab Config che citavano ancora output/cartella su Drive per A5.1, e pulito il JS (`loadA5()` aggiornata ai nuovi id badge indipendenti per sotto-agente, rimossi `repMm1Lbl`/`repMm2Lbl` e l'intero blocco morto delle push notifications). Verificato con `node --check` sugli script estratti e un controllo automatico dei link relativi (0 rotti) prima di commit/push/merge su main.
- [2026-11-18] **Redesign completo della pagina di A6**, stesso workflow mockup-first di A5, approvato e applicato a `page_agent_a6_v1.html`: header/nav allineati (sys-mini, pillole Home+Pipeline), hero con A6.1/A6.2 affiancate e badge indipendenti, tab Azioni neutralizzata, tab Modalità assorbita nella tab Lavoro (le 4 modalità di A6.2 diventano step), JS pulito (notifiche push rimosse). **Differenza deliberata rispetto ad A5**: la tab Documenti è stata **mantenuta** (non rimossa) perché qui i file (media kit, mail) restano davvero su Drive — A7 li legge da lì per la bozza Gmail — quindi il riferimento non era superato come lo era per A5. Nella stessa tab, le due righe di esempio dei file sono state rese esplicitamente non cliccabili (solo un pulsante "Apri" verso la cartella, non un link per riga), e aggiunto un pulsante a pillola verso la pagina reale dei report A2 (`app/agenti/a2-analyst/report.html`) al posto di un riferimento Drive morto rimasto nella card "Input — Report A2".
- [2026-11-18] **Bug di colori di stato, trovati da Gianluca con test manuali reali su Supabase (cambiando `agent_states.stato`), su A1-A7 — tre round di correzione:**
  - **Round 1 — colori icona vs badge invertiti.** Sintomo: cambiando stato, badge e icona non sempre concordavano. Causa: i file avevano i colori esadecimali di "queued" (icona) e "sleep" (icona) scambiati rispetto a quanto la badge della stessa categoria usa — bug di origine nel template, identico in ogni pagina copiata. Fix: ripristinati ai valori giusti (poi corretti di nuovo al Round 3, vedi sotto — il primo tentativo era stato derivato per analogia invece che copiato dalla home).
  - **Round 2 — sfondo del riquadro logo sbagliato.** Sintomo: riquadro verde (A5/A6/A7) o blu (A1-A4) con icona grigia, visibile ad ogni caricamento dati fallito o pagina senza sessione. Causa: `.logo-box-hero` aveva uno sfondo di default hardcoded indipendente dallo stato reale. Fix: rimosso il colore fisso dalla regola base, aggiunta la classe di stato "sleep" di default nel markup (stesso meccanismo della home).
  - **Round 3 — tutto corretto copiando esattamente `app/page_home_v25.html`** (unica pagina già giusta, confermato da Gianluca): i due round precedenti erano andati nella direzione sbagliata perché dedotti per analogia. Confrontata riga per riga con la home: icona/badge `queued`=rosso, `sleep`=blu (erano ancora scambiati); riquadro in stato "riposo" è un contrasto invertito voluto (quasi nero in chiaro, quasi bianco in scuro — mai implementato prima su nessuna pagina, non solo sbagliato); **contorno della hero-card e colore del titolo erano completamente statici**, non legati allo stato (su A1-A4 un verde fisso, su A5-A7 un colore fisso) — aggiunta una mappa dedicata (`INK_CFG`) e gli id mancanti (`heroCard`, `agentTitle`) per renderli dinamici esattamente come badge/icona; **stato "errore" non gestito da nessun `mapState()`** (lo scrivono gli script Python in caso di eccezione, es. `a1_monthly.py`, `a7_gmail_drafter.py`) — cadeva di default su "inattivo" (blu) invece che rosso come in home — aggiunta una voce dedicata ovunque; **icone in stato "riposo" con parti bianche invisibili in tema scuro** (il riquadro diventa quasi bianco, le parti bianche dell'icona — non legate al tema — sparivano) — aggiunto un override per tema scuro per ogni icona. **A1 non aveva affatto la logica condivisa `mapState()`/`STATE_CFG`** (if/else inline con un ramo finale che fingeva "inattivo" per qualunque stato non riconosciuto, incluso "in coda" e "riposo" mai gestiti prima) — refactorato sullo stesso pattern delle altre pagine, con la segnalazione "MBS mancante" mantenuta come override di priorità. Verificato con `node --check` e controlli di coerenza id su tutti i 7 file prima di ogni commit.
- [2026-11-18] **Bug: il tema scelto in Impostazioni non si applicava al resto dell'app.**
  **Sintomo:** cambiando tema in Impostazioni > Aspetto, solo la pagina Impostazioni cambiava aspetto; tutte le altre pagine restavano legate al tema del sistema/browser.
  **Causa:** solo `page_settings_v1.html` leggeva la preferenza salvata (`localStorage.gdc_theme_cache` + attributo `data-theme` sull'elemento root); le altre 19 pagine con un tema scuro definito lo attivavano solo tramite `@media(prefers-color-scheme:dark)`, ignorando la scelta esplicita dell'utente.
  **Fix applicato:** esteso a tutte le 19 pagine lo stesso meccanismo di Impostazioni — script inline che imposta `data-theme` prima che il CSS venga valutato, ogni regola del tema scuro condizionata anche a `:not([data-theme="light"])` (una scelta esplicita "Chiaro" vince anche se il sistema è scuro), e una copia di ogni regola fuori dal media query sotto `:root[data-theme="dark"]` (una scelta esplicita "Scuro" si applica anche se il sistema è chiaro). Verificato con un browser automatizzato (Playwright) in entrambe le direzioni, su variabili CSS e su regole con colori hardcoded.
- [2026-11-18] **Mockup pagina A7 preparato, in revisione — non ancora applicato al file reale.** Redesign più leggero di A5/A6 perché A7 è strutturalmente diverso: un solo agente (non due sotto-agenti) basato su GitHub Actions (non un progetto Claude.ai), con un selettore-azienda proprio per lanciare la creazione bozze. Applicati solo gli stessi fix già consolidati (header/nav, bottoni neutri, colori di stato) senza forzare fusioni di tab non necessarie: le tab Stato/Lavoro/Setup/Attività/Config restano separate perché ciascuna ha contenuto distinto e non ridondante.
- [2026-11-18, sessione successiva] **Mockup A7 rifinito e approvato, applicato al file reale.** Su feedback di Gianluca: rimosso il riquadro "Operativo in produzione..." dalla cima (spiegazione integrata come riga introduttiva nella tab Lavoro), rimossa la scritta statica "On-demand — nessun cron" (quello spazio si popola già dinamicamente), tab Setup eliminata e confluita in Config, tab Stato eliminata (il riquadro "Stato componenti" era statico e sempre OK, non diceva nulla — la sua unica parte utile, lo stato reale da Supabase, confluita anch'essa in Config), tolto il pulsante "GitHub Actions — dispatch manuale" nella tab Azioni (ridondante col selettore azienda), icone delle due emoji busta sostituite con la sola busta (scartata la combinazione busta+matita su richiesta esplicita — "se non hai un'icona coerente va bene solo la busta"). Applicato a `page_agent_a7_v1.html` ripristinando il redirect al login (rimosso solo nel mockup per permetterne l'apertura diretta in Artifact) — verificato che il redirect funzioni ancora e che nessun link/id sia rotto.
- [2026-11-18, sessione successiva] **Bug: in home lo stato "riposo" aveva ancora il problema di contrasto segnalato da Gianluca, nonostante il fix della sessione precedente.** Sintomo: riquadro del logo bianco invece che nero in stato riposo con tema scuro. Causa: una regola CSS residua — probabilmente introdotta per sbaglio durante l'estensione del meccanismo tema a tutte le pagine — forzava con `!important` lo sfondo a bianco (`#FAFAF5`) per `.bg-rest`/`.logo-rest` in tema scuro, in conflitto con la regola base che lo vuole sempre nero indipendentemente dal tema. Stesso identico bug trovato su tutte le pagine A1-A7. Fix: rimossa la regola residua ovunque (sia la versione guardata in `@media` sia quella forzata via `data-theme`), insieme alle sovrascritture dei singoli elementi dei loghi introdotte nella sessione precedente per compensare lo sfondo bianco — non più necessarie visto che il riquadro resta sempre nero. Verificato con Playwright in entrambi i temi su tutte le pagine.
- [2026-11-18, sessione successiva] **Rifiniture minori su home e hub, su richiesta di Gianluca:** testo in fondo alla pagina hub "GDC WORKSPACE" → "GDC WEBAPP"; più spazio tra la riga Hub/notifiche/impostazioni e la banda "Team Social" (troppo vicine); pulsanti "Apri sessione"/"Copia messaggio" uniformati a stessa dimensione (prima diversi, 117px vs 135px) e colore neutro invece di azzurro; pulsante "Pipeline Sponsorizzazioni" senza freccia e testo neutro invece di sabbia; rimosse le pillole "Supabase Pipeline" (A5) e "Drive A6" (A6) dai titoli scheda; rimossa la legenda a pallini colorati in fondo pagina (e il CSS ora inutilizzato). **Bug trovato durante il fix dei pulsanti di stato:** spazio vuoto in eccesso tra la fine di alcune schede agente (A2/A3, ~24px) e la riga dei pulsanti di stato. Causa: `setLogoState()` sovrascriveva `card.className` con `'acard '+c.card`, perdendo la classe `acard-logo-round` già presente nel markup statico — quella classe è ciò che imposta `align-items:center` sulla riga della scheda; persa, il contenuto si stirava (stretch di default) invece di centrarsi, lasciando lo spazio vuoto in basso. Fix: preservata la classe nell'aggiornamento di stato. Risolve il sintomo alla radice su tutte le schede, non solo quelle segnalate. Aggiunto anche il colore di stato individuale (prima statico, sempre blu) ai sottotitoli "A5.1/A5.2"/"A6.1/A6.2" nella hero di quelle pagine, stesso bug-pattern già risolto per titolo/contorno.
- [2026-11-18, sessione successiva] **Avviato audit approfondito sul funzionamento (non solo la grafica) di `page_pipeline_v1.html` e `page_company_v2.html`**, su richiesta esplicita di Gianluca ("quasi tutto manuale, non va bene, fai un controllo profondo"). Letto il codice di entrambi i file e incrociato con i dati reali su Supabase (tabella `companies`, 56 righe). Findings:
  - Pipeline a 13 step: 1-6 (Trovata→Bozza Gmail) automatizzati dagli agenti A5/A6/A7; 7-13 (Mail inviata→Rifiutato, la trattativa vera e propria) **completamente manuali, zero automazione** — nessun collegamento con Gmail per rilevare risposte, l'avanzamento step 7→8 richiede che Gianluca stesso noti la risposta e clicchi.
  - Il conteggio giorni (urgente/in attesa/silenzio a 21gg, contatore follow-up) è implementato bene — il problema è l'input manuale a monte, non la logica.
  - Dati reali: 18 aziende ferme allo step 7 da 61 a 187 giorni senza alcun avanzamento; **LinkedIn: 0 aziende su 56 hanno mai una data di contatto registrata** nonostante campo e bottone esistano da tempo; Instagram usato solo su 10/56, anch'esso fermo da 90+ giorni.
  - **Bug trovato (non ancora corretto):** `saveChannelNote()` in `page_company_v2.html` sovrascrive sempre `linkedin_contattato_date`/`instagram_contattato_date` a "adesso" ad ogni salvataggio, anche se si sta solo aggiornando una nota o lo stato senza un nuovo contatto reale — perde la distinzione fra "primo contatto" e "ultima modifica". Non ha ancora fatto danni solo perché LinkedIn non è mai stato usato.
  - **Incoerenza di modello dati:** per la mail esistono due campi distinti (`step_7_date`=inviata, `step_8_date`=risposta); per LinkedIn/Instagram un solo campo data per canale, che schiaccia "quando ho contattato" e "quando mi hanno risposto" nello stesso timestamp.
  - **Rischio di manutenzione:** la logica di calcolo giorni/follow-up (`calcFollowup`/`renderFollowUp`) è duplicata quasi identica tra i due file, sincronizzata solo da un commento nel codice ("Allineato 1:1"), non da una funzione condivisa.
  Findings presentati a Gianluca in chat; **nessuna decisione presa in questa sessione** su quale direzione intraprendere (automatizzare il rilevamento risposte mail via Gmail, correggere il bug delle date social, ripensare il tracking LinkedIn/Instagram) — discussione in corso, da riprendere.
- [2026-11-19] **Decisa la direzione per le fragilità dell'audit e applicata a `page_pipeline_v1.html`/`page_company_v2.html`.** Scartata l'automazione delle risposte Gmail (rischio notifiche ignorate col tasso di risposta reale già basso). Scelto invece: due date distinte per canale (primo contatto fisso, ultimo cambio stato per il contatore), scala a 4 livelli verde/sabbia/sospesa (bianco/nero, oltre 60gg)/rosso, unica sia per la mail che per i canali social. Migrazione Supabase (`add_channel_primo_contatto_dates`) con backfill. Applicato a `page_pipeline_v1.html`: card con pill separate per Mail/LinkedIn/Instagram, bandierina di priorità multi-canale. Applicato a `page_company_v2.html`: nuova sezione "Canali di contatto" separata dallo step 7 (poi superata, vedi sotto), fix del bug `saveChannelNote()` verificato con un test end-to-end (nota-sola non tocca più la data, cambio di stato sì). Verificato con Playwright (rendering chiaro/scuro, interazioni) prima di ogni commit.
- [2026-11-19] **Header e navigazione di `page_pipeline_v1.html` allineati al resto dell'app**, su richiesta di Gianluca ("va aggiornata tutta la pagina pipeline... coerente col resto"). Mockup-first (2 iterazioni): logo a sinistra, stato di connessione al centro, data a destra con calendario funzionante; pillole di navigazione coi lati a freccia (clip-path, stesso pattern di home/A1-A7), solo "Home" (il pulsante Hub tolto, resta solo nella home). Applicato al file reale.
- [2026-11-19] **Mockup dello stesso header preparato anche per `page_company_v2.html`** (pillola singola "← Pipeline" con icona a freccia indietro, punteggio spostato dentro la card azienda) — non ancora applicato al file reale: il focus si è spostato sul redesign più ampio dei canali prima di confermarlo.
- [2026-11-19] **Redesign "pipeline a rami" per `page_company_v2.html` — richiesto da Gianluca, in corso, non ancora applicato.** Vedi Decisioni progettuali per il contenuto deciso. Percorso di iterazione (6 versioni di mockup): v1 card impilate sotto la pipeline (scartata, grafica non gradita); v2 corsie sottili accanto agli step 7-9 con storico espandibile inline (si avvicinava, ma linee con gap visibili per un bug di posizionamento automatico della griglia CSS); v3 corretto con SVG dedicati per i connettori di biforcazione/ricongiungimento, interattivo (matita, storico eventi, aggiunta rami dal vivo) — Gianluca ha confermato il concetto ma chiesto una grafica diversa, fornendo due schizzi a mano; v4 ricostruita con colonne di pari peso ed espansione "a spinta" (il pallino cliccato spinge i successivi), corrispondente al primo schizzo; v5 tentativo di risolvere "le linee si spezzano quando spinge" passando a un pannello overlay ancorato al pallino — **approccio poi corretto da Gianluca**: preferiva la spinta, voleva solo che le linee seguissero il movimento, non un cambio di meccanismo; v6 (attuale) torna alla spinta ma ridisegna le linee leggendo le posizioni reali nel DOM a ogni render, pannello fuso col pallino (bordo/titolo comune, non più icona duplicata a fianco), matita che attiva direttamente qualunque pallino invece di aprire solo le info, rimosso il collegamento 12→13. Mockup v6 in revisione presso Gianluca al termine della sessione.
- [2026-11-19, sessione successiva] **Mockup rifinito dalla v6 alla v9**, su tre round di feedback diretto di Gianluca sul v6 pubblicato. Round 1 (v7): bordo pallino+scheda reso continuo (fix della "giunzione aperta" segnalata con un fermo immagine annotato in rosso), linee portate sotto ai pallini 6/10, gating 10-12 su "almeno un canale a 9·Gestita" con avviso a comparsa, step 13 escluso dal gate. Round 2 (v8), dopo un fermo immagine con annotazioni a mano sul bordo del popup: pallino tornato un cerchio pieno/vuoto invece di un blocco squadrato; bug — retrocedere nel tronco non resettava i rami — risolto; numeri su tutti i pallini di tutti i rami; un solo "+"; più spazio tra le righe; contatori eventi corretti (prima leggevano sempre e solo gli eventi di Mail) e allineati in colonna; storico eventi esteso a tutti gli step 1-13; bug — step 13 segnava come fatti i pallini precedenti — risolto con un flag `rejected` indipendente. Round 3 (v9→v10): etichette MAIL/IG/LD rese leggibili con piccoli tag colorati; contatori estesi anche al tronco 1-6/10-13; titoli di tutti gli step allineati in un'unica colonna; tronco centrato dinamicamente rispetto al numero di rami presenti (verificato con 4 e 5 colonne, si ricentra da solo aggiungendo rami); bug colore pallino 6 verificato e confermato **non riprodursi** (il pallino resta "sabbia" finché il tronco non avanza davvero oltre il bivio — serve completare la condizione di sblocco, non un difetto del codice).
- [2026-11-19, sessione successiva] **Ultima richiesta sul mockup (v10→v11): bivio spostato dallo step 6 allo step 4** (vedi Decisioni progettuali) e titoli portati da centrati ad allineati a sinistra con i tag dei contatori spostati più a destra. Mockup v11 approvato.
- [2026-11-19, sessione successiva] **Applicazione al file reale.** Investigato a fondo `page_company_v2.html` (pipeline timeline 1-13 esistente, sezione "Canali di contatto" esistente, sistema di note per-step `step_notes`/`openNoteEditor`, meccanismo follow-up, azioni rapide) e lo schema reale `companies` su Supabase (56 righe) prima di toccare qualunque cosa. Scoperto che gli step 5-9 sono scritti in produzione dall'automazione Gmail A6/A7 e che anche la pagina lista pipeline dipende dagli stessi campi — da qui la domanda esplicita a Gianluca sul "ponte automatico" (vedi Decisioni progettuali). Eseguita la migrazione Supabase (`add_lanes_trunk_events_rejected` + backfill dati, vedi Decisioni progettuali), poi riscritta `page_company_v2.html`: unite le vecchie sezioni "② Pipeline" e "④ Canali di contatto" nell'unico componente a rami (CSS/HTML/JS portati dal mockup v11, adattati al bridge dati reale), rimossi i vecchi popup/funzioni ormai sostituiti (`openNoteEditor`, `saveStepNote`, `renderChannels`, `openChannelEditor`, `saveChannelNote` e relativi popup HTML), aggiornati `setStep`/`execAction` per il nuovo modello (gating step 10, `rejected` indipendente per step 13, scrittura invariata su `step_5..step_9` per il ponte mail). Scoperto e segnalato, non corretto, un bug preesistente indipendente (vedi Decisioni progettuali, "Azioni rapide"). Verificato tutto con Playwright sul file reale (non il mockup), instradando le chiamate Supabase verso dati equivalenti ai reali: rendering chiaro/scuro, ponte mail, gating, rifiuto indipendente, creazione di un ramo manuale custom persistita via `lanes` — tutto confermato funzionante prima di commit/push/merge su main.
- [2026-11-19, sessione successiva] **Header di `page_company_v2.html` applicato al file reale, su richiesta esplicita di Gianluca** ("manca l'aggiornamento della parte sopra della pagina... procedi con le solite modifiche coerenti con il resto della webapp"): aggiunto l'indicatore "Connesso a Supabase" e il calendario popup interattivo (stesso componente condiviso da Home/A1-A7/Pipeline), sostituito il vecchio bottone "← Pipeline" (`history.back()`) + bottone "Hub" separato con la pill-row standard a due pillole con freccia (Home/Pipeline).
- [2026-11-19, sessione successiva] **Audit di navigazione su richiesta di Gianluca** ("vedi se ci sono vicoli ciechi... pagine che hanno ancora il layout vecchio"), controllando ogni link interno dell'app (script Python su tutti gli `href`, nessun altro target mancante trovato) più i due casi segnalati esplicitamente. **Bug: loop azienda↔scheda.** Sintomo: da `page_company_v2.html`, aprire la "scheda azienda" (`app/page_scheda_azienda_v1.html`) e poi cliccare "torna alla pipeline" riapriva la scheda invece di andare alla pipeline, in un loop senza uscita. Causa: `page_company_v2.html` era l'unico punto di tutta l'app a usare `history.back()` per tornare indietro, mentre la scheda azienda torna con un link diretto (non `history.back()`) — il mix rompeva la catena dello storico del browser. Fix: sostituito `history.back()` con un link diretto e deterministico (`page_pipeline_v1.html`, dentro la nuova pill-row), eliminando strutturalmente la dipendenza dallo storico browser. **Bug: link "Apri" di A6 verso i report A2.** Sintomo: il bottone "Apri" (tab Documenti, zona input A2) portava al login invece che al report. Causa: il link apriva `report.html` in una nuova scheda (`target="_blank")`, che non eredita il `sessionStorage` col token di sessione. Fix: rimosso `target="_blank"`, naviga nella stessa scheda. Entrambi verificati con Playwright simulando la sequenza esatta riportata da Gianluca.
- [2026-11-19, sessione successiva] **Pillola "torna indietro" estesa a 7 pagine secondarie** (categorizza post, carica CSV, elenco/dettaglio report A2, dashboard KPI, scheda azienda, elenco/dettaglio piani editoriali, elenco/dettaglio brief mensili), su richiesta esplicita di Gianluca: tutte usavano ancora il vecchio bottone con la freccetta "←" scritta nel testo — sostituito con la stessa pillola a freccia (clip-path) già in uso altrove, rimuovendo la freccetta testuale dato che ora è la forma a indicare la direzione.
- [2026-11-19, sessione successiva] **Bug "Azioni rapide" risolto.** Sintomo: i vecchi pulsanti di avanzamento step dentro le schede non facevano nulla. Causa: la funzione `renderAzioni()` scriveva su `#azioni-title`/`#azioni-list`, due id rimossi dall'HTML quando Gianluca aveva chiesto (in una sessione precedente) di rimuovere quei pulsanti — l'avanzamento si fa solo cliccando i pallini della pipeline a rami. La funzione era quindi un no-op orfano, chiamata da due punti morti. Fix: rimossi la funzione, i suoi due call-site, gli helper `azBtn`/`azRefuse` (usati solo da lei) e la CSS associata (`.az-btn` e varianti), tutti verificati come non referenziati altrove prima della rimozione.

### Step 11 — Ruoli e permessi per collaboratori (osservatore/operatore)

**Stato:** in corso — modello di permessi completamente deciso e documentato; Step 10 chiuso (unico residuo: verifica su una trattativa reale, non bloccante, segnalata lì); **fondamenta dati create**: tabella `profiles` con RLS, funzioni helper `is_admin()`/`current_user_role(area)`, trigger di provisioning automatico su nuovi account, seed dell'account esistente di Gianluca come `is_admin=true`; **pagina di amministrazione fatta** (Impostazioni → Account, gestione ruoli per collaboratore); **enforcement IA TEAM completato su tutte le 17 pagine** (home, pipeline, azienda, scheda azienda, A1-A7 e relative sotto-pagine). Non ancora fatto: enforcement dei ruoli su GDC Studio (deliberatamente rimandato, vedi Decisioni progettuali — Gianluca ha scelto di fare prima IA TEAM).

**Obiettivo:** permettere a Gianluca di far entrare un collaboratore nella webapp con un account separato dal proprio, con accesso limitato per area (GDC IA TEAM / GDC Studio) e per ruolo (osservatore = solo vedere, operatore = può anche agire), gestibile da una pagina di amministrazione che solo lui vede.

**Decisioni progettuali:**
- **Due ruoli soli, non di più**: osservatore e operatore. Nessuna granularità più fine richiesta da Gianluca (es. per singolo agente) — solo per area.
- **Ruolo indipendente per area**: una persona può essere operatore su un'area e osservatore sull'altra (es. operatore su Studio, osservatore su IA TEAM). Non un ruolo unico valido ovunque.
- **Modello dati proposto**: tabella `profiles` (una riga per account Supabase Auth) con `is_admin` (solo Gianluca — accesso operatore automatico ovunque + unico che vede la pagina di amministrazione), `ia_team_ruolo` e `studio_ruolo` (nessuno/osservatore/operatore ciascuno).
- **Pagina di amministrazione**: dentro Impostazioni → Account, visibile solo a `is_admin`. Gestione permessi su account esistenti **e creazione di nuovi account direttamente da qui** (superata la decisione iniziale "si creano altrove" — vedi nota del 2026-11-20: risolto con una Edge Function, niente service_role key lato client). Resta assente solo l'invito via email (si comunica la password direttamente).
- **GDC IA TEAM — osservatore**: vede tutto (stato agenti, report, pipeline, schede azienda, calendario). Ogni pulsante che scrive su Supabase o lancia un agente resta **visibile ma disattivato** (stesso pattern già in uso in alcuni punti della webapp, es. classe `.lg-disabled`) — scelta esplicita di Gianluca, niente nascosto, solo non cliccabile.
- **GDC IA TEAM — operatore**: tutto attivo tranne la pagina di amministrazione. **Limite noto, non bloccante**: i pulsanti "Messaggio"/"Apri chat"/"Apri sessione" portano ai progetti Claude.ai di Gianluca — un collaboratore operatore non potrebbe usarli davvero senza accesso al suo account Claude. Risolto con una soluzione semplice: aggiungere un link per scaricare l'md/docx del prompt di ogni agente (già esistenti in `docs/prompts/`) nella **tab Azioni della pagina di ciascun agente** (non in home — Gianluca ha chiesto esplicitamente di non toccare la grafica della home, sistemata a più riprese in questa stessa sessione), così il collaboratore può creare lo stesso progetto sul proprio profilo Claude.
- **Pulsanti di stato-test** (forzatura manuale di `agent_states.stato`, usati finora solo per i test manuali di Gianluca): visibili e usabili **solo da `is_admin`**, mai da operatore o osservatore — sono uno strumento di debug, non un'azione operativa reale.
- **GDC Studio — i dati restano di Gianluca**, non si duplicano per account. Un collaboratore con un ruolo Studio assegnato opera sui dati di Gianluca (le query puntano al suo `user_id` invece che al proprio) invece che sul proprio spazio separato. La strada attuale ("ogni account ha il proprio Studio indipendente", già così oggi via `_userId = sessionStorage.gdc_uid`) resta disponibile e non va rimossa — Gianluca vuole tenerla per un possibile uso futuro (collegato al discorso Step 2/template, vedi sotto), ma la priorità ora è la prima.
- **GDC Studio — osservatore**: accesso e visualizzazione completa (ordini, filamenti, spese, hardware, progetti), nessuna modifica, **unica eccezione il Calcolatore Prezzi**: può calcolare un prezzo e salvarlo come progetto bozza (`saveProjCalc`, resta dentro il calcolatore); **non può "Invia a ordini"** (`sendToOrders`, crea un ordine vero con cliente — considerato a tutti gli effetti una modifica dati commerciali reali, stessa categoria delle altre azioni vietate). Confermato esplicitamente da Gianluca.
- **"Ampliamento template" (far usare la webapp, col proprio profilo, a persone esterne al tutto) discusso ma rimandato esplicitamente** — non scartato, solo non prioritario ora. Gianluca: "mi sembra molto complicato... il lato personalizzazione apre molti punti di rottura potenziali". Causa identificata insieme: la complessità del suo stesso sistema non è stata scrivere l'HTML ma decidere cosa ogni agente fa e come si incastra nel suo processo reale — conoscenza specifica del suo business, non riducibile a un wizard di configurazione. Due strade tecniche individuate per il futuro, da scegliere quando si riprenderà il discorso: (a) ognuno clona il repo e configura la propria copia (fattibile con l'architettura attuale, richiede solo un wizard/checklist che compili dati oggi scritti a mano nell'HTML), oppure (b) un'unica installazione condivisa multi-tenant (richiederebbe una riscrittura sostanziale: i segreti non potrebbero più stare nell'HTML statico, servirebbe un vero backend).

- **Implementazione dati (prima parte, fatta)**: tabella `profiles` (`user_id` pk → `auth.users`, `email`, `is_admin`, `ia_team_ruolo`, `studio_ruolo`), RLS con pattern "authenticated read: true" (stesso di `companies`/`agent_states` — chiunque loggato legge tutti i profili, serve sia alla pagina admin che a ogni pagina per risolvere il proprio ruolo) + update permesso solo a `is_admin` (nessun self-service sui propri permessi). Due funzioni helper `SECURITY DEFINER` (`is_admin()`, `current_user_role(area)`) per evitare la ricorsione RLS e dare alle pagine un modo semplice di interrogare il proprio ruolo via RPC. Trigger `on_auth_user_created_profile` crea automaticamente la riga (ruoli `nessuno`/`nessuno`) quando Gianluca crea un nuovo account Supabase Auth altrove — coerente con "niente flusso di invito via email". Seed: l'unico account esistente (`gdciateam@gmail.com`) impostato `is_admin=true`.
- **Ordine di lavoro scelto da Gianluca per l'enforcement**: IA TEAM prima di Studio. Chiarito un fraintendimento in questa discussione: IA TEAM non è "il lavoro piccolo" solo perché sono più pagine — ciascuna è più semplice e i dati sono meno sensibili; Studio è un singolo file molto più grande (`gdc_studio.html`) che tocca dati commerciali reali (ordini/clienti), quindi più delicato, non più piccolo.
- **UX del blocco per l'osservatore, decisa da Gianluca durante l'inventario**: non un `disabled` nativo che non fa nulla al click. I pulsanti restano visivamente smorzati ma cliccabili; al click, se il ruolo non lo permette, un popup spiega cosa farebbe quell'azione invece di eseguirla.
- **Scelta implementativa conseguente (non chiesta esplicitamente, dedotta dal requisito sopra)**: il controllo vive dentro le funzioni che scrivono davvero su Supabase o lanciano un agente (`gateIa(messaggio)` come prima riga di ciascuna), non nei singoli elementi HTML. È più robusto di provare a disabilitare ogni bottone — molti sono generati dinamicamente (template string in JS) e sarebbe facile lasciarne scoperto qualcuno; con il controllo nella funzione, anche un punto di ingresso dimenticato nell'HTML resterebbe comunque bloccato. Lo smorzamento visivo (classe `.role-disabled`, applicata via attributo `data-gate="ia"`/`"admin"`) è un livello separato, "best effort": serve a far capire in anticipo cosa è permesso, ma la sicurezza reale sta nella funzione.
- **`toggleEdit()` come unico punto di controllo per la pipeline a rami** (invece di gated ogni singolo pallino): `onPipTrunkClick`/`onPipDotClick` leggono internamente `pipEditOn`, quindi se l'osservatore non può mai attivare la modalità modifica, quei click restano sempre di sola lettura senza bisogno di guardie separate al loro interno. `pipAddHistoryEvent`/`onPipPlusClick`/`pipConfirmAddLane` restano gated a parte perché raggiungibili anche a modifica disattivata.
- **Fail-open su errore di rete nel caricamento del ruolo** (resta `operatore` se la fetch a `profiles` fallisce): scelto per non bloccare l'unico utente reale di oggi (Gianluca, sempre admin) in caso di problemi temporanei con Supabase — un collaboratore vero esiste solo da quando esiste un secondo account, oggi non ancora il caso.
- **Ruolo `nessuno` trattato come `osservatore`** ai fini del blocco azioni (nessuna via di mezzo più permissiva): un account senza un ruolo IA TEAM assegnato non può comunque scrivere/lanciare nulla, coerente con un default sicuro.

- **Creazione account da webapp, invece che solo dalla dashboard Supabase** (2026-11-20): Gianluca ha chiesto se fosse possibile, inizialmente scartato per lo stesso motivo del "niente invito via email" sopra (la creazione richiede la service_role key, mai lato client). Risolto con una **Supabase Edge Function** (`admin-create-user`, pattern già in uso nel progetto per `upsert_company` e altre): verifica `is_admin` lato server con la service_role key prima di creare l'account, che resta sempre fuori dal codice della webapp. Supera la decisione precedente ("gli account li crea Gianluca altrove") — l'alternativa scartata resta solo l'invito via email vero e proprio (richiederebbe configurare l'invio email sul progetto Supabase, non fatto).

**Criterio di completamento:** tabella `profiles` creata con RLS (**fatto**); pagina di amministrazione funzionante (Impostazioni → Account) (**fatto**, inclusa la creazione di nuovi account); ogni pagina IA TEAM rispetta il ruolo dell'utente loggato (osservatore = sola visualizzazione salvo le eccezioni sopra, operatore = pieno accesso eccetto amministrazione) (**fatto**, tutte le 17 pagine); lo stesso per Studio (da fare); verificato con almeno un account di test per ciascun ruolo (verificato con Playwright per IA TEAM su tutte le pagine; un vero secondo account reale non esiste ancora).

**Note (cronologia dello step):**
- [2026-11-19] Creata la tabella `profiles` con RLS, le funzioni helper e il trigger di provisioning (vedi Decisioni progettuali), seed dell'account di Gianluca come admin. Nessuna pagina ancora modificata — è solo la fondamenta dati, additiva e non distruttiva, verificata con una query diretta (riga seedata correttamente) e con `get_advisors(security)` (nessun problema nuovo oltre ai warning già tollerati dal progetto sulle funzioni `SECURITY DEFINER` richiamabili via RPC, stesso pattern di `notify_company_step_change`/`notify_scheda_pdf_requested` già esistenti). Chiesto a Gianluca l'ordine dei prossimi passi invece di deciderlo autonomamente: scelta pagina di amministrazione prima.
- [2026-11-19, stessa sessione] Pagina di amministrazione implementata in `app/page_settings_v1.html` (tab Account): sottotitolo account reso dinamico col ruolo reale, sezione "Amministrazione" visibile solo a `is_admin` con elenco collaboratori e due select (IA TEAM/Studio) per `ia_team_ruolo`/`studio_ruolo`, salvataggio via PATCH a ogni cambio. Verificato con Playwright (light/dark, caso admin e caso collaboratore, instradando `/auth/v1/user` e `/rest/v1/profiles`) prima di commit/push/merge. Prossimo passo da concordare con Gianluca: enforcement dei ruoli pagina per pagina (ordine da decidere — IA TEAM è molte pagine più piccole, Studio è un unico file grande `gdc_studio.html` che tocca dati commerciali reali).
- [2026-11-20] **Scelto IA TEAM prima di Studio** (dopo un chiarimento su cosa fosse "il lavoro piccolo", vedi Decisioni progettuali), poi fatto un inventario pagina per pagina di tutte le azioni che scrivono su Supabase o lanciano un agente (17 pagine IA TEAM + le 4 tab non-Account di Impostazioni, verificate senza azioni da limitare oltre quella già fatta). Durante l'inventario, due nuovi requisiti da Gianluca: conferma del modello a 3 stati (amministratore/operatore/osservatore) e la richiesta che i pulsanti bloccati mostrino un popup esplicativo al click invece di essere semplicemente disattivati — da cui la scelta implementativa di mettere il controllo dentro le funzioni (`gateIa`) invece che sui singoli elementi HTML (vedi Decisioni progettuali). Implementato e verificato con Playwright su tutte le 17 pagine (home, pipeline, azienda, scheda azienda, A1 categorizza/carica CSV, A5, A6, A7) — per ciascuna: pulsante visivamente smorzato ma cliccabile per l'osservatore, popup mostrato con il testo corretto, nessuna scrittura/navigazione eseguita; operatore e admin comportamento normale; i pulsanti stato-pill (home) bloccati anche per l'operatore, sbloccati solo per `is_admin`. Scoperto e rimosso durante l'inventario un'altra catena di codice morto in `page_company_v2.html` (`openPopupThen`/`closePopup`/`execAction`, stesso tipo di orfano delle "Azioni rapide" già risolte, dimenticato nella stessa pulizia).
- [2026-11-20, stessa sessione] **Creazione account aggiunta alla pagina di amministrazione**, su richiesta di Gianluca dopo aver chiesto "da dove aggiungo un nuovo account" (fino a qui si poteva solo dalla dashboard Supabase). Creata la Edge Function `admin-create-user` (verifica `is_admin` lato server, poi crea l'account Supabase Auth) e il modulo corrispondente in Impostazioni → Account (email, password con generatore, pulsante "Crea account"). Verificato con Playwright: creazione riuscita con aggiornamento immediato dell'elenco collaboratori, e caso di errore (email duplicata) gestito correttamente.

**Note (cronologia dello step):**
- [2026-11-19] Discussione completa sul modello di permessi, su iniziativa di Gianluca ("parliamone prima di lavorare sull'altro fronte"). Nessuna riga di codice scritta — solo design, vedi Decisioni progettuali sopra. Scoperta rilevante durante la discussione: il login della webapp è già vera autenticazione Supabase (`/auth/v1/token`), non una password condivisa — la base per account multipli esiste già, manca solo il livello di ruoli/permessi.

## Storico sessioni

### [2026-11-20 22:34] Step 11: enforcement ruoli completato su tutte le 17 pagine GDC IA TEAM, più gestione completa account (crea/reset password/disabilita/elimina) da webapp

**Riepilogo:** dopo aver scelto di affrontare prima IA TEAM e poi GDC Studio, fatto un inventario pagina per pagina di ogni azione che scrive su Supabase o lancia un agente, confermato con Gianluca il modello a 3 stati (amministratore/operatore/osservatore) e il requisito che i pulsanti bloccati mostrino un popup esplicativo al click, poi implementato e verificato l'enforcement su tutte le 17 pagine IA TEAM. A seguire, la pagina di amministrazione è stata completata con la gestione a tutto tondo degli account collaboratore (prima possibile solo dalla dashboard Supabase): creazione, reset password, disabilitazione/riattivazione ed eliminazione definitiva.

**Cosa è stato fatto:**
- Chiarito un fraintendimento iniziale: Gianluca pensava Studio fosse "il lavoro piccolo" perché è un solo file — in realtà è il file più grande e più delicato (dati commerciali reali); IA TEAM ha più pagine ma ciascuna più semplice. Confermato con Gianluca: si parte da IA TEAM.
- Confermato esplicitamente il modello a 3 stati: amministratore (solo Gianluca, accesso completo), operatore/collaboratore (accesso pieno alle azioni, non alla pagina admin né ai pulsanti di debug), osservatore/visualizzatore (vede tutto, non può agire).
- Inventario completo: elencate tutte le pagine IA TEAM (17) più le tab non-Account di Impostazioni; per ciascuna, classificate le azioni in "sola lettura/navigazione" vs "da limitare per l'osservatore", confermato un pezzo alla volta con Gianluca.
- Nuovo requisito UX da Gianluca: i pulsanti bloccati per l'osservatore, una volta cliccati, devono mostrare un popup che spiega cosa farebbe quell'azione — non un semplice `disabled` che non fa nulla.
- Scelta implementativa conseguente: il controllo (`gateIa()`/`gateAdmin()`) vive dentro le funzioni che scrivono/lanciano, non nei singoli elementi HTML — più robusto perché molti pulsanti sono generati dinamicamente via JS. Lo smorzamento visivo (classe `.role-disabled`) è un livello separato, solo estetico.
- Implementato su tutte le 17 pagine: home (Messaggio/Apri chat A5-A6, Crea Bozza+token+lancio A7, pulsanti ciclo editoriale, più i pulsanti stato-pill bloccati anche per l'operatore e sbloccati solo per `is_admin`), pipeline (pulsante "+" Aggiungi azienda), azienda (follow-up, note, token GitHub, modalità modifica della pipeline a rami, aggiungi evento/ramo, Messaggio/Apri chat, Genera bozza A7), scheda azienda (Esporta PDF), A1 (salva categoria post, carica CSV), A5 e A6 (Messaggio/Apri progetto), A7 (apri picker, che copre a cascata selezione/token/lancio).
- **Bug/codice morto scoperto e risolto**: `openPopupThen`/`closePopup`/`execAction` e il popup "Vuoi aggiungere una nota?" in `page_company_v2.html` erano orfani — stesso tipo di dead code di `renderAzioni` (risolto in una sessione precedente), dimenticato nella stessa pulizia. Rimossi insieme alla CSS associata, verificato che nessun punto del file li richiamasse più.
- Verificato con Playwright, pagina per pagina: per l'osservatore, pulsante visivamente smorzato, popup mostrato con il testo corretto, nessuna scrittura né navigazione eseguita (incluso il blocco della navigazione su link `target="_blank"`); per l'operatore e l'admin, comportamento normale e invariato rispetto a prima.
- **Creazione account aggiunta alla pagina di amministrazione**: Gianluca ha chiesto da dove aggiungere un nuovo account, poi se si potesse fare dalla webapp invece che dalla dashboard Supabase. Creata la Edge Function `admin-create-user` (stesso pattern di `upsert_company`, già presente nel progetto): verifica `is_admin` lato server con la service_role key (mai esposta al browser) prima di creare l'account Supabase Auth; il trigger esistente gli assegna poi automaticamente il profilo. In webapp, modulo "Nuovo account" (email, password con generatore, pulsante "Crea account") sopra l'elenco collaboratori, che si aggiorna subito dopo la creazione. Verificato con Playwright: creazione riuscita ed errore (email duplicata) gestito correttamente.
- **Password persa su un account appena creato**: Gianluca ha creato un account di prova (`test.collaboratore@gdciateam.it`) ma non ha salvato la password in tempo, chiedendo di "recuperarla da Supabase". Spiegato che una password non è mai recuperabile (Supabase la salva solo come hash salato, non in chiaro) — la sola via è impostarne una nuova. Identificato l'account con una query di sola lettura su `profiles`/`auth.users` ordinata per data di creazione, poi reimpostata subito la password via SQL diretto (`crypt()`/`gen_salt('bf')` di pgcrypto su `auth.users.encrypted_password`, compatibile con l'hashing bcrypt usato da Supabase Auth) per dare accesso immediato, dato che l'account era appena stato creato e la situazione era bloccante. In parallelo, estesa la Edge Function `admin-create-user` per accettare anche `{user_id, password}` (reset di un account esistente via `PUT /auth/v1/admin/users/{id}`, stesso controllo `is_admin` lato server) invece di solo `{email, password}` (creazione), e aggiunto in webapp un pulsante "Reimposta password" per ogni collaboratore nell'elenco, con generatore di password e password mostrata una sola volta a schermo dopo il reset.
- **Disabilitazione ed eliminazione account**: Gianluca ha chiesto come rimuovere un collaboratore che non vuole più, chiarendo che "eliminare" per lui significa soprattutto che le credenziali non funzionino più — non necessariamente che l'account scompaia dall'elenco. Chiesto (AskUserQuestion) se bastasse una disabilitazione reversibile o servisse anche un'eliminazione definitiva: Gianluca ha scelto entrambi. Riprogettata la Edge Function `admin-create-user` con un dispatch esplicito sul campo `action` (`create`/`reset_password`/`ban`/`unban`/`delete`), retrocompatibile con le chiamate già esistenti. `ban`/`unban` usano `PUT /auth/v1/admin/users/{id}` con `ban_duration` (`876000h` ≈ permanente, o `none` per riattivare) — l'account resta integro e visibile, solo il login viene bloccato — e aggiornano anche una nuova colonna `profiles.banned` (cache server-side, scritta dalla stessa Edge Function con la service role key) così la webapp può mostrare lo stato senza interrogare `auth.users` direttamente. `delete` usa `DELETE /auth/v1/admin/users/{id}`: cancella l'account Auth e, per cascata della foreign key `profiles_user_id_fkey` (`ON DELETE CASCADE`), anche il profilo collegato — a quel punto sparisce davvero dall'elenco, in modo irreversibile. In webapp (Impostazioni > Account): pulsante "Disabilita"/"Riattiva" che cambia etichetta in base allo stato (con badge "Disabilitato" sulla riga quando attivo) e pulsante "Elimina definitivamente" con conferma a prova di click accidentale (va digitata l'email esatta dell'account). Verificato con Playwright l'intero ciclo: disabilita → badge compare, riattiva → badge scompare, elimina → riga rimossa dall'elenco.

**Decisioni prese:**
- Contesto: come gestire il fallimento del caricamento del ruolo (es. problema di rete con Supabase).
- Decisione: fail-open, resta `operatore` se la fetch a `profiles` fallisce.
- Alternative scartate: fail-closed (osservatore di default) — scartato perché l'unico utente reale oggi è sempre admin, e un guasto temporaneo di Supabase non deve bloccare il lavoro normale.
- Da rivedere se: in futuro esistono collaboratori reali con ruoli diversi e un blocco di rete diventa un rischio di falso-positivo "operatore" per un vero osservatore — a quel punto si potrebbe aggiungere un retry o un indicatore di stato incerto.
- Contesto: come trattare il ruolo `nessuno` (account senza assegnazione) ai fini del blocco azioni.
- Decisione: trattato come osservatore (default sicuro, nessuna via di mezzo più permissiva).
- Contesto: come permettere la creazione di account dalla webapp, visto che serve la service_role key (mai lato client).
- Decisione: Supabase Edge Function con verifica `is_admin` lato server. Supera la decisione iniziale dello Step 11 ("gli account si creano altrove") — vedi nota nel blocco Step 11 della Pipeline.
- Alternative scartate: invito via email vero e proprio — richiederebbe configurare l'invio email sul progetto Supabase, non fatto; si comunica la password direttamente invece.
- Contesto: come sbloccare subito un account con password persa, senza accesso diretto alla rete Supabase da riga di comando in questa sessione (il proxy di rete del sandbox blocca le chiamate dirette a `*.supabase.co`, vedi Problemi aperti/errori sessioni precedenti).
- Decisione: per lo sblocco immediato, SQL diretto su `auth.users.encrypted_password` con `crypt()`/`gen_salt('bf')` di pgcrypto (tecnica nota e supportata per Supabase self-service, compatibile con l'hash bcrypt che Auth si aspetta). Per l'uso futuro, invece, meccanismo "ufficiale" via Edge Function (Admin API), così resta coerente con il resto del sistema e non richiede più accesso diretto al database.
- Da rivedere se: in futuro serve anche poter resettare la password di un admin da webapp (oggi il pulsante "Reimposta password" compare solo per i collaboratori non-admin, coerente con l'elenco `is_admin=eq.false` già usato altrove nella pagina).
- Contesto: come implementare la "rimozione" di un collaboratore, visto che Gianluca ha chiesto sia il blocco del login sia (eventualmente) la cancellazione vera e propria.
- Decisione: due pulsanti distinti e separati — "Disabilita/Riattiva" (ban reversibile, l'account resta visibile) ed "Elimina definitivamente" (cancellazione permanente, irreversibile) — Gianluca ha scelto esplicitamente questa opzione ("Entrambi") tra tre proposte.
- Alternative scartate: un solo pulsante "Elimina" che cancella sempre tutto — scartato perché non distingue il caso reversibile (sospensione temporanea) da quello permanente, e avrebbe reso banale perdere per sempre un account per errore.
- Da rivedere se: in futuro serve distinguere ulteriormente "disabilitato dall'admin" da altri stati account (es. sospeso per inattività) — oggi `profiles.banned` è un flag booleano unico.

**File consegnati/modificati:** `app/page_home_v25.html`, `page_pipeline_v1.html`, `page_company_v2.html`, `app/page_scheda_azienda_v1.html`, `app/agenti/a1-analytics/categorizza.html`, `app/agenti/a1-analytics/carica_mbs.html`, `page_agent_a5_v1.html`, `page_agent_a6_v1.html`, `page_agent_a7_v1.html`, `app/page_settings_v1.html`; Edge Function Supabase `admin-create-user` (non versionata nel repo, come le altre Edge Function del progetto, azioni `create`/`reset_password`/`ban`/`unban`/`delete`); migrazione `profiles_add_banned_flag` (colonna `profiles.banned`); reset una tantum via SQL della password dell'account `test.collaboratore@gdciateam.it`.

**Impatto su Vision/Pipeline:** Step 11 ora quasi completo — resta solo l'enforcement su GDC Studio (deliberatamente rimandato) prima di poter dire lo step concluso.

---

### [2026-11-19 23:39] Header/navigazione di `page_company_v2.html` applicati al reale, chiuso lo Step 10, avviato lo Step 11 (tabella `profiles` + pagina di amministrazione)

**Riepilogo:** applicato al file reale l'header di `page_company_v2.html` (mancava ancora, era solo mockup), risolti due vicoli ciechi di navigazione e il bug preesistente delle "Azioni rapide" segnalati da Gianluca, estesa la pillola "torna indietro" coerente a 7 pagine secondarie, e avviato lo Step 11 (ruoli/permessi per collaboratori, modello già deciso in una sessione precedente): tabella `profiles` + RLS, e pagina di amministrazione in Impostazioni → Account.

**Cosa è stato fatto:**
- Header di `page_company_v2.html`: aggiunto l'indicatore "Connesso a Supabase" e il calendario popup interattivo, sostituiti il vecchio bottone "← Pipeline" (`history.back()`) e il bottone "Hub" separato con la pill-row standard Home/Pipeline — stesso componente già in uso su Home/A1-A7/Pipeline.
- **Bug: loop di navigazione azienda↔scheda.** Sintomo: tornare dalla scheda azienda alla pipeline riapriva la scheda in un loop. Causa: `page_company_v2.html` unico punto dell'app a usare `history.back()`, in conflitto con la navigazione a link diretti usata ovunque (compresa la scheda azienda stessa). Fix: link diretto e deterministico al posto di `history.back()`.
- **Bug: link "Apri" di A6 verso i report A2 portava al login.** Causa: apriva `report.html` in una nuova scheda (`target="_blank"`), che non eredita il token di sessione da `sessionStorage`. Fix: rimosso `target="_blank"`.
- Pillola "torna indietro" (clip-path, senza freccetta nel testo) estesa a 7 pagine secondarie (categorizza post, carica CSV, elenco/dettaglio report A2, dashboard KPI, scheda azienda, elenco/dettaglio piani editoriali, elenco/dettaglio brief mensili), su richiesta esplicita di Gianluca.
- **Bug: "Azioni rapide" non facevano nulla.** Causa: `renderAzioni()` orfana, scriveva su id HTML rimossi in una sessione precedente insieme ai pulsanti di avanzamento manuale (sostituiti dal click diretto sui pallini della pipeline a rami). Fix: rimossi la funzione, i call-site, gli helper e la CSS associata, tutti dead code verificato.
- **Step 11 avviato**: creata la tabella `profiles` con RLS, due funzioni helper `SECURITY DEFINER` (`is_admin()`, `current_user_role(area)`), trigger di provisioning automatico su nuovo account, seed dell'account esistente di Gianluca come admin. Chiesto a Gianluca con quale pezzo proseguire (pagina admin, enforcement IA TEAM, o enforcement Studio) — scelta: pagina admin prima.
- **Pagina di amministrazione implementata** in `app/page_settings_v1.html`, tab Account: sottotitolo del proprio account reso dinamico (prima testo statico "Amministratore", ora legge il ruolo reale da `profiles`); sezione "Amministrazione" visibile solo a `is_admin`, con elenco dei collaboratori (account non-admin) e due select per assegnare `ia_team_ruolo`/`studio_ruolo`, salvataggio immediato via PATCH a ogni cambio. Nessun flusso di invito — coerente con la decisione già presa ("gli account li crea Gianluca altrove").
- Colmato un buco nel registro `supabase/migrations/`: le due migrazioni della sessione precedente (`add_lanes_trunk_events_rejected`, `backfill_lanes_rejected`) erano state applicate su Supabase ma non registrate come file nel repo — aggiunte ora insieme alla nuova migrazione `profiles`.

**Decisioni prese:**
- Contesto: come avviare lo Step 11 (ruoli/permessi) senza costruire subito tutto insieme (pagina admin + enforcement su decine di pagine), vista la dimensione del lavoro (due aree separate, IA TEAM multi-pagina e Studio un unico file grande).
- Decisione: prima le sole fondamenta dati (tabella + RLS + helper), poi chiesto esplicitamente a Gianluca l'ordine dei passi successivi invece di deciderlo autonomamente — risposta: pagina di amministrazione prima, poi l'enforcement (ordine IA TEAM vs Studio ancora da decidere).
- Alternative scartate: implementare anche l'enforcement nella stessa sessione senza chiedere — scartato per evitare di impegnare una modifica così ampia (tocca l'autenticazione/sicurezza di tutta l'app, due aree molto diverse per dimensione) senza un check-in esplicito sulla sequenza.
- Da rivedere se: Gianluca indica un ordine diverso per l'enforcement (es. prima Studio, che tocca dati commerciali reali, invece di IA TEAM).

**File consegnati/modificati:** `page_company_v2.html`; `page_agent_a6_v1.html`; `app/agenti/a1-analytics/categorizza.html`; `app/agenti/a1-analytics/carica_mbs.html`; `app/agenti/a2-analyst/report.html`; `app/agenti/a2-analyst/dashboard_kpi.html`; `app/page_scheda_azienda_v1.html`; `app/agenti/a3-planner/piano.html`; `app/agenti/a4-brief/brief.html`; `app/page_settings_v1.html`; migrazione Supabase `create_profiles_table` (+ registro di `add_lanes_trunk_events_rejected`/`backfill_lanes_rejected` mancanti); `supabase/migrations/20261119_create_profiles_table.sql` e i due file di registro recuperati.

---

### [2026-11-19 21:13] "Pipeline a rami" completata e applicata a `page_company_v2.html`, con migrazione dati Supabase

**Riepilogo:** il mockup della pipeline a rami (avviato nella sessione precedente) è stato rifinito su 5 round di feedback diretto fino alla v11, poi portato in produzione su `page_company_v2.html` — sostituisce la vecchia timeline pipeline e la sezione "Canali di contatto" con un unico componente, con nuovo schema Supabase e migrazione dei 56 record esistenti.

**Cosa è stato fatto:**
- Rifinito il mockup dalla v6 alla v11 (vedi Step 10 → Note per il dettaglio round per round): bordo pallino+scheda continuo, linee sotto ai pallini del tronco, gating step 10-12 su "almeno un canale a Gestita" con step 13 escluso, numeri su tutti i pallini, un solo "+", contatori eventi reali ed estesi a tutti gli step 1-13 allineati in colonna, storico eventi anche sul tronco, titoli allineati a sinistra, tronco centrato dinamicamente sul numero di rami, bivio spostato dallo step 6 allo step 4 (Testo/Bozza diventano stadi di ogni ramo, non solo di Mail).
- Risolti nel mockup (poi portati anche sul file reale) tre bug: retrocedere nel tronco non azzerava i rami già avanzati; attivare un ramo senza aver superato il bivio lasciava il tronco "indietro"; lo step 13 "Rifiutato" segnava come fatti tutti i pallini precedenti (stessa causa radice del bug trovato nell'audit, ora risolta anche nel codice reale, non solo nel mockup).
- Applicato il design a `page_company_v2.html`: unite le vecchie sezioni "② Pipeline" e "④ Canali di contatto" in un unico componente; CSS/HTML/JS portati dal mockup e adattati al "ponte automatico" con l'automazione Gmail esistente (vedi Decisioni prese); rimossi i vecchi popup/funzioni di nota-per-step e canale ormai sostituiti.
- Migrazione Supabase: nuove colonne `lanes`/`trunk_events`/`rejected` su `companies` (additive), backfill dei 10 record Instagram esistenti e correzione dell'unica azienda col bug step 13 (GoPro).
- Scoperto e segnalato (non corretto, fuori scope) un bug preesistente indipendente: i pulsanti "Azioni rapide" puntano a elementi HTML che non esistono più, falliscono silenziosamente.
- Verificato tutto con Playwright sul file reale, instradando Supabase verso dati equivalenti ai reali (non solo sul mockup): rendering chiaro/scuro, ponte mail, gating, rifiuto indipendente, creazione di un ramo manuale custom.

**Decisioni prese:**
- Contesto: gli step 5-9 (ora dentro i rami) sono scritti in produzione dall'automazione Gmail A6/A7, e la pagina lista pipeline dipende dagli stessi campi — una migrazione completa avrebbe richiesto riscrivere anche quei prompt.
- Decisione: "ponte automatico" — l'automazione continua a scrivere esattamente come oggi (`step_5..step_9`/`step_N_date`/`step_notes`), la pagina azienda legge questi campi dal vivo per il ramo Mail invece di duplicarli in una nuova struttura. I nuovi campi jsonb (`lanes`, `trunk_events`) coprono solo le parti senza automazione (Instagram, LinkedIn, rami manuali, storico eventi extra del tronco).
- Alternative scartate: migrazione completa subito (anche del ramo Mail), che avrebbe richiesto aggiornare anche i prompt A6/A7 — scartata per rischio/tempo, scelta esplicita di Gianluca.
- Decisione presa autonomamente in fase di applicazione (non nel mockup): NON portare sul file reale il comportamento del mockup "retrocedere nel tronco azzera i rami" — su dati veri avrebbe potuto cancellare contatti reali per un click sbagliato. Segnalato esplicitamente a Gianluca come deviazione deliberata.
- Da rivedere se: si decide in futuro di aggiornare il prompt A6 per scrivere uno storico eventi multiplo anche per il ramo Mail (oggi mostra un solo evento per stadio, a differenza degli altri rami) — o se si decide di dare ai rami manuali/Instagram/LinkedIn anche loro un meccanismo di "reset on regress" ora volutamente assente.

**File consegnati/modificati:** `page_company_v2.html` (riscritta la sezione pipeline+canali); migrazioni Supabase `add_lanes_trunk_events_rejected` e backfill dati; `docs/documento-sessione-gdc-ia-team.md` (questo aggiornamento).

**Impatto su Vision/Pipeline:** Step 10 aggiornato — il redesign "pipeline a rami" è ora **completato e applicato**, non più solo a livello di mockup (vedi Pipeline → Step 10 per Stato/Decisioni progettuali/Criterio di completamento aggiornati).

---

### [2026-11-19 17:59] Canali/follow-up: direzione scelta e applicata; header pipeline+company allineati; avviato redesign "pipeline a rami"

**Riepilogo:** chiusa la decisione sulle fragilità trovate nell'audit di pipeline/azienda (scala a 4 livelli, due date per canale) e applicata alle pagine reali; allineato l'header/navigazione di `page_pipeline_v1.html` al resto dell'app (applicato) e preparato lo stesso per `page_company_v2.html` (solo mockup); avviato — su richiesta di Gianluca, con un cambio di grafica significativo rispetto al primo tentativo — un redesign più ampio che reintegra i canali di contatto dentro l'alberatura della pipeline 1-13, con rami personalizzabili e storico eventi multi-voce; arrivato a un mockup interattivo (v6) che Gianluca sta ancora provando.

**Cosa è stato fatto:**
- Deciso e applicato: due date per canale (primo contatto/ultimo cambio stato), scala verde/sabbia/sospesa/rosso comune a mail e canali social, soglie 21gg/60gg. Migrazione Supabase `add_channel_primo_contatto_dates` con backfill.
- Applicato a `page_pipeline_v1.html`: pill separate Mail/LinkedIn/Instagram nella card, bandierina di priorità multi-canale.
- Applicato a `page_company_v2.html`: sezione "Canali di contatto" separata dallo step 7 (poi messa in discussione, vedi sotto), bug `saveChannelNote()` risolto e verificato.
- Applicato a `page_pipeline_v1.html`: header/navigazione allineati al resto dell'app (logo-stato-data, pillola "Home" a freccia, calendario).
- Preparato (non applicato) lo stesso header per `page_company_v2.html`.
- **Bug: lo storico di uno scambio di mail (es. più follow-up) finiva tutto schiacciato in un'unica nota con un'unica data sovrascritta, perdendo la cronologia reale.** Causa: il modello dati tracciava un solo stato+una data per step, non un log di eventi. Fix progettato e prototipato a livello di mockup (vedi sotto) — non ancora sul file reale/schema dati.
- Avviato, su richiesta di Gianluca, un redesign che reintegra i canali nell'alberatura 1-13 (biforcazione dopo lo step 6, ricongiungimento allo step 10, rami aggiungibili a mano con testo libero, storico eventi multi-voce per ogni ramo). Iterato con 6 versioni di mockup e feedback diretto (inclusi due schizzi a mano di Gianluca), arrivando a un mockup interattivo (v6) con colonne di pari peso, pannello che spinge e si fonde col pallino cliccato, linee ridisegnate in tempo reale dalla posizione reale dei pallini, matita che attiva direttamente qualunque pallino. Non ancora applicato al file reale.

**Decisioni prese:**
- Contesto: come intervenire sulle fragilità trovate nell'audit di pipeline/azienda (sessione precedente, nessuna direzione ancora scelta).
- Decisione: niente automazione Gmail; due date per canale + scala a 4 livelli comune a mail e social; soglia "sospesa" a 60gg (il doppio della soglia di silenzio a 21gg).
- Alternative scartate: automazione del rilevamento risposte via Gmail (rischio notifiche ignorate, tasso di risposta reale già basso — scartata da Gianluca); nome "Morta" per lo stato bianco/nero (sostituito con "Sospesa", scelto da Gianluca).
- Contesto: come mostrare i canali nella pagina azienda, dopo averli appena separati in una sezione dedicata.
- Decisione: reintegrarli nell'alberatura della pipeline 1-13 come rami che si diramano e si ricongiungono, con storico eventi multi-voce e possibilità di aggiungere rami personalizzati.
- Alternative scartate: sezione "Canali di contatto" separata dalla pipeline (appena applicata, superata dalla nuova richiesta); card impilate sotto la pipeline (mockup v1, grafica non gradita); pannello overlay ancorato al pallino invece che spinta con le linee statiche (mockup v5, scartato — Gianluca voleva la spinta con le linee che seguono, non un cambio di meccanismo).
- Da rivedere se: in fase di implementazione reale emergesse che lo schema dati a rami arbitrari (oggi solo mail/LinkedIn/Instagram hanno colonne dedicate) è più complesso del previsto da generalizzare senza toccare i dati già migrati.

**File consegnati/modificati:**
- Modificati e applicati: `page_pipeline_v1.html` (canali + header/navigazione), `page_company_v2.html` (sezione Canali di contatto, bug fix).
- Migrazione Supabase: `add_channel_primo_contatto_dates`.
- Mockup (non applicati, solo artifact): header `page_company_v2.html`; redesign "pipeline a rami" (6 versioni, l'ultima — v6 — ancora in revisione presso Gianluca).

**Impatto su Vision/Pipeline:** nessuna modifica alla Vision. Pipeline: Step 10 aggiornato con la direzione scelta per l'audit e il nuovo fronte di lavoro "pipeline a rami" (vedi Decisioni progettuali e Note dello step).

---

### [2026-11-19 10:36] Progettato il modello di ruoli/permessi per collaboratori (osservatore/operatore, per area)

**Riepilogo:** sessione di sola discussione/progettazione su richiesta di Gianluca, prima di riprendere il lavoro tecnico su pipeline/azienda: definito nel dettaglio il modello di ruoli per far accedere collaboratori alla webapp con permessi limitati, e discusso (e rimandato) il tema più ampio di renderla un template personalizzabile per terzi.

**Cosa è stato fatto:**
- Esplorato lo stato attuale dell'autenticazione: il login usa già Supabase Auth reale (non una password condivisa), quindi account multipli sono già possibili — manca solo un livello di ruoli/permessi.
- Definito con Gianluca, a domande mirate, il modello completo per i collaboratori: due ruoli (osservatore/operatore) indipendenti per area (GDC IA TEAM / GDC Studio), tabella `profiles` con flag admin, pagina di amministrazione in Impostazioni → Account (solo gestione permessi, niente inviti via email per ora), comportamento pulsante-per-pulsante per l'osservatore su IA TEAM (visibile ma disattivato) e su Studio (sola visualizzazione, eccetto il Calcolatore Prezzi che può calcolare/salvare bozza ma non creare un ordine vero), pulsanti di stato-test riservati solo all'amministratore, e una soluzione per il limite "i link Claude.ai portano al profilo di Gianluca" (link di download del prompt md/docx di ogni agente, nella tab Azioni di ciascuna pagina agente, non in home).
- Discusso il tema più ampio — rendere la webapp un template personalizzabile da altre persone — e deciso di **rimandarlo esplicitamente**: non scartato, ma riconosciuto come molto più complesso (richiede ripensare decisioni di business specifiche, non solo un wizard di configurazione), con due strade tecniche già individuate per quando verrà ripreso (clone-e-configura vs vero multi-tenant).
- Dettagli completi del modello nello Step 11 della Pipeline (nuovo).

**Decisioni prese:**
- Contesto: come gestire l'accesso di un collaboratore con ruolo "operatore" ai pulsanti "Messaggio"/"Apri chat"/"Apri sessione", che aprono i progetti Claude.ai personali di Gianluca.
- Decisione: aggiungere un link di download del prompt (md/docx, già esistenti in `docs/prompts/`) nella tab Azioni di ogni pagina agente — non in home, per non toccare la grafica della home già sistemata più volte in questa sessione.
- Contesto: cosa può fare un osservatore su GDC Studio, dove esiste un'unica azione che scrive dati (il Calcolatore Prezzi).
- Decisione: può calcolare e salvare come progetto bozza, non può "Invia a ordini" (creazione di un ordine reale con cliente).
- Contesto: punto più ampio, rendere la webapp un template per altre persone.
- Decisione: rimandato, non scartato — priorità resta chiudere lo Step 10 (audit pipeline/azienda) e poi lo Step 11 (ruoli) prima di riaffrontarlo.
- Alternative scartate: nessuna per lo Step 11 (prima proposta, niente da scartare); per il template, scartata l'idea di affrontarlo subito — troppa complessità di business logic da ripensare, non solo di infrastruttura.

**File consegnati/modificati:** nessuno — sessione di sola discussione/progettazione, nessuna modifica al codice.

**Impatto su Vision/Pipeline:** aggiunto un nuovo Step 11 alla Pipeline ("Ruoli e permessi per collaboratori").

---

### [2026-11-18 22:14] A7 approvato e applicato, fix trasversale riposo/home, rifiniture home/hub, avviato audit funzionale pipeline/azienda

**Riepilogo:** chiuso il redesign grafico di A7 (mockup approvato e applicato al file reale), risolto un residuo del bug "riposo" su home non coperto dal fix della sessione precedente, sistemate diverse piccole rifiniture su home/hub (trovando per strada un bug reale sullo spazio in eccesso nelle schede agente), e avviato — su richiesta esplicita di Gianluca — un audit approfondito del funzionamento (non della grafica) di pipeline e scheda azienda, con findings concreti ma nessuna decisione ancora presa.

**Cosa è stato fatto:**
- Mockup A7 rifinito a più riprese (rimosso riquadro esplicativo e scritta statica ridondante, tab Setup confluita in Config, tab Stato eliminata, pulsante GitHub dispatch ridondante rimosso, icone busta semplificate) e approvato; applicato a `page_agent_a7_v1.html` (ripristinato il redirect login tolto solo per l'anteprima in Artifact).
- **Bug: stato "riposo" in home ancora con contrasto sbagliato in tema scuro nonostante il fix della sessione precedente.** Sintomo: riquadro logo bianco invece che nero. Causa: regola CSS residua con `!important` che forzava lo sfondo a bianco in tema scuro, in conflitto con la regola base (sempre nero) — stesso bug replicato su tutte le pagine A1-A7. Fix: rimossa la regola residua ovunque, insieme alle sovrascritture dei singoli loghi diventate superflue. Verificato con Playwright in entrambi i temi, tutte le pagine.
- Rifiniture home/hub su richiesta di Gianluca: testo footer hub, spaziatura riga Hub/notifiche/impostazioni, pulsanti "Apri sessione"/"Copia messaggio" uniformati e neutri, pulsante Pipeline Sponsorizzazioni senza freccia e neutro, rimosse pillole Supabase/Drive da A5/A6, rimossa legenda a pallini.
- **Bug: spazio in eccesso tra la fine di alcune schede agente (A2/A3) e la riga dei pulsanti di stato.** Causa: `setLogoState()` sovrascriveva `card.className` perdendo la classe `acard-logo-round` (che centra il contenuto) già presente nel markup statico. Fix: classe preservata nell'aggiornamento — risolve il sintomo alla radice su tutte le schede.
- Aggiunto il colore di stato individuale (prima statico) ai sottotitoli A5.1/A5.2/A6.1/A6.2.
- **Audit funzionale di `page_pipeline_v1.html`/`page_company_v2.html`** incrociando codice e dati reali Supabase: pipeline 7-13 (trattativa) completamente manuale senza automazione; 18 aziende ferme allo step 7 da 61-187gg; LinkedIn mai usato (0/56), Instagram usato solo su 10/56 e comunque fermo; bug nel salvataggio contatto canali (la data si sovrascrive sempre, perdendo "primo contatto" vs "ultima modifica"); modello dati incoerente fra mail (due date distinte) e canali social (una sola data); logica giorni/follow-up duplicata fra due file senza una funzione condivisa. Dettagli completi nella nota dello Step 10 del 2026-11-18 (sessione successiva).

**Decisioni prese:**
- Contesto: nel mockup A7, come gestire l'icona delle due azioni "Crea bozza"/"Apri bozze" senza un'icona univoca coerente per "crea".
- Decisione: usare la sola icona busta per entrambe, invece di una combinazione busta+matita.
- Alternative scartate: busta+matita per "Crea bozza" (bocciata esplicitamente da Gianluca — "non voglio 2 icone se non ne hai una coerente va bene solo la busta").

**File consegnati/modificati:** `page_agent_a7_v1.html`, `app/page_home_v25.html`, `page_agent_a5_v1.html`, `page_agent_a6_v1.html`, `app/page_hub_v1.html`; mockup iterato e pubblicato come Artifact (non persistito nel repo).

**Impatto su Vision/Pipeline:** Step 10 aggiornato — redesign grafico ora completo su tutte le pagine A1-A7+home; aggiunto un fronte nuovo ("audit funzionale pipeline/azienda") ancora aperto, in attesa della direzione di Gianluca.

---

### [2026-11-18 20:57] Redesign pagina A6 + mockup A7 + trovati e risolti bug trasversali su colori di stato e tema chiaro/scuro (A1-A7, tutte le pagine)

**Riepilogo:** applicato il redesign mockup-first ad A6 (mantenendo la tab Documenti, a differenza di A5, perché lì i file restano davvero su Drive), preparato il mockup di A7 (ancora in revisione), e — grazie al test manuale di Gianluca di ogni stato reale su Supabase — trovati e corretti tre bug di colore sulle pagine agente (icona/badge invertiti, contorno/titolo statici, stato "errore" mai gestito, icone invisibili in tema scuro) più un bug separato per cui il tema scelto in Impostazioni non si applicava a nessun'altra pagina dell'app.

**Cosa è stato fatto:**
- Redesign completo di `page_agent_a6_v1.html` (mockup approvato da Gianluca dopo alcune iterazioni): header/nav allineati ad A5, hero con A6.1/A6.2 affiancate e badge indipendenti, tab Azioni neutralizzata, tab Modalità assorbita nella tab Lavoro, JS pulito. Tab Documenti mantenuta (decisione deliberata, vedi sotto) ma corretta: righe file rese esplicitamente non cliccabili con un solo pulsante "Apri" verso la cartella, e aggiunto un collegamento reale alla pagina dei report A2 al posto di un riferimento Drive morto.
- Mockup di `page_agent_a7_v1.html` preparato e consegnato per revisione (file inviato direttamente in chat, non come allegato scaricabile, e poi anche come Artifact apribile nel pannello — il download diretto non andava bene a Gianluca). Non ancora applicato al file reale.

**Bug: colori icona vs badge invertiti (queued/sleep), su A1-A7**
**Sintomo:** cambiando stato via Supabase, badge e icona di uno stesso stato a volte avevano famiglie di colore diverse.
**Causa:** colori esadecimali di "queued" e "sleep" scambiati tra loro nel CSS dell'icona — bug di origine nel template, identico su ogni pagina.
**Fix applicato:** valori ripristinati; poi corretti di nuovo (vedi bug successivo) perché il primo fix era stato dedotto per analogia invece che copiato dalla fonte corretta.

**Bug: sfondo del riquadro logo incoerente/mai aggiornato di default, su A1-A7**
**Sintomo:** riquadro di colore sbagliato (verde o blu fisso) con icona di un altro colore, visibile su ogni errore di caricamento dati o pagina senza sessione (incluso il mockup inviato in chat, senza token).
**Causa:** `.logo-box-hero` aveva un colore di sfondo di default hardcoded, indipendente dallo stato reale e mai aggiornato dal catch-block in caso di errore.
**Fix applicato:** rimosso il colore fisso dalla regola base; il riquadro parte già nella classe di stato "sleep" via markup statico, stesso meccanismo della home.

**Bug: contorno hero-card e titolo statici (non seguivano lo stato), stato "errore" mai gestito, icone "riposo" invisibili in tema scuro — su A1-A7**
**Sintomo:** testando ogni stato reale su Supabase, Gianluca ha trovato che contorno e titolo restavano quasi sempre fissi su un colore sbagliato (corretti solo per lo stato che per caso coincideva col colore statico); uno stato "errore" mostrava blu invece di rosso; in tema scuro alcune parti delle icone in stato "riposo" sparivano contro lo sfondo che diventa quasi bianco.
**Causa:** (1) contorno/titolo non erano mai stati collegati a nessuna logica di stato — i due fix precedenti in questa stessa sessione avevano reso dinamici solo badge e icona; (2) nessun `mapState()` riconosceva lo stato `error` (scritto dagli script Python in caso di eccezione), che cadeva quindi nel ramo di default "sleep"; (3) i colori delle icone in stato "riposo" sono valori fissi non legati al tema, mentre lo sfondo del riquadro in quello stato è theme-aware (fix di una sessione precedente) — in scuro i due non combinavano più. In più, A1 non aveva affatto la logica condivisa `mapState()`/`STATE_CFG` delle altre pagine (if/else inline con un ramo finale "sleep" che catturava per sbaglio anche "in coda" e "riposo", mai gestiti).
**Fix applicato:** confrontata riga per riga `app/page_home_v25.html` (unica pagina già corretta, confermato da Gianluca) per ottenere i colori giusti; aggiunta una mappa `INK_CFG` + gli id `heroCard`/`agentTitle` mancanti per rendere contorno e titolo dinamici come badge/icona; aggiunta una voce `error` dedicata in ogni `STATE_CFG` (stessa resa visiva di "in coda", rosso, etichetta propria "Errore"); aggiunto un override di tema scuro per le parti bianche delle icone in riposo; A1 refactorato sullo stesso pattern condiviso delle altre pagine, con la segnalazione "MBS mancante" mantenuta come override di priorità sopra lo stato normale. Verificato con `node --check` e controlli di coerenza degli id su tutti i 7 file.

**Bug: il tema di Impostazioni non si applicava alle altre pagine**
**Sintomo:** cambiando tema in Impostazioni > Aspetto, solo quella pagina cambiava — tutte le altre restavano legate al tema del sistema/browser.
**Causa:** solo `page_settings_v1.html` leggeva `localStorage.gdc_theme_cache` e impostava l'attributo `data-theme`; le altre 19 pagine con un tema scuro definito lo attivavano solo tramite `@media(prefers-color-scheme:dark)`, ignorando la preferenza esplicita salvata.
**Fix applicato:** stesso meccanismo di Impostazioni esteso a tutte le 19 pagine (script inline pre-CSS, regole del tema scuro condizionate anche a `:not([data-theme="light"])`, copia di ogni regola fuori dal media query sotto `:root[data-theme="dark"]`). Verificato con Playwright in entrambe le direzioni (sistema chiaro + tema forzato scuro, e viceversa), su variabili CSS e su colori hardcoded.

**Decisioni prese:**
- Contesto: A5 aveva rimosso la tab Documenti perché il suo contenuto (link Drive per i report) era superato dalla migrazione a Supabase.
- Decisione: per A6 la tab Documenti resta, perché i suoi contenuti (media kit, mail) sono file che restano davvero su Drive — A7 li legge proprio da lì.
- Da rivedere se: A7 o un futuro agente smettesse anch'esso di appoggiarsi a Drive per l'output reale.
- Contesto: bisognava decidere come rendere dinamici contorno/titolo della hero-card senza introdurre una terza fonte di colore indipendente da badge/icona.
- Decisione: stessa identica palette di badge/icona per ogni stato (non la combinazione leggermente diversa — es. sfondo più chiaro per il contorno — usata nella home per le sue card), eccetto lo stato "riposo" dove entrambi usano un nero/bianco theme-aware pensato apposta per questo redesign (non presente nella home, che non ha un trattamento così marcato per "riposo").
- Alternative scartate: riprendere esattamente le sfumature della home card (`border-color:var(--athlete-bg)` per sleep) — scartata perché Gianluca aveva già confermato corretto il colore pieno (`var(--athlete)`) già in uso su A5/A6 da una sessione precedente.

**File consegnati/modificati:**
`page_agent_a6_v1.html` (redesign completo), `page_agent_a5_v1.html`, `page_agent_a7_v1.html`, `app/agenti/a1-analytics/page_agent_a1_v1.html` (refactor mapState/STATE_CFG), `app/agenti/a2-analyst/page_agent_a2_v3.html`, `app/agenti/a3-planner/page_agent_a3_v1.html`, `app/agenti/a4-brief/page_agent_a4_v1.html` — fix colori di stato; più, per il fix del tema, anche `app/page_home_v25.html`, `page_company_v2.html`, `app/page_scheda_azienda_v1.html`, `app/agenti/a1-analytics/carica_mbs.html`, `app/agenti/a1-analytics/categorizza.html`, `app/agenti/a2-analyst/report.html`, `app/agenti/a2-analyst/dashboard_kpi.html`, `app/agenti/a3-planner/piano.html`, `app/agenti/a4-brief/brief.html`, `page_pipeline_v1.html`, `gdc_studio.html`, `app/page_hub_v1.html` (19 file in totale, tutti tranne `app/page_settings_v1.html` che era già corretto). Mockup consegnati: `mockup_a6_page_base.html` (poi applicato), `mockup_a7_page_base.html` (ancora in revisione, pubblicato anche come Artifact).

**Impatto su Vision/Pipeline:** Step 10 aggiornato — redesign grafico ora completo per home+A5+A6, A7 in mockup; registrata la nuova classe di bug (colori di stato, tema chiaro/scuro) trovata e risolta trasversalmente su tutte le pagine dell'app.

---

### [2026-11-18 12:00] Bug di coerenza post-migrazione risolti + redesign grafico home e pagina A5

**Riepilogo:** Dopo la migrazione delle schede (voce precedente), trovati e risolti due bug di coerenza nella webapp causati dal passaggio Drive→Supabase (link "Scheda" rotto, prompt/messaggi che leggevano ancora "Report A2" da una cartella Drive morta da settembre); poi completato il redesign grafico delle card A5/A6/A7 in home e, con un secondo giro di workflow mockup-first più approfondito richiesto da Gianluca, il redesign completo della pagina di A5 (navigazione, hero, tab Azioni/Lavoro/Pipeline/Config).

**Cosa è stato fatto:**

**Bug: link "Scheda" non funzionante dalla pagina azienda**
**Sintomo:** da `page_company_v2.html`, il link "📄 Scheda" non apriva nulla di utile.
**Causa:** href senza il prefisso `app/` — la pagina `page_scheda_azienda_v1.html` vive in `app/`, non in root.
**Fix applicato:** corretto l'href. Verificato.

**Bug: A5.2 e A6.1 leggono ancora "Report A2" da una cartella Drive morta**
**Sintomo:** nessun sintomo visibile finora (non ancora rieseguiti dopo settembre) — scoperto rileggendo la tab Documenti di A5 su segnalazione di Gianluca ("la tab documenti punta tutta al drive, va controllata").
**Causa:** A2 ha smesso di scrivere i report mensili su Drive a partire dallo Step 5 (ora scrive su Supabase `report_mensili`), ma i prompt di A5.2 (v10) e A6.1 (v9) non erano stati aggiornati per questo aspetto — confermato controllando la data dell'ultimo file nella cartella Drive (settembre 2026).
**Fix applicato:** A5.2 v10→v11, A6.1 v9→v10 — sezione di lettura riscritta con query SQL su `report_mensili`. Trovata e corretta anche l'eco dello stesso bug (stesso testo Drive) nei messaggi precompilati di `page_home_v25.html`, `page_company_v2.html`, `page_agent_a5_v1.html`, `page_agent_a6_v1.html`. Verificato (prompt consegnati come .docx + .md, messaggi committati e mergiati).

- Redesign card A5/A6/A7 in home (`app/page_home_v25.html`), via mockup-first su Artifact, per uniformarle allo stile già applicato ad A1-A4: rimossi descrizione/tag/stato morto, introdotto il pattern riga-con-2-pulsanti per i sotto-agenti, pillole "Pipeline Sponsorizzazioni"/"Ciclo editoriale" riposizionate dentro le rispettive bande di team, corretto il wrapping del titolo su mobile.
- Redesign completo di `page_agent_a5_v1.html`: prima passata diretta (chrome di navigazione), poi — su richiesta esplicita di Gianluca di tornare al mockup prima di proseguire — una seconda passata più profonda su `mockup_a5_page_base.html` (6 iterazioni), approvata e applicata alla pagina reale: pillola Pipeline a specchio e riposizionata, pillola notifiche rimossa, hero con A5.1/A5.2 affiancate, tab Azioni neutralizzata e raggruppata (rimosso un pulsante duplicato), tab Documenti rimossa, tab Lavoro+Pipeline unite con una spiegazione del workflow pensata per un lettore esterno, Config corretta sugli stessi residui Drive del bug sopra, JS pulito dai riferimenti morti.

**Decisioni prese:**
- Contesto: la pillola "Pipeline" nella pagina di A5 riusava la stessa forma a "freccia verso sinistra" della pillola Hub (azione "torna alla home"), ma Pipeline è un'azione in avanti.
  Decisione: creata una variante speculare dedicata (`.pill-hub-wrap-r`/`.pill-hub-r`, punta a destra) invece di riusare la forma sbagliata.
- Contesto: la pillola notifiche esiste oggi su tutte le pagine agente (A1-A7) ma la gestione reale delle notifiche è centralizzata in Impostazioni/home.
  Decisione: rimossa dalla pagina di A5 come prima applicazione.
  Da rivedere se: va ancora fatto lo stesso su A1-A4, A6, A7 — non ancora eseguito, pendente.
- Contesto: la tab Documenti di A5 puntava solo a Drive ed era percepita come ridondante (schede già raggiungibili dalla pipeline/company page, report già in A2).
  Decisione: rimossa interamente invece di solo aggiornarne i link.

**File consegnati/modificati:**
- `page_company_v2.html` — fix link Scheda, fix messaggio A5.2/A6.1.
- `app/page_home_v25.html` — redesign card A5/A6/A7, fix messaggio A5.2/A6.1.
- `page_agent_a5_v1.html` — redesign completo (nav, hero, tab Azioni/Lavoro/Config, JS).
- `page_agent_a6_v1.html` — fix messaggio A6.1, relabeling card input scheda.
- `docs/prompts/Agente5_2_auto_prompt_v10.md` → `v11.md`, `docs/prompts/Agente6_1_auto_prompt_v9.md` → `v10.md` (+ `.docx` consegnati a Gianluca).
- Mockup Artifact: `mockup_team_commerciale.html`, `mockup_home_full.html`, `mockup_a5_page_base.html`.

**Impatto su Vision/Pipeline:** Step 10 — aggiunto il criterio "bug di coerenza dalla migrazione risolti" (fatto) e tracciato separatamente il redesign grafico A5-A7 (fatto per home+A5, A6/A7 ancora da fare).

---

### [2026-11-18 07:30] Migrazione completa delle schede aziendali Drive→Supabase (38, non 16)

**Riepilogo:** La stima di 16 schede da migrare (Step 10) era sbagliata — un audit diretto della cartella Drive "Schede aziendali" ha trovato 38 sottocartelle aziendali reali, non solo le 16 tracciate dalla colonna `companies.drive_folder_scheda`. Migrate 36 su 38 nella tabella `schede_aziendali`; le 2 restanti (LiberNovo, Commerciale Teatina Srl) hanno la cartella Drive vuota — nessun DOCX mai prodotto, segnalato a Gianluca senza inventare contenuto.

**Cosa è stato fatto:**
- Corretta la stima iniziale: interrogata direttamente la cartella Drive "Schede aziendali" (`parentId`/listato tutte le sottocartelle) invece di fidarsi della colonna Supabase `drive_folder_scheda`, che risale solo a dopo il fix storico di A5.2 — le aziende create prima di quel fix non vi comparivano mai. Trovate 38 sottocartelle totali contro le 16 attese.
- Migrazione eseguita con 3 fork Claude in sequenza (ciascuno: legge il DOCX da Drive, lo convertisce in pagina HTML fedele riusando la stessa palette/font del sito, fa upsert in `schede_aziendali`, aggiorna `companies.drive_folder_scheda` per le aziende trovate solo con l'audit):
  1. Prima ondata (16 aziende già note): 14 migrate, 2 (LiberNovo, Commerciale Teatina Srl) con cartella vuota.
  2. Seconda ondata (22 aziende scoperte con l'audit): interrotta da un riavvio del container a metà — verificato via query diretta su Supabase che 12 erano già state scritte prima dell'interruzione (nessuna perdita di lavoro), poi completate le 9 rimanenti con un nuovo fork.
  3. 1 azienda (Action Italia) omessa per errore dalla lista della seconda ondata, scoperta con un controllo finale di coerenza (confronto tra l'elenco completo delle 38 cartelle e le righe effettivamente presenti in `schede_aziendali`) e migrata a mano.
- Verifica finale: `SELECT count(*) FROM schede_aziendali` → 36; controllo di coerenza che ogni company_id con una cartella Drive non vuota sia presente, confermando che le uniche 2 mancanti sono le 2 cartelle genuinamente vuote.

**Decisioni prese:**
- Contesto: la lista di 16 aziende da migrare, usata per lanciare il primo fork, si è rivelata incompleta subito dopo il lancio (segnalazione di Gianluca).
  Decisione: non fidarsi più della colonna `drive_folder_scheda` come censimento — fare un audit diretto della cartella Drive parent, trattando la lista Supabase come indizio, non come fonte di verità.
  Da rivedere se: in futuro si creano nuove aziende con cartelle scheda create fuori dal flusso standard di A5.2 (stesso rischio di disallineamento Drive/Supabase).

**File consegnati/modificati:**
- Tabella `schede_aziendali`: 36 righe (company_id, html, updated_at).
- `companies.drive_folder_scheda`: aggiornata per le 22 aziende scoperte solo con l'audit.
- `docs/documento-sessione-gdc-ia-team.md` (Step 10: corretta la stima 16→38, criterio di completamento aggiornato, nuove note).

**Impatto su Vision/Pipeline:** Step 10 — criterio di completamento sulla migrazione schede soddisfatto (36/38, le 2 restanti senza DOCX reale); resta aperta la verifica con una trattativa reale (A6.1/A6.2 su un'azienda a step 7-9) prima di considerare l'intero Step 10 completato.

---

### [2026-11-17 22:30] Team Commerciale: notifiche collegate, credenziali sorvegliate, scheda A5.2 in HTML

**Riepilogo:** Chiusa la pagina Impostazioni (Step 9: script collegati alle preferenze, cron per A2/A3/A4) e ripreso l'audit del Team Commerciale (Step 10) — chiarito che Pipeline Notify non era rotto, costruito un controllo di salute delle credenziali, corretto il buco di `agent_states` su A5.1/A5.2/A6.1, e spostata la scheda azienda di A5.2 da DOCX su Drive a pagina HTML su Supabase con export PDF on-demand (con la cascata di aggiornamenti su A6.1/A6.2 che ne consegue).

**Cosa è stato fatto:**
1. `a1_monthly.py`, `a7_followup.py`, `pipeline_notify.py`, `notify_failures.py` ora leggono `user_settings` prima di ogni push (fail-open su errore/riga mancante).
2. Nuovo `scripts/a2a3a4_watcher.py` (cron orario): rileva i completamenti di A2/A3/A4 non ancora notificati confrontando `agent_states.updated_at` con la nuova colonna `agent_states.last_notified_at`, manda la push rispettando le preferenze.
3. Verificato (RPC temporanea via `pg_net` dal database, mai esposta a GitHub Actions) che il PAT `github_repo_dispatch_pat` funziona: i 52 giorni di silenzio di Pipeline Notify erano dovuti a zero attività commerciale reale, non a un guasto.
4. Nuovo `scripts/credential_health_check.py` (cron giornaliero): testa PAT GitHub, service account Google e refresh token Gmail, scrive l'esito su `token_status`, si appoggia alla rete di sicurezza `notify_failures.py` già esistente in caso di fallimento.
5. Prompt A5.1 (v6→v7), A5.2 (v8→v9→v10) e A6.1 (v7→v8→v9) corretti per scrivere `agent_states` (`working`/`done`) — stesso pattern già in uso per A2/A3/A4.
6. Scheda azienda di A5.2: nuova tabella `schede_aziendali` (pagina HTML al posto del DOCX), tabella `scheda_pdf_requests` + trigger Postgres + `scripts/export_scheda_pdf.py` (Playwright) per l'export PDF on-demand, nuova pagina webapp `app/page_scheda_azienda_v1.html`, `page_company_v2.html` aggiornata. A5.2 (v10) scrive la scheda su Supabase; A6.1 (v9) e A6.2 (v10→v11) aggiornati per leggerla da lì invece che da Drive.
7. Aggiornato questo documento (Step 9 chiuso, Step 10 aggiornato con tutte le decisioni e i risultati dell'audit).

**Decisioni prese:**
- Contesto: "Pipeline Notify fermo da 52 giorni" sembrava un PAT scaduto/revocato (ipotesi dello Step 10 originale).
  Decisione: verificato con un test diretto dal database — il PAT funziona, il vero problema è l'assenza di attività commerciale da fine settembre, non un bug.
- Contesto: A6.1 produce un PPTX che Gianluca corregge sempre a mano prima di esportarlo in PDF.
  Decisione: non convertito in HTML come la scheda di A5.2 — l'editing manuale in PowerPoint è un passaggio voluto, non solo una scomodità di formato.
  Alternative scartate: stesso trattamento HTML+export della scheda — scartata perché toglierebbe la possibilità di correggere a mano.
- Contesto: A6.2 (conversazione continuativa su una trattativa, spesso con più conversazioni attive insieme) non ha un vero momento "done".
  Decisione: nessuna segnalazione di stato su `agent_states` per A6.2 — confermato da Gianluca, il pallino sarebbe comunque poco significativo per questo agente.
  Alternative scartate: segnalazione a tempo fisso (es. "working" per N ore dopo ogni scrittura) — scartata per complessità non giustificata da un indicatore puramente cosmetico.
- Contesto: cambiare il formato di output di A5.2 impatta chi legge quell'output.
  Decisione: aggiornati anche A6.1 e A6.2 nella stessa sessione, non solo A5.2 — altrimenti si sarebbero rotti al primo uso dopo il cambio.
- Da rivedere se: le 16 schede già prodotte su Drive (prima del cambio) non sono ancora state migrate su Supabase — se Gianluca riprende una trattativa già aperta prima che la migrazione sia fatta, A6.1/A6.2 non troverebbero la scheda. Prossimo passo esplicito.

**File consegnati/modificati:**
- Script: `scripts/a2a3a4_watcher.py` (nuovo), `scripts/credential_health_check.py` (nuovo), `scripts/export_scheda_pdf.py` (nuovo), `a1_monthly.py`/`a7_followup.py`/`pipeline_notify.py`/`notify_failures.py` (gate su `user_settings`).
- Workflow: `.github/workflows/a2a3a4_watcher.yml`, `credential_health_check.yml`, `export_scheda_pdf.yml` (nuovi); `notify_failures.yml` aggiornato con i tre nuovi nella watch-list.
- Webapp: `app/page_scheda_azienda_v1.html` (nuova), `page_company_v2.html` (bottone Scheda + messaggi di lancio aggiornati), `app/page_settings_v1.html` (nuovo workflow in tab Automazioni).
- Supabase: tabelle `schede_aziendali`, `scheda_pdf_requests`, colonna `agent_states.last_notified_at`, bucket Storage `schede-pdf`, funzioni `notify_scheda_pdf_requested`, `submit_github_pat_healthcheck`, `get_http_response_status`.
- Prompt (consegnati a Gianluca in .docx, salvati in `docs/prompts/` in .md): Agente 5.1 v7, Agente 5.2 v10, Agente 6.1 v9, Agente 6.2 v11.

**Impatto su Vision/Pipeline:** Step 9 chiuso; Step 10 aggiornato con l'esito completo dell'audit e il lavoro di migrazione ancora aperto.

---

### [2026-11-17 13:45] Home: pillole a icona, fix scroll calendario, saga del glitch header su iOS

**Riepilogo:** Dopo la pagina Impostazioni, Gianluca ha chiesto alcune modifiche grafiche alla home (pillola notifiche a icona, riordino pillole, logo centrato con dinamica di scroll) — la parte sul logo ha richiesto tre tentativi prima di risolvere un bug di rendering su iOS, scoperto solo su dispositivo reale e non riproducibile in locale.

**Cosa è stato fatto:**
1. Pillola "Attiva notifiche" trasformata da pillola con testo a cerchio a icona (stesso stile di quello delle Impostazioni): campanella piena e colore neutro quando le notifiche sono attive su questo dispositivo, campanella barrata e colore rosso quando non lo sono.
2. **Bug: pannello eventi del calendario non scorrimento con molti eventi nello stesso giorno**
   - **Sintomo:** con molte attività nello stesso giorno, non si riusciva a scorrere la lista eventi nel popup calendario — lo scroll "passava attraverso" muovendo la pagina sotto invece del pannello.
   - **Causa:** il popup non aveva un'altezza massima né un meccanismo di scroll indipendente per il pannello eventi.
   - **Fix applicato:** pannello eventi reso scrollabile al suo interno (`overflow-y:auto`, `overscroll-behavior:contain`) e scroll della pagina bloccato (`body.style.overflow='hidden'`) finché il popup resta aperto. Verificato con 25 eventi finti nello stesso giorno via browser headless.
3. Header riprogettato: logo GDC ingrandito (40→54px) e centrato, "Tutti i sistemi attivi" e pillola calendario ai due lati, con una dinamica di rimpicciolimento/dissolvenza del logo scorrendo verso il basso.
4. **Bug: glitch di rendering sull'header su iOS (3 tentativi prima della soluzione)**
   - **Sintomo:** su iPad reale, in modalità standalone con status bar `black-translucent`, scorrendo la home si vedeva per un istante il contenuto della pagina passare in una fascia sopra la riga di stato, come se l'header non coprisse correttamente quello spazio — segnalato da Gianluca con screenshot. Non riproducibile in Chromium headless (specifico di WebKit/iOS).
   - **Causa:** non accertata nei dettagli interni di WebKit, ma empiricamente legata a qualunque header "ancorato" (sia `position:sticky` che `position:fixed` con spacer) in combinazione con lo scroll e la status bar translucida in modalità standalone.
   - **Fix applicato (tentativi, in ordine):**
     1. Animare il logo con `transform`/`opacity` invece di `height` dentro l'header `sticky` (per evitare reflow di layout ad ogni frame di scroll) — non ha risolto.
     2. Sostituire `sticky` con `position:fixed` + uno spacer sotto per mantenere lo spazio nel flusso — non ha risolto nemmeno questo (stesso sintomo riconfermato da Gianluca con screenshot).
     3. **Risolto** — su proposta di Gianluca: il contenuto di questa fascia non è essenziale da tenere sempre in vista, quindi niente ancoraggio. Header tornato a `position:static`, scorre via con il resto della pagina come ogni altro elemento — eliminando categoricamente la possibilità del bug (nessun layer fisso/incollato con cui lo scroll possa interferire). Il logo mantiene l'animazione di rimpicciolimento mentre esce dallo schermo, ora puramente cosmetica.
5. Pillola calendario e "Tutti i sistemi attivi" riposizionate una seconda volta su richiesta di Gianluca: calendario di nuovo in alto a destra, stato a sinistra, logo al centro — layout finale confermato corretto.

**Decisioni prese:**
- Contesto: dopo due tentativi falliti di tenere l'header ancorato in cima durante lo scroll senza il glitch su iOS.
- Decisione: non ancorare affatto questa fascia — torna in flusso normale, scorre via con il resto della pagina.
- Alternative scartate: `position:sticky` con animazione via `height` (bug), `position:sticky` con animazione via `transform`/`opacity` (bug persiste), `position:fixed` + spacer sincronizzato via scroll (bug persiste comunque).
- Da rivedere se: in futuro servisse davvero un header sempre visibile, andrebbe approfondita la causa specifica in WebKit (es. `viewport-fit=cover` + `env(safe-area-inset-top)`, o rinunciare a `black-translucent`) — non indagato oltre in questa sessione.

**File consegnati/modificati:**
- `app/page_home_v25.html`

**Verifiche fatte:** parser HTML Python (nessun mismatch) e `node --check` dopo ogni modifica; verifica funzionale con browser headless Playwright ad ogni iterazione (posizione calcolata dell'header, valori di transform/opacity campionati durante lo scroll, popup calendario testato con 25 eventi finti nello stesso giorno). Il glitch specifico di iOS è stato confermato/escluso solo da Gianluca su dispositivo reale, non riproducibile in Chromium headless.

### [2026-11-17 11:20] Pagina Impostazioni: Notifiche granulari, Dispositivi, Automazioni, Aspetto, Account

**Riepilogo:** Dopo l'audit del team commerciale (vedi voce precedente), Gianluca ha chiesto di dare priorità a una pagina Impostazioni mai realizzata finora, partendo dal tab Notifiche; costruita con mockup iterativo e poi implementata nella webapp reale con 5 tab.

**Cosa è stato fatto:**
1. Proposte di contenuto per la pagina (oltre alle Notifiche: Dispositivi, Stato automazioni, Aspetto, Account) — accettate da Gianluca.
2. Notifiche: deciso un interruttore generale ("pausa" software) + sottomenù con ogni notifica singola, ricavando l'elenco reale dal codice (non inventato): A1/A2/A3/A4 completati, avvisi MBS, i 13 step della pipeline commerciale (etichettati con chi li esegue), A7 follow-up pronto/testo mancante, errore automazione.
3. Punto architetturale sollevato e condiviso con Gianluca: A2/A3/A4 girano nella sessione Claude Code (non via script GitHub Action) — per le loro notifiche push, deciso di usare in futuro un cron watcher (stesso pattern solido di pipeline_watcher.py) invece di estendere la catena trigger Postgres→pg_net→PAT→repository_dispatch già fragile (Step 10) — non ancora implementato.
4. 1 mockup (pagina completa a 5 tab), poi una correzione richiesta da Gianluca: la pillola "Home" doveva avere la stessa punta a sinistra/tonda a destra già usata in `page_home_v25.html` (clip-path a doppio livello), non una pillola arrotondata semplice.
5. Implementata la pagina reale `app/page_settings_v1.html`: Notifiche e Aspetto persistiti su Supabase (tabella `user_settings`, mai usata finora, già con la forma giusta e RLS per-utente — upsert via `on_conflict=user_id`); Dispositivi con dati reali da `push_subscriptions` (attiva/disattiva/rimuovi); Automazioni con stato reale (ultima esecuzione + esito) letto dalla API pubblica di GitHub Actions per ciascun workflow (il repo è pubblico, nessun token necessario); Account con email reale dell'utente autenticato e logout.
6. Aggiunto un pulsante a icona (ingranaggio) sulla home, accanto alla pillola "Attiva notifiche", come punto di accesso alla nuova pagina.
7. Domanda di Gianluca su un possibile account multi-utente a permessi limitati (es. SMM) — risposta data (fattibile via ruoli + RLS, ma oggi tutta la webapp assuma un solo utente quindi è un retrofit, non un'aggiunta semplice), annotata per quando vorrà riprenderla, nessuna implementazione.

**Decisioni prese:**
- Contesto: come far rispettare le nuove preferenze di notifica dal lato server.
- Decisione: gli script Python non sono stati ancora modificati per leggere `user_settings` prima di inviare una push — le preferenze oggi sono salvate ma ignorate. È il prossimo passo esplicito dello Step 9.
- Alternative scartate: estendere la catena pg_net/PAT/repository_dispatch anche alle notifiche A2/A3/A4 — scartata perché è la stessa catena già trovata silenziosamente rotta nello Step 10.

**File consegnati/modificati:**
- `app/page_settings_v1.html` (nuovo)
- `app/page_home_v25.html` (aggiunto pulsante ingranaggio nel pill-row)
- mockup `mockup-settings-v1.html` (v1 e v2 con correzione pillola)

**Verifiche fatte:** parser HTML Python su entrambi i file reali (nessun mismatch), `node --check` sugli script estratti (validi), controllo esistenza di tutti i link relativi (`page_login_v6.html`, `sw.js`, `manifest.json`, icone).

### [2026-11-16 23:00] Audit workflow Team Commerciale (A5-A7)

**Riepilogo:** Su richiesta di Gianluca di iniziare a lavorare sul team commerciale, eseguito un controllo del workflow reale (script + GitHub Actions + dati Supabase) prima di qualsiasi modifica — trovata una fragilità seria e concreta, non ancora risolta.

**Cosa è stato fatto:**
1. Letto per intero il codice reale di `a7_gmail_drafter.py`, `a7_followup.py`, `pipeline_watcher.py`, `pipeline_notify.py`, `notify_failures.py` e i rispettivi workflow GitHub Actions — architettura generale giudicata solida e ben documentata.
2. **Bug: "Pipeline Notify" silenziosamente fermo da 52 giorni**
   - **Sintomo:** nessuna notifica push/attività per avanzamenti della pipeline commerciale da fine settembre, scoperto confrontando la storia reale delle run GitHub Actions: Pipeline Watcher ha 1138 run regolari fino a oggi, ma Pipeline Notify non esegue dal 25/09 (52 giorni).
   - **Causa:** non accertata con certezza. Il meccanismo (trigger Postgres `notify_company_step_change` → `pg_net` → PAT GitHub letto da Supabase Vault → `repository_dispatch`) non controlla mai l'esito della chiamata HTTP — se il PAT è scaduto o revocato, la chiamata fallisce e non lo sa nessuno, perché non viene nemmeno creata una run GitHub da cui `notify_failures` potrebbe accorgersene. Coincidenza non chiarita: nello stesso periodo (da fine settembre) anche il resto della pipeline commerciale risulta fermo (nessun cambio di step, manuale o automatico).
   - **Fix applicato:** nessuno — in attesa di conferma da Gianluca se ha notato o no le notifiche mancanti, per capire se il PAT va rigenerato o se è solo assenza di eventi.
3. Trovato un bottleneck di processo (non un bug): 6 aziende bloccate allo step 3 (media kit in attesa di revisione ed export PDF da parte di Gianluca) da luglio/inizio settembre — rilevato correttamente da Pipeline Watcher ogni ora, semplicemente in attesa della sua revisione manuale.
4. Segnalate pagine `page_agent_a5_v1.html`/`a6`/`a7`/`page_company_v2.html` ancora al vecchio pattern (pre-redesign A1-A4) come candidate per un lavoro successivo, e un avviso minore del linter di sicurezza Supabase sulla funzione trigger (eseguibile come RPC da `anon`/`authenticated`, probabilmente innocuo ma da chiudere con un `REVOKE`).

**File consegnati/modificati:** nessuno — solo diagnosi, nessuna modifica al codice in questa voce.

**Impatto su Vision/Pipeline:** aggiunto lo Step 10 "Audit e miglioramento Team Commerciale (A5-A7)" alla Pipeline.

### [2026-11-16 22:10] Home: stacco visivo Team Social / Team Commerciale

**Riepilogo:** Dopo aver verificato dalla webapp il lavoro di redesign A1-A4, Gianluca ha chiesto di dare "un po' di stacco" in home tra il gruppo A1-A4 (team social) e A5-A7 (team commerciale), rimasti finora in un'unica lista senza alcuna separazione visiva. Risolto con una cornice neutra concentrica alle card, dopo tre iterazioni di mockup.

**Cosa è stato fatto:**
1. **3 proposte iniziali** in mockup: etichetta con riga, divisore con barretta colorata, fasce di sfondo colorate. Gianluca ha scelto le fasce come idea.
2. **Problema di design individuato da Gianluca**: una tinta fissa sulla fascia (es. blu/sabbia) competerebbe con i colori che bordo e logo-box delle card già usano per lo stato reale dell'agente (verde=completato, rosso=in coda, sabbia=in corso, azzurro=inattivo) — rischio di sembrare essa stessa uno stato/errore. Rifatto il mockup con i veri colori/card della webapp per ragionarci sopra, e proposte 3 varianti tutte neutre (nessuna tinta nuova): fascia rialzata (bianco su carta), fascia incassata (ombra interna leggera), solo cornice tratteggiata.
3. **Scelta: variante incassata ("Opzione B"), con due correzioni richieste da Gianluca**: la cornice doveva essere concentrica alle card (padding uguale su tutti i lati — nella prima versione era asimmetrico, 20/10/10/12, per via della vecchia etichetta in flusso) e la scritta andava spostata fuori dal perimetro del bordo, in linea con il quadrato del logo delle card, con un "taglio" nel bordo dove passa il testo (pattern legend/fieldset).
4. **Implementato sulla home reale**: cornice con padding uniforme 16px, etichetta posizionata matematicamente (16 padding banda + 2 bordo card + 8 padding logo-col = 26px) invece che a occhio, sfondo dell'etichetta = `var(--carta)` per mascherare il bordo dietro il testo in entrambi i temi senza bisogno di regole dark-mode separate.

**Decisioni prese:**
- Contesto: come separare visivamente due gruppi di agenti su una home dove ogni card cambia già colore (bordo + logo-box) in base al proprio stato live.
- Decisione: cornice neutra (solo bordo, nessun fill/tinta) con etichetta in stile "legend", concentrica alle card.
- Alternative scartate: fasce con sfondo colorato fisso (rischio di confondersi con i colori di stato); etichetta dentro la cornice in flusso (rompe la concentricità, richiede padding asimmetrico).

**File consegnati/modificati:**
- `app/page_home_v25.html` — aggiunta `.team-band`/`.team-band-lbl`, card A1-A4 e A5-A7 wrappate rispettivamente in "Team Social" e "Team Commerciale"
- `/tmp/.../scratchpad/mockup-home-team-split.html`, `-v2.html`, `-v3.html` — le tre iterazioni di mockup (etichette iniziali → fasce neutre con toggle chiaro/scuro → cornice concentrica rifinita)

**Verifiche fatte:** parser HTML Python (`html.parser`) sull'intero file per verificare che l'inserimento dei due wrapper `<div class="team-band">` non abbia sbilanciato la struttura dei tag — nessun mismatch.

---

### [2026-11-16 21:40] Pagina Agente A4 ridisegnata — rimosso il vecchio flusso Drive/claude.ai, completata la catena A1→A4

**Riepilogo:** Stesso trattamento (audit → mockup → allineamento → codice reale) applicato a tutta la catena editoriale A1-A4 in questa sessione, qui su A4 — l'ultimo agente rimasto. A differenza di A2/A3, il prompt di A4 (v8) non menzionava esplicitamente il passaggio a una sessione Claude Code dedicata, quindi prima di rimuovere il pulsante "Apri progetto Claude A4" è stato chiesto esplicitamente a Gianluca.

**Cosa è stato fatto:**
1. **Audit preliminare**: letta tutta la pagina e confrontata con il prompt reale di A4 (v8) e con `brief.html` (già corretto, legge da `report_mensili` come `piano.html`/`report.html`).
2. **Domanda di chiarimento esplicita**: il prompt v8 dice ancora "ogni mese apriamo una conversazione dedicata nel Progetto", senza il changelog di spostamento a Claude Code che invece A2 (v18) e A3 (v13) hanno esplicitamente. Gianluca ha confermato: A4 fa parte della stessa sessione Claude Code dedicata lanciata dalla pillola "Ciclo editoriale mensile" in home (A2→A3→A4 in sequenza nella stessa conversazione).
3. **Rimosso l'intero vecchio flusso**: popup "Copia messaggio precompilato" + pulsante "Apri progetto Claude A4" (claude.ai/project) + pulsanti "Cartella Drive A3 — Piani" e "Cartella Drive A4" — nessun punto di lancio sulla pagina stessa, coerente con la risposta di Gianluca.
4. **Bug corretto**: la pagina diceva "A4 non scrive su activity_log al momento, e non salva mese/numeri come A1/A2" — falso dalla v5 (activity_log) e v8 (mese su agent_states).
5. **Dipendenze rese reali**: piano A3 mese corrente + mese precedente, report A2 degli ultimi due mesi (qui il doppio mese resta corretto — il prompt lo richiede esplicitamente come OBBLIGATORIO, a differenza della semplificazione fatta per A3) — ora controlli reali su `report_mensili` invece di "non verificabile qui".
6. **Posizione nel flusso aggiornata**: A4 resta l'ultimo della catena A1→A4, nessuna dipendenza o segnale verso un agente successivo (diversamente da A1→A2→A3 che si passano il testimone).
7. **Documenti**: ora mostra il render live degli ultimi brief generati (`report_mensili`, agente='a4') con link a `brief.html?mese=...`, più l'input diretto al Google Sheet A1 (unico input non ancora migrato su Supabase, confermato dal prompt).
8. **Coerenza visiva con A1/A2/A3**: pillole Home/Notifiche a punta, titolo unico colorato per stato, `.sys-mini`, tab ridotte da 5 a 4. Mantenuta intatta l'animazione JS-driven dell'icona A4 (disegno del documento + barre + cursore che scrive, `startA4Anim`/`stopA4Anim`), diversa dalle animazioni CSS di A1/A3 — non toccata perché non superata, solo funzionalità reale.

**File consegnati/modificati:**
- `app/agenti/a4-brief/page_agent_a4_v1.html` — riscritto (pillole/titolo/tab/logica reale), animazione icona A4 preservata
- `/tmp/.../scratchpad/mockup-a4-agent.html` — mockup approvato, base per il file reale

**Verifiche fatte:** `node --check` sullo script estratto — OK; grep per residui del vecchio flusso (msgOverlay, openMsg/closeMsg/copyMsg, claude.ai/project, Cartella Drive A3/A4, .docx, present_files, lg-cta, lg-maker, back-btn, system-bar) — nessuno trovato; tutti i link relativi (brief.html, home, login, sw.js) verificati esistenti sul filesystem.

**Impatto su Vision/Pipeline:** con A4 ridisegnata, la catena editoriale mensile A1→A2→A3→A4 che la Vision cita come "presa in mano da Claude Code" è ora completa su tutti e quattro gli agenti — stesso linguaggio visivo, stessa sessione Claude Code dedicata, stesso output HTML su Supabase per tutti.

---

### [2026-11-16 21:05] Pagina Agente A3 ridisegnata — rimosso il vecchio flusso PPTX/Drive/claude.ai

**Riepilogo:** Stesso trattamento (audit → mockup → allineamento → codice reale) già applicato ad A1 e A2, ora su A3 — stessa categoria di problema di A2: la pagina descriveva un flusso di lavoro completamente superato.

**Cosa è stato fatto:**
1. **Audit preliminare**: letta tutta la pagina e confrontata con il prompt reale di A3 (v13) e con `piano.html` (già aggiornato, legge correttamente da Supabase). Confermato che il prompt v13 ha già completato la stessa transizione di A2 (v13: output HTML su Supabase invece di PPTX, input Report-A2/piano-precedente da Supabase invece che da Drive, auto-segnalazione su agent_states, scrittura su activity_log dalla v11).
2. **Rimosso l'intero vecchio flusso**: popup "Copia messaggio precompilato" (con build del messaggio via `buildMsg()`) + pulsante "Apri progetto Claude A3" (claude.ai/project) + due pulsanti "Cartella Drive A2 — Report" e "Cartella Drive A3" come output — tutti sostituiti dal riferimento alla sessione Claude Code dedicata lanciata dalla pillola "Ciclo editoriale mensile" in home (stesso punto d'ingresso di A2, nessun pulsante di lancio sulla pagina stessa).
3. **Bug corretto**: la pagina diceva "A3 non scrive su activity_log al momento" — non vero dalla v11. Il tab Panoramica ora mostra l'attività reale da `activity_log`.
4. **Dipendenze rese reali**: "Report A2 Mm2" e "Piano A3 Mm1" erano segnate "Non verificabile qui" (placeholder hardcoded) — ora sono controlli reali su `report_mensili` (agente+mese esatti), più il controllo calendario BPT già reale (ereditato dalla correzione fatta in questa stessa sessione su `bpt_calendars`).
5. **Semplificazione segnalata esplicitamente a Gianluca**: il vecchio messaggio precompilato citava due mesi di report A2 (Mm1 e Mm2), ma il prompt v13 parla di un solo "report del mese chiuso" (opzionale) — ridotto a un solo riferimento, in attesa di eventuale correzione se serve ancora il doppio mese.
6. **Documenti**: ora mostra il render live degli ultimi piani generati (`report_mensili`, agente='a3') con link a `piano.html?mese=...`, più l'input diretto al Google Sheet A1 (confermato obbligatorio dal prompt, letto in parallelo da A3 oltre che da A2).
7. **Coerenza visiva con A1/A2**: pillole Home/Notifiche a punta, titolo unico colorato per stato (prima diviso in "Agente 3"/"Planner"), `.sys-mini` al posto della vecchia `.system-bar`, tab ridotte da 5 a 4 (Panoramica unisce Azioni+Run).
8. **Correzione richiesta da Gianluca**: nel mockup il logo GDC in alto a sinistra era un placeholder testuale ("GDC") invece del vero SVG animato — corretto nel file reale, riportato l'SVG master (G/D/C/STUFF/linee) con l'animazione a comparsa sequenziale, identico a quello di A1/A2/home.

**File consegnati/modificati:**
- `app/agenti/a3-planner/page_agent_a3_v1.html` — riscritto (pillole/titolo/tab/logica reale), con il vero logo GDC animato
- `/tmp/.../scratchpad/mockup-a3-agent.html` — mockup iterato e approvato, base per il file reale (non toccato dopo l'approvazione tranne per il fix del logo, fatto direttamente sul file reale)

**Verifiche fatte:** `node --check` sullo script estratto — OK; grep per residui del vecchio flusso (msgOverlay, openMsg/closeMsg/copyMsg, buildMsg, claude.ai/project, Cartella Drive A2/A3, .pptx, lg-cta, lg-maker, back-btn, system-bar) — nessuno trovato; tutti i link relativi (piano.html, home, login, sw.js) verificati esistenti sul filesystem.

---

### [2026-11-16 20:30] BPT Calendar: bug reale trovato (torneo dicembre mancante) e script riscritto senza Playwright

**Riepilogo:** Gianluca ha segnalato che `bpt_calendar.yml` "non funziona" (sospettava fosse fragile fin da quando l'ha costruito) — indagine confermata: il workflow non falliva mai su GitHub Actions, ma produceva dati sbagliati per un bug nei nomi dei campi letti dall'API, e nel frattempo la FIVB sta sostituendo il Beach Pro Tour con una nuova serie (FIVB Beach World Series, dal 2026/2027), che avrebbe rotto in silenzio il filtro per livello usato finora. Riscritto lo script su una fonte dati migliore (fivbeach.com) e con un criterio di filtro più robusto a questo cambiamento.

**Cosa è stato fatto:**

**Bug: calendario BPT dà sempre "0 tornei" di fatto, anche quando non è vero**

**Sintomo:** le tre run automatiche più recenti (sett./ott./nov. 2026) hanno tutte scritto "Nessun torneo BPT nel mese" su Supabase, senza mai un errore su GitHub Actions (conclusion sempre "success", step da ~3 secondi).

**Causa:** diagnosi in due parti.
1. Per ottobre e novembre 2026 lo 0 era corretto (nessun torneo BPT in quei mesi secondo il calendario reale). Ma per **dicembre 2026 era sbagliato**: esiste un torneo (Beach Elite Itapema, Brasile, 9–13 dic) con Cottafava/Dal Corso iscritti nel tabellone principale (verificato scraping diretto la pagina iscritti) — pubblicato/confermato sull'API BPT *dopo* la run del 2 novembre, quindi mai visto dal workflow (nessun meccanismo di ri-controllo dopo il run mensile).
2. Bug strutturale indipendente, nel codice: lo script cercava i campi `location`/`city`/`venue`/`country` e `title`/`name` nel JSON di `en.volleyballworld.com`, ma l'API reale usa `destination` (stringa unica "Città, Paese") e il campo `name` è uno slug tecnico, non un nome leggibile. Risultato silenzioso: "Luogo:" sempre vuoto nel testo generato per A3, e di conseguenza anche il calcolo oltreoceano/vicina sempre sbagliato (dipende dal testo location, sempre vuoto) — confermato sull'unica riga reale già salvata in passato (Rio de Janeiro, agosto 2026: Luogo vuoto, trattato come trasferta "vicina" invece che oltreoceano).

**Fix applicato:** riscritto `scripts/bpt_calendar.py` da zero su una fonte diversa, **fivbeach.com**, verificata più affidabile: ogni pagina (calendario e singolo torneo) incorpora un blob JSON già pulito nell'HTML statico (attributo `data-page`, Inertia.js) — leggibile con una normale richiesta HTTP, **senza alcun bisogno di Playwright/browser**, né per il calendario né per la lista iscritti (prima richiedeva Playwright per cercare "Dal Corso" testualmente in una tabella HTML). Rimosso Playwright dal workflow (installazione Chromium e dipendenze di sistema, ~35s di setup) e dai requirements. Rimossi anche `GOOGLE_CREDENTIALS`/`DRIVE_FOLDER_A3`: erano letti ma il salvataggio su Drive non veniva mai chiamato da `main()` — dead code, il testo è sempre stato letto dalla webapp solo da Supabase.

**Decisioni prese:**
- Contesto: Gianluca ha chiesto se, visto il periodo di transizione (nuova FIVB Beach World Series che sostituisce il Beach Pro Tour tra fine 2026 e il 2027), il cambio di struttura dei tornei avrebbe potuto rompere di nuovo il sito/script.
- Decisione: il nuovo script **non filtra più per tier/tipo di torneo** (Elite16, Challenge, ecc. — la tassonomia che la federazione sta proprio cambiando), ma scarica tutti i tornei maschili pro-rilevanti (esclude solo tour nazionali/giovanili/multisport, categorie strutturalmente diverse) nella finestra di viaggio del mese target, e verifica l'iscrizione effettiva di Dal Corso/Cottafava torneo per torneo. Verificato in pratica: il primo evento della nuova serie (Beach World Series Dubai, gen. 2027, classificato con tier/tipo nuovi "major"/"World Series") viene correttamente intercettato e controllato dal nuovo script — un filtro per tier vecchio l'avrebbe saltato in silenzio.
- Alternative scartate: tenere il filtro per tier/tipo aggiornandolo ai nuovi nomi — scartata perché si romperebbe di nuovo al prossimo cambio federale (è già successo una volta).
- Da rivedere se: il volume di tornei "non esclusi" dovesse crescere troppo (oggi ~200/anno su 3 anni scaricati, verifica iscritti solo su quelli in finestra — qualche richiesta HTTP in più per run, nessun problema di tempo osservato).

**File consegnati/modificati:**
- `scripts/bpt_calendar.py` — riscritto (fonte fivbeach.com, niente Playwright, filtro per finestra-viaggio + verifica iscritti invece che per tier)
- `.github/workflows/bpt_calendar.yml` — rimossi step installazione Playwright/Chromium e secret Drive non più usati; `timeout-minutes` abbassato da 20 a 10
- `scripts/requirements.txt` — rimosso `playwright==1.44.0`

**Verifiche fatte:** `python3 -m py_compile` sullo script; dry-run locale (mock del client Supabase, nessuna scrittura reale) per dicembre 2026 → trova correttamente 1 torneo (Itapema), testo generato con "Luogo: Itapema, Brazil" e trasferta "oltreoceano (+6gg anticipo)" corretti; dry-run per novembre 2026 → correttamente 0 tornei (nessuna regressione); dry-run per gennaio 2027 → intercetta e verifica Beach World Series Dubai (nuova serie), Dal Corso non trovato (dato reale, non assunto).

**Nota per il prossimo passo:** la riga `bpt_calendars` di dicembre 2026 su Supabase è ancora quella vecchia e sbagliata (0 tornei) — va rigenerata lanciando il workflow con `bpt_target_month=2026-12` ora che il fix è su `main`. Non ancora fatto in questa sessione: in attesa di conferma di Gianluca prima di toccare il dato live.

---

### [2026-11-16 19:53] Pagina Agente A2 ridisegnata — rimosso l'intero vecchio flusso PPTX/Drive/claude.ai

**Riepilogo:** Stesso trattamento (audit → mockup → allineamento → codice reale) applicato ad A1 nelle sessioni precedenti, ora su A2 — ma qui il problema non era solo cosmetico: la pagina descriveva un flusso di lavoro completamente superato (report in PPTX consegnato via claude.ai/project e caricato a mano su Drive/Slides), mentre da tempo A2 scrive il report come pagina HTML direttamente su Supabase tramite la sessione Claude Code dedicata.

**Cosa è stato fatto:**
1. **Audit preliminare**: letta tutta la pagina e confrontata con il prompt reale di A2 (v20) e con `report.html`/`dashboard_kpi.html` (già aggiornati, letture da Supabase corrette) per distinguere cosa era davvero superato da cosa era solo da uniformare visivamente ad A1.
2. **Rimosso l'intero vecchio flusso**: popup "Copia messaggio precompilato" (con un messaggio che citava ancora Drive e un numero di versione del prompt vecchio) + pulsante "Apri progetto Claude A2" (claude.ai/project) + pulsante "Cartella Drive A2" come output — tutti sostituiti dal riferimento alla sessione Claude Code dedicata già in uso da Step 8 (lanciata dalla pillola "Ciclo editoriale mensile" in home, non più da questa pagina).
3. **Bug corretto**: la pagina diceva "A2 non scrive su activity_log al momento" — non vero da diverse versioni del prompt (v13+). Il tab Panoramica ora mostra l'attività reale da `activity_log`.
4. **Tab Documenti riscritta**: da nomi di file Slides inesistenti ("report_GDC_[mese]_[anno]") a un render live degli ultimi report da `report_mensili`, con link diretto a `report.html?mese=...`.
5. **Tab Lavoro**: "Procedura manuale" (6 passaggi del vecchio flusso: copia messaggio → genera pptx → scarica → carica su Drive → conversione Slides → aggiorna Supabase a mano) sostituita da "Cosa fa" con gli step reali (apertura sessione dedicata, lettura del documento di sessione e dell'ultimo prompt, gate di categorizzazione, lettura Sheet A1, scrittura diretta su Supabase, activity_log + stato).
6. **Tab Config**: tolte 3 righe "Dipendenze" placeholder del vecchio flusso ("Drive accessibile"/"progetto Claude.ai configurato"/"conversione Google attiva", tutte "Non verificabile qui"), aggiunta una dipendenza reale — "Categorizzazione completata" — con la stessa query già usata per il gate di A1/home.
7. **Coerenza visiva con A1**: pillole header (Home a punta + Notifiche, tolto il doppio Home+Hub), titolo hero unico con colore dinamico sullo stato, badge tipo neutro ("🤖 Claude Code" invece di "☁️ Claude.ai" verde), mini-indicatore al posto della vecchia system-bar.
8. **Richiesta di Gianluca in revisione**: dare più risalto al pulsante "Report mensili" — spostato per primo nella lista Azioni (prima era terzo, dopo Dashboard KPI e Google Sheet).
9. Ripristinata la logica reale (guard di autenticazione + fetch Supabase vere) dopo il giro di mockup, che usava dati finti per il solo scopo di revisione visiva.

**File consegnati/modificati:** `app/agenti/a2-analyst/page_agent_a2_v3.html` (riscritta).

**Verifiche fatte:** sintassi JS (`node --check`), controllo che tutti i link relativi (`report.html`, `dashboard_kpi.html`, `../../page_home_v25.html`, `../../../page_login_v6.html`, `../../../sw.js`) risolvano a file reali, nessun residuo di codice/CSS morto legato agli elementi rimossi (verificato via grep).

**Impatto su Vision/Pipeline:** nessuno sui macro-step — stesso filone di redesign dello Step 6, qui esteso alla pagina di A2. Prossimo passo naturale: A3 e A4 con lo stesso approccio.

---

### [2026-11-16 19:36] Pulsante Categorizza nella scheda A1 (home) + gate su "Apri sessione" del ciclo editoriale

**Riepilogo:** Chiusa la richiesta di portare la categorizzazione post anche in home — non come pillola header (prima proposta, scartata da Gianluca) ma come terzo pulsante nella scheda A1 — e aggiunto un gate di cliccabilità sul pulsante "Apri sessione" del ciclo editoriale.

**Cosa è stato fatto:**
1. **Pulsante "Categorizza" nella scheda A1**: la griglia Azioni di A1 era già definita a 3 colonne nel CSS (`.actions`), solo forzata a 2 da uno style inline aggiunto nel redesign precedente — tolto l'override, aggiunto il terzo pulsante senza toccare A2-A4 (che usano la stessa classe CSS). Rosso (`lg-primary`) con badge numerico in alto a destra quando ci sono post da categorizzare, **verde** (`lg-done`, non neutro/grigio come nella prima proposta — richiesto da Gianluca) quando il conteggio è zero. Stessa query già usata in `categorizza.html`/pagina A1 (`categoria_primaria is null`), un'unica fetch condivisa anche con il gate sotto.
2. **Gate sul pulsante "Apri sessione"** (ciclo editoriale): discussa con Gianluca la sua proposta di bloccarlo finché non sono pronti MBS + categorie + dati di A1 Monthly. Ho controllato il prompt di A2 (v20) prima di rispondere: A2 è scritto apposta per gestire l'assenza di repost come caso normale (badge "n.d." su reach/ER, sezione "Repost — Metriche Volume" solo se presenti), non un dato bloccante — l'MBS è un arricchimento facoltativo, non un prerequisito. Proposto di bloccare solo su **A1 completato** (stato `done` su `agent_states`) **e categorizzazione completa** (conteggio pendenti a zero), escludendo l'MBS. Gianluca ha confermato. Il pulsante parte disabilitato di default (stesso pattern dei pulsanti "Vedi report/piano/brief") finché entrambe le condizioni non sono confermate da Supabase.

**Decisioni prese:**
- Contesto: dove mettere il pulsante di categorizzazione in home — la prima proposta (pillola nell'header, accanto a Hub/Notifiche) è stata scartata da Gianluca a favore dell'inserimento diretto nella scheda A1.
- Decisione: terzo pulsante nella griglia Azioni di A1, non una pillola separata in header.
- Decisione: il gate su "Apri sessione" copre A1-completato e categorizzazione, non l'MBS — motivato dal comportamento reale di A2 verificato nel suo prompt, non da preferenza estetica.
- Alternative scartate: pillola header con Notifiche+Categorizza affiancate (primo mockup, mostrato ma non approvato); includere l'MBS nel gate del ciclo editoriale (proposta iniziale di Gianluca, rivista dopo la verifica sul prompt A2).

**File consegnati/modificati:** `app/page_home_v25.html` (modificato: terzo pulsante Categorizza in `#actions-a1`, badge `.cat-count`, funzione `loadCategorizePending()`, gate `updateCicloGate()` agganciato sia a `loadStates()` — stato A1 — sia alla nuova fetch del conteggio pendenti, pulsante `#cicloOpenBtn` disabilitato di default).

**Verifiche fatte:** sintassi JS (`node --check` sullo script estratto), controllo che `agenti/a1-analytics/categorizza.html` risolva correttamente dal path della home.

**Impatto su Vision/Pipeline:** nessuno sui macro-step — stesso filone di pulizia/redesign dello Step 6, qui tornato sulla home dopo il giro sulla pagina A1.

---

### [2026-11-16 18:22] Pagina Agente A1 ridisegnata — pillole, titolo unico, tab ristrutturate, render live dei KPI

**Riepilogo:** Dopo la home, stessa passata di pulizia/redesign (mockup-first, poi codice reale) sulla pagina del singolo agente A1 — prima pagina agente toccata in questo giro, da usare come riferimento per A2/A3/A4 in seguito.

**Cosa è stato fatto:**
1. **Pillole header**: il pulsante "← Home" perde la freccetta e diventa a punta a sinistra (stesso pattern della pillola Hub in home); "Attiva notifiche" diventa una vera pillola, stessa altezza/dimensioni della pillola calendario (prima era testo semplice).
2. **Titolo hero unificato**: da etichetta piccola + sottotitolo grande ("Agente 1" / "Data Collector") a un unico titolo ("AGENTE 1 — Data Collector"), colore dinamico coerente con lo stato corrente (verde=completato, rosso=MBS mancante, oro=in corso, blu=inattivo) — stessa logica della home. Descrizione sotto il titolo riscritta per essere informativa (cosa fa, dove va l'output) invece del generico "nessun intervento richiesto".
3. Badge "⚙ Automatico" reso neutro (grigio) — il verde stonava, non comunicava uno stato.
4. **Riferimenti a Drive ormai sbagliati corretti**: banner e step "Cosa fa" parlavano ancora di cercare il CSV MBS "su Drive" — ora dicono correttamente "bucket Supabase Storage" (coerente con la migrazione del CSV MBS fatta in sessione precedente). Aggiunto pulsante "Carica CSV" nelle Azioni (mancava su questa pagina, c'era solo in home) e corretto il link "Apri Google Sheet" che puntava alla cartella Drive invece che al foglio.
5. **Pulsante BPT Calendar mancante**: Gianluca l'ha notato in revisione — bpt_calendar.py ha un workflow GitHub proprio (`bpt_calendar.yml`, stesso cron di A1 Monthly ma non lo stesso workflow), non c'era alcun pulsante per vederlo/avviarlo. Aggiunto in Azioni, più la riga cron e il secret `DRIVE_FOLDER_A3` in Config.
6. **Tab ridotte da 5 a 4** (proposta di Gianluca, io ho proposto la disposizione): Panoramica assorbe Attività (Azioni + stat ultimo run + log activity_log + riepilogo BPT in un'unica tab); Lavoro invariata nella struttura ma con gli step "Cosa fa" più dettagliati; Documenti non mostra più solo link statici ma il **render live degli ultimi KPI mensili** dalla tabella Supabase `kpi_mensili` (reach/like/commenti/salvataggi/viralità per mese), con link diretto alla tabella su Supabase, più il Google Sheet; Config invariata nella sostanza ma guadagna la sezione Script (spostata da Documenti, più coerente lì) e la riga BPT Calendar.

**Decisioni prese:**
- Contesto: Gianluca ha chiesto se serva ancora il "doppio binario" Google Sheet + Supabase per i dati di A1, visto che ora Documenti mostra dati Supabase.
- Decisione: sì, resta necessario, ma non è un doppio binario ridondante — sono tre pezzi con tre scopi diversi. Google Sheet = unica fonte dati di A2 (legge 5 sheet dettagliati che su Supabase non esistono in quel formato, confermato leggendo `docs/prompts/Agente2_auto_prompt_v20.md`). Supabase `posts` = serve alla categorizzazione e al gate di A2 (il Sheet non è interrogabile comodamente da un gate automatico o dal browser). Supabase `kpi_mensili` = prima di questa sessione non aveva alcun lettore (solo scritta da a1_monthly.py, mai letta da nessuno) — il render in Documenti le dà il suo primo vero scopo: è l'unico modo per mostrare dati KPI nella webapp senza esporre credenziali Google al browser.
- Alternative scartate: rimuovere la scrittura di `kpi_mensili` da a1_monthly.py in quanto codice senza scopo — scartata perché il render in Documenti le dà ora un consumo reale.
- Da rivedere se: in futuro si decidesse di togliere il render KPI da Documenti, la scrittura di `kpi_mensili` tornerebbe un sync morto e andrebbe tolta.

**File consegnati/modificati:** `app/agenti/a1-analytics/page_agent_a1_v1.html` (riscritta: CSS/HTML del redesign + nuova funzione `loadKpi()` con fetch reale da Supabase, mantenuto invariato il guard di autenticazione e le fetch reali esistenti — il giro di mockup su Artifact/file inviato in chat usava dati finti e nessun redirect, mai arrivato in questa forma al repo).

**Verifiche fatte:** sintassi JS (`node --check` sullo script estratto), controllo manuale che tutti i link relativi nuovi/esistenti (`carica_mbs.html`, `categorizza.html`, `../../page_home_v25.html`, `../../../page_login_v6.html`, `../../../sw.js`) risolvano a file reali.

**Impatto su Vision/Pipeline:** nessuno sui macro-step — stesso filone di pulizia/redesign dello Step 6, ora esteso dalla home alle pagine dei singoli agenti (A1 prima, A2/A3/A4 da fare con lo stesso approccio).

---

### [2026-11-16 15:00] Messaggio precompilato del ciclo editoriale aggiornato — tolto un riferimento ormai superato alla migrazione storica

**Riepilogo:** Gianluca ha notato che `MSG_CICLO` (il testo copiato dal pulsante "Copia messaggio" nella pillola del ciclo editoriale) citava ancora il gap sui mesi a cavallo della migrazione — superato da quando lo Step 7 ha portato tutta la storia del progetto su Supabase.

**Cosa è stato fatto:** Rimossa da `MSG_CICLO` la frase "Se manca un dato di input perché il mese è a cavallo della migrazione storica, chiedimi il link Drive diretto" — sostituita con un'istruzione generica, non più legata alla migrazione: "Se manca un dato di input, serve una categorizzazione non ancora fatta, o un passaggio richiede una mia conferma, fermati e dimmelo invece di procedere nel dubbio" (quest'ultima parte copre anche il gate di categorizzazione aggiunto al prompt A2 v20). Aggiunta anche una riga che dice alla sessione dedicata di usare sempre la versione più recente di ciascun prompt in `docs/prompts/`, non uno che potrebbe ricordare da una conversazione precedente — stessa cautela già annotata per il messaggio di setup iniziale della sessione (Step 8), qui estesa al messaggio che viene effettivamente incollato ogni mese.

**File consegnati/modificati:** `app/page_home_v25.html` (modificato: `MSG_CICLO`)

**Verifiche fatte:** sintassi JS (`node --check`).

**Impatto su Vision/Pipeline:** nessuno sui macro-step — correzione di un testo residuo, stessa famiglia di pulizia già in corso nello Step 6.

---

### [2026-11-16 14:30] Home page — seconda passata di correzioni su screenshot reale (pillole, pulsanti stato, colori, logo)

**Riepilogo:** Gianluca ha rivisto la home sul sito vero (screenshot da iPad) e ha chiesto 6 correzioni puntuali sul redesign di ieri — tutte applicate direttamente al codice, nessun nuovo giro di mockup (le basi erano già verificate ieri).

**Cosa è stato fatto:**
1. Rimosse le pillole "⚡ Auto"/"👤 Claude" dal titolo di A1-A4 (A5-A7 invariate, fuori perimetro).
2. **Bug trovato guardando lo screenshot**: la griglia dei pulsanti di stato (In coda/In corso/Fatto/Riposo/Inattivo/Errore) era a 5 colonne (`grid-template-columns:repeat(5,1fr)`) ma i pulsanti sono 6 — il sesto ("Errore") andava sempre a capo su una riga separata. Fix: 6 colonne, pulsanti leggermente più compatti per restare leggibili.
3. Titolo agente ingrandito (`.agent-name` da .82rem a 1rem). Colore dei pulsanti "Vedi report/piano/brief" (A2/A3/A4) reso coerente con la sostanza: erano rossi (classe `lg-primary`) anche quando il report esisteva già — ora `loadLatestReports()` applica `lg-done` (verde) quando trova un report, lascia il grigio neutro (`lg-disabled`, già di default) solo se non ne esiste ancora nessuno. "Carica CSV" di A1 resta rosso di proposito (Gianluca l'ha confermato: il file non è stato caricato dall'app, solo mandato in chat — rosso è corretto).
4. Rimossa l'etichetta di stato testuale sotto il logo ("COMPLETATO" ecc.) su A1-A4 — lo stato si legge già dal colore del bordo scheda e dai pulsantini sotto; elemento già gestito con guardia `if(lbl)` lato JS, rimozione sicura senza toccare lo script.
5. Rimossa la scheda "Tutti i sistemi attivi / Aggiornato alle...": logo GDC ingrandito (34px→40px), nuovo indicatore compatto (`sys-mini`: pallino + testo breve) inserito nella riga dell'header tra logo e pillola calendario — il dettaglio "Aggiornato alle HH:MM" resta disponibile come tooltip (`title`) invece che come testo visibile separato.
6. Pillola calendario e pillola notifiche uniformate (altezza 32px, stesso padding, stesso font-size) — prima il calendario era visibilmente più piccolo.

**Decisioni prese:**
- Contesto: dove mettere le informazioni di stato sistema tolte dalla scheda rimossa — Gianluca aveva offerto due opzioni (dentro il popup del calendario, oppure nella riga dell'header tra logo e calendario).
  Decisione: riga dell'header (opzione più semplice, non richiede ristrutturare il popup calendario) — il dettaglio orario resta comunque disponibile al passaggio del mouse/tocco prolungato (tooltip), non perso del tutto.
  Da rivedere se: Gianluca preferisce in pratica vedere il dettaglio orario sempre visibile — si può comunque spostare nel popup calendario in un secondo momento.

**File consegnati/modificati:**
- `app/page_home_v25.html` (modificato: CSS `.stato-row`/`.stato-pill`/`.agent-name`/`.date-chip`, nuova `.sys-mini`, rimossa `.system-bar` e classi correlate; HTML card A1-A4 e header; JS `loadLatestReports()` e gestione stato sistema)

**Verifiche fatte:** sintassi JS (`node --check`); controllo automatico di tutti i link locali del repo (33, 0 rotti).

**Impatto su Vision/Pipeline:** nessuno sui macro-step; prosegue il lavoro di pulizia grafica (Step 6) sulla home page, ora più rifinito dopo revisione diretta sul dispositivo reale.

---

### [2026-11-16 13:30] a1_monthly.py e a1_mbs_watcher.py aggiornati — MBS legge da Supabase Storage, non più da Drive

**Riepilogo:** Chiuso il cerchio aperto ieri con `carica_mbs.html`: `a1_monthly.py` e `a1_mbs_watcher.py` ora leggono il CSV repost MBS dal bucket Supabase Storage `mbs-csv` invece che dalla cartella Drive "Archivio docs MBS". Non ancora verificato con un run reale con un file vero caricato — vedi sotto.

**Cosa è stato fatto:**
- `scripts/a1_monthly.py`: rimossa `find_mbs_csv()` (ricerca su Drive per pattern di date nel nome, fragile — storicamente già causa di un bug quando l'ID Meta nel nome file è cambiato tra giugno e luglio 2026). Nuova `find_mbs_csv_path(supabase)`: confronto esatto su `{ANNO}-{MESE_NUM:02d}.csv` nella lista del bucket — più semplice e robusto perché ora il nome del file lo decidiamo noi al momento dell'upload, non più l'export di Meta. `fetch_mbs_reposts()` non prende più `drive_service` come parametro; scarica il CSV via `supabase.storage.from_('mbs-csv').download(path)` invece che via Drive API. Aggiornati i testi di email/push/activity_log sul file mancante: linkano ora a `carica_mbs.html` invece che alla cartella Drive.
- `scripts/a1_mbs_watcher.py`: stessa sostituzione (Drive → Storage) per il controllo periodico che decide se ritriggerare A1 Monthly. Rimossa `get_drive_service()` e l'intera dipendenza da `google-auth`/`googleapiclient` in questo script — non gli serve più nulla di Google, solo Supabase + GitHub API.
- `.github/workflows/a1_mbs_watcher.yml`: rimosso il secret `GOOGLE_CREDENTIALS` dall'env dello step (non più letto dallo script).
- Verificato: `python3 -m py_compile` su entrambi gli script; nessun riferimento residuo a `MBS_FOLDER_ID` o a `get_drive_service` nello watcher; confermato via query diretta che il bucket `mbs-csv` e la policy RLS creati ieri sono ancora al loro posto.

**Decisioni prese:**
- Contesto: come testare il nuovo codice, dato che questa sessione non ha le credenziali reali (service_role key, token Instagram) per lanciare `a1_monthly.py` in locale, né un modo per caricare io stesso un CSV di prova nel bucket (serve una sessione webapp autenticata da browser, non disponibile qui).
  Decisione: non lanciare un run reale di `a1_monthly.yml` senza coordinarmi prima con Gianluca — lo farebbe comunque con il bucket vuoto (nessun file ancora caricato da nessuno in `mbs-csv`), quindi manderebbe una email/push reale "MBS mancante" che rischia di confondere, dato che il file su Drive per il mese corrente esiste già (il run del 16/11 è già andato a buon fine con il vecchio codice, prima di questa modifica).
  Alternative scartate: testare caricando un file fittizio via SQL direttamente nella tabella `storage.objects` — scartata, creerebbe una riga senza il contenuto reale nel backend di storage, stato inconsistente.
- Contesto: se mantenere un fallback che controlla ANCHE Drive, per transizione morbida, o tagliare netto su Supabase Storage.
  Decisione: taglio netto, Drive non viene più controllato per MBS — Gianluca aveva chiesto esplicitamente "dato che ora non usiamo più il drive" il 15/11, quindi un fallback silenzioso avrebbe contraddetto l'intenzione.
  Da rivedere se: il primo run reale con un file vero caricato da webapp dovesse fallire per un motivo imprevisto nell'API storage3/supabase-py (nessuna verifica diretta possibile in questa sessione, solo lettura della documentazione del pacchetto).

**File consegnati/modificati:**
- `scripts/a1_monthly.py` (modificato: `find_mbs_csv_path()`, `fetch_mbs_reposts()`, link email/push)
- `scripts/a1_mbs_watcher.py` (modificato: `find_mbs_csv_path()`, rimossa dipendenza Google Drive)
- `.github/workflows/a1_mbs_watcher.yml` (modificato: rimosso secret `GOOGLE_CREDENTIALS`)
- `docs/documento-sessione-gdc-ia-team.md`

**Impatto su Vision/Pipeline:** nessuno sui macro-step; chiude il lavoro "MBS senza Drive" iniziato il 15/11 nello Step 6. **Resta da fare per chiudere del tutto**: una verifica con un run reale — Gianluca carica un CSV vero (o di prova) via `carica_mbs.html`, poi si lancia A1 Monthly e si controllano i log, stesso principio già seguito per ogni altra automazione di questo progetto (costruire, poi verificare con un caso vero prima di fidarsene).

---

### [2026-11-16 12:00] Step 6 anticipato — redesign home page (pillole, ciclo editoriale, card A1-A4) + upload MBS senza Drive

**Riepilogo:** Gianluca ha anticipato la pulizia grafica (Step 6, inizialmente rimandata a fine pipeline) con una prima passata sulla home page: iterata via mockup su Artifact fino ad approvazione, poi applicata al codice reale. Criterio guida: "il pulsante serve? Se sì lo teniamo, se no lo togliamo." In parallelo, risolto il tema di come caricare il CSV di Meta Business Suite senza passare più da Drive.

**Cosa è stato fatto:**
- Iterato un mockup HTML (Artifact, stessi font/colori del sito reale) su 4 round di revisione per: pillole Hub (punta sinistra "torna indietro")/Notifiche (stato colorato→neutro), pillola unica per il ciclo editoriale (bottoni a specchio, icona verso l'esterno/testo verso il centro), card A1/A2 con angolo sinistro concentrico al logo.
- Applicato il design approvato a `app/page_home_v25.html`: nuove classi CSS (`.pill-hub-wrap`/`.pill-hub`, `.pill-notif`, `.ciclo-pill`/`.ciclo-end`/`.ciclo-label`, `.acard-logo-round`); card A1-A4 senza descrizione testuale; A1 con soli 2 pulsanti (Apri MBS + Carica CSV); A2/A3/A4 con un solo pulsante dinamico "Vedi report/piano/brief" che punta sempre al mese più recente trovato su Supabase (nuova `loadLatestReports()`), al posto dei 3 pulsanti dipendenti dallo stato di prima (`renderActions()`/`copyMsg()` rimossi).
- **Bug evitato prima di arrivare al codice reale**: il primo tentativo di pillola con punta a sinistra usava un CSS `border` classico — si tagliava in modo innaturale sulla punta (visibile solo sul mockup, mai arrivato al sito vero). Fix: due livelli sovrapposti con lo stesso `clip-path`, nessun `border`.
- **MBS senza Drive**: creato bucket Supabase Storage privato `mbs-csv` + policy RLS `mbs_csv_authenticated_all`; nuova pagina `app/agenti/a1-analytics/carica_mbs.html` (selettore mese/anno + drag&drop, upload diretto via Storage API). Verificato che un download automatico via browser non è praticabile da questa sessione (nessun accesso Chrome/computer-use in ambiente cloud) e che l'API Meta non offre comunque il dettaglio dei repost (confermato il 12/11, invariato). Il lato lettura (`a1_monthly.py` legge ancora da Drive) resta un passaggio separato, segnalato esplicitamente nella pagina stessa.
- Verificato: sintassi JS (`node --check`) su entrambi i file toccati; controllo automatico di tutti i link locali del repo (33, 0 rotti); bucket e policy Supabase confermati con query diretta.

**Decisioni prese:**
- Contesto: come automatizzare il download del CSV MBS, dato che l'API non espone i dati di dettaglio dei repost.
  Decisione: il passo di export manuale da MBS resta; cambia solo la destinazione, da cartella Drive con nome file esatto a upload diretto su Supabase Storage dalla webapp.
  Alternative scartate: script che si autentica da solo su Meta (fragile, rischio ToS); nessuna, dato il vincolo tecnico confermato due volte (12/11 e 16/11).
- Contesto: quando applicare la pulizia grafica della home, rispetto all'ordine Step 7→8→9→6 deciso il 15/11.
  Decisione: Gianluca ha scelto di anticiparla comunque, in parallelo, non più strettamente "per ultima".
  Alternative scartate: nessuna — scelta esplicita e diretta di Gianluca, non una proposta di Claude.

**File consegnati/modificati:**
- `app/page_home_v25.html` (modificato: pillole, ciclo editoriale, card A1-A4, `loadLatestReports()`, rimossi `renderActions()`/`copyMsg()`)
- `app/agenti/a1-analytics/carica_mbs.html` (nuovo)
- Supabase: bucket Storage `mbs-csv` (nuovo, privato) + policy `mbs_csv_authenticated_all`
- `docs/documento-sessione-gdc-ia-team.md`

**Impatto su Vision/Pipeline:** Step 6 passa da "pulizia rimandata a fine pipeline" a "pulizia in corso in parallelo" (prima passata: home page). Resta da fare: stessa pulizia sulle pagine singolo-agente (dove si sposta il percorso "vecchio" con Progetto Claude.ai/copia messaggio, tolto dalla home), aggiornamento di `a1_monthly.py` per leggere il CSV MBS da Supabase Storage invece che da Drive, pulizia del codice morto residuo (`MSGS.A2/A3/A4`, `PROJ`, `DRIVE`, `FILE_CUR`, `FILE_FMT`).

---

### [2026-11-15 19:45] Gate categorizzazione obbligatoria prima di A2 (prompt A2 v20) — risponde a: come si gestisce l'interruzione per categorizzare i post?

**Riepilogo:** Gianluca ha chiesto come viene gestita, nel nuovo flusso automatico (Step 8), l'interruzione in cui deve categorizzare manualmente i post prima che A2 possa analizzarli (schermata webapp dello Step 4). Verificato che oggi **nessuna versione del prompt controlla questo** — funzionava solo perché finora Gianluca categorizzava sempre prima di aprire il Progetto Claude.ai di A2 a mano. Una sessione automatica che riceve solo "esegui il ciclo di [mese]" non ha modo di saperlo da sola: avrebbe generato silenziosamente un report con Mix Topic incompleto, lo stesso bug già visto (e finora corretto solo a valle) nello Step 5. Aggiunto un gate esplicito in testa al prompt di A2.

**Cosa è stato fatto:**
- Prompt A2 v19→v20 (`Agente2_auto_prompt_v20.md`, v19 rimosso): nuovo Step 0.5 in sez. 4, eseguito subito dopo la segnalazione `agent_states`→'working' e prima di leggere qualunque dato. Interroga Supabase (`select count(*) from posts where mese = '[Mese Anno]' and categoria_primaria is null`) — stessa query già usata dalla card "Categorizza post" di A1 per il conteggio "N post da categorizzare". Se 0: procede normalmente (vale anche per i mesi storici pre-Step 4, dove la tabella `posts` non ha righe per quel mese — nessun blocco falso). Se maggiore di 0: si ferma, comunica a Gianluca quanti post mancano e il link alla pagina di categorizzazione (`.../app/agenti/a1-analytics/categorizza.html`), e riprende solo dopo una sua conferma esplicita — stesso pattern "fermati e comunica" già validato su A4 per i dati mancanti (Step 5), qui applicato preventivamente invece che scoperto come bug a posteriori.
- Verificata la query direttamente su Supabase prima di scriverla nel prompt (non solo per ragionamento): su Ottobre 2026 restituisce 0 post da categorizzare (coerente con i 7/7 già categorizzati), confermando che la stessa query usata altrove nella webapp si comporta come previsto anche per questo nuovo uso.

**Decisioni prese:**
- Contesto: dove deve vivere questo controllo — nel prompt di A2 (letto da chiunque esegua A2, sessione dedicata o Progetto Claude.ai) o solo nelle istruzioni della sessione dedicata dello Step 8.
  Decisione: nel prompt di A2 — è la fonte autorevole che ogni esecutore legge comunque, non duplica logica nella sessione orchestratrice, e resta valido anche se in futuro A2 gira da un posto diverso.
  Alternative scartate: mettere il controllo solo nelle istruzioni della sessione Claude Code dedicata — scartata perché duplicherebbe la logica in un posto meno autorevole e non proteggerebbe un run di A2 lanciato altrove (es. ancora dai Progetti Claude.ai, possibile durante la transizione).

**File consegnati/modificati:**
- `docs/prompts/Agente2_auto_prompt_v20.md` (nuovo, sostituisce `Agente2_auto_prompt_v19.md`)
- `docs/documento-sessione-gdc-ia-team.md`

**Impatto su Vision/Pipeline:** nessuno sui macro-step della pipeline (lavoro di dettaglio dentro lo Step 8, già "in corso"). Nota per la sessione dedicata: il suo messaggio di setup iniziale cita ancora per nome `Agente2_auto_prompt_v19.md` (non più esistente) — non bloccante, perché le sue istruzioni le dicono comunque di leggere i prompt "per intero prima di eseguire ogni agente" e troverà v20 cercando nella cartella; non è stato possibile inviarle un messaggio di correzione diretto in questa sessione (nessun tool disponibile per messaggiare una sessione Claude Code Remote già creata) — da verificare al primo ciclo reale che lo faccia correttamente da sola.

---

### [2026-11-15 19:10] Step 8 avviato — sessione Claude Code dedicata creata + bottone webapp

**Riepilogo:** Discusse con Gianluca le due scelte architetturali chiave dello Step 8 (sessione persistente vs nuova ogni volta; scope iniziale con o senza la modalità itinerante di A4) e avviato il lavoro concreto: creata la sessione Claude Code dedicata e persistente per il ciclo A2→A3→A4, e aggiunto il bottone corrispondente nella webapp.

**Cosa è stato fatto:**
- Creata una sessione Claude Code Remote dedicata (`session_01HsrMVD8rfwcZoBQUR5DssK`), agganciata al repo `giandcdalcorso11-coder/GDC-DASHBOARD` su branch `main` (a differenza di questa sessione di sviluppo, che lavora sul branch `claude/webapp-github-automation-analysis-76x7fi`). Eredita automaticamente connettori e accesso già configurati per l'ambiente (Supabase, Google Drive, GitHub) — nessuna configurazione aggiuntiva necessaria.
- Messaggio di setup iniziale inviato alla sessione: ruolo (eseguire A2→A3→A4 nell'ordine solo su richiesta esplicita con il nome del mese), dove trovare le istruzioni (i 3 prompt in `docs/prompts/`, A1 escluso perché completamente automatico), dove leggere lo stato del progetto prima di ogni ciclo (`docs/documento-sessione-gdc-ia-team.md`), cosa fare dopo ogni ciclo (nuova voce di storico + commit/push su `main`), e il perimetro esplicito (la modalità itinerante di A4 resta fuori). Verificato che la sessione ha letto il messaggio ed è pronta, in attesa (stato: idle, nessun ciclo eseguito).
- Nuova card "Ciclo editoriale mensile" in cima a `page_home_v25.html` (sopra la lista per-agente, perché l'azione è trasversale A2→A3→A4): due pulsanti, "Apri sessione" (link fisso alla sessione dedicata) e "Copia messaggio" (riusa il meccanismo popup `openMsg()` già esistente sulla pagina per altri messaggi, nessun nuovo componente). Nuovo messaggio precompilato `MSG_CICLO`, generato dinamicamente con mese corrente/precedente, stesso pattern già in uso per i messaggi degli altri agenti su questa pagina.
- Verificata la sintassi JS della pagina dopo le modifiche (estratto e validato con `node --check`).

**Decisioni prese:**
- Contesto: se la sessione dedicata ad A1-A4 deve essere una sola sessione persistente ripresa ogni mese, o una nuova sessione creata ad ogni ciclo.
  Decisione: persistente — un solo link fisso nel bottone, continuità di contesto/memoria tra un mese e l'altro.
  Alternative scartate: sessione nuova ogni volta (link che cambia o va rigenerato ogni mese, nessuna memoria pregressa) — scartata da Gianluca a favore della continuità, accettando il compromesso di un contesto che cresce nel tempo (gestibile con autocompact se necessario).
- Contesto: se includere la modalità itinerante di A4 (consulenza creativa post per post durante il mese) nello scope di questo step.
  Decisione: resta fuori per ora — lo Step 8 v1 copre solo l'apertura mese (A2→A3→A4). Idea di integrarla nella stessa sessione dedicata discussa ma non decisa, da valutare più avanti.
  Alternative scartate: includerla da subito nella stessa sessione — scartata perché avrebbe richiesto che la sessione restasse aperta/richiamabile tutto il mese e non solo a inizio mese, cambiando la natura dello step.
  Da rivedere se: Gianluca chiede esplicitamente di allargare lo scope in un prossimo step.
- Nota collaterale (non una decisione formale, solo registrata): discussa anche una vision più a lungo termine — editing video e gestione/pubblicazione diretta dei post dalla stessa catena — esplicitamente descritta da Gianluca come lavoro nuovo, lungo, da affrontare solo a pipeline finita. Nessuna azione presa; osservazione di Claude: l'editing video romperebbe probabilmente il vincolo "zero costo extra" (richiede strumenti esterni al di fuori di Claude Code), la pubblicazione diretta è più abbordabile via API Instagram ma richiede un gate di conferma per non eliminare la revisione editoriale di Gianluca prima della pubblicazione.

**File consegnati/modificati:**
- `app/page_home_v25.html` (modificato: nuova card "Ciclo editoriale mensile", nuova costante `MSG_CICLO`)
- Sessione Claude Code Remote `session_01HsrMVD8rfwcZoBQUR5DssK` (nuova, non è un file di repo ma una risorsa dell'account — link: `https://claude.ai/code/session_01HsrMVD8rfwcZoBQUR5DssK`)
- `docs/documento-sessione-gdc-ia-team.md`

**Impatto su Vision/Pipeline:** Step 8 passa da "da fare" a "in corso". Resta da fare per chiuderlo: una prova reale completa (Gianluca lancia un ciclo vero dalla sessione dedicata e si verifica che A2→A3→A4 vadano a buon fine in sequenza).

---

### [2026-11-15 18:30] Step 7 completato — migrazione storica completa dei 22 mesi A2/A3/A4

**Riepilogo:** Su istruzione esplicita di Gianluca ("tutto dall'inizio del progetto... come se dall'inizio avessimo usato questo nuovo workflow"), convertiti in HTML/Supabase tutti i documenti storici mai prodotti da A2, A3 e A4 prima della migrazione dello Step 5 — 22 mesi in totale, nessuno escluso. `report_mensili` ora contiene l'intera storia del progetto, non solo i mesi prodotti dal nuovo workflow in avanti.

**Cosa è stato fatto:**
- Inventario completo via ricerca Google Drive sulle tre cartelle agente: A2 Gennaio-Settembre 2026 (9 mesi, Ottobre già reale dallo Step 5), A3 Aprile-Ottobre 2026 (7 mesi, Novembre già reale), A4 Maggio-Ottobre 2026 (6 mesi, Novembre già reale).
- Per ciascun mese: letto il documento originale da Drive (PDF, Google Doc o Google Slides secondo il caso), ricostruito fedelmente come pagina HTML nel template reale e già in produzione dell'agente (CSS/struttura presi da una riga Supabase vera, non ricreati a memoria), scritto via `INSERT ... ON CONFLICT (agente, mese)` direttamente su `report_mensili` — nessun file intermedio nel repo.
- Principio seguito ovunque: "cambia solo il contenitore" — nessun numero, frase o classificazione storica è stata corretta col senno di poi (es. la serie "Capiamo la Sabbia" a Settembre 2026 resta GDC STUFF/SPORT, non riclassificata DIVULGAZIONE anche se quella categoria esiste da mesi successivi). Dati illeggibili nei PDF più vecchi (soprattutto OCR a doppia colonna) non sono stati mai inventati: dove la lettura era ambigua, la ricostruzione più plausibile è stata comunque segnalata con una nota di trasparenza dentro l'HTML stesso.
- Recuperato un riavvio del processo di lavoro a metà percorso (durante A2 Agosto 2026) senza perdita né duplicazione di dati, grazie alla checklist a task e alla natura idempotente degli upsert.
- Verifica finale con query diretta su `report_mensili`: 25 righe totali (A2: 10 mesi Gennaio-Ottobre; A3: 8 mesi Aprile-Novembre; A4: 7 mesi Maggio-Novembre), nessun mese mancante.

**Decisioni prese:**
- Contesto: come trattare dati OCR ambigui o mancanti nei documenti storici più vecchi (PDF a doppia colonna con serie di dati interlacciate).
  Decisione: mai inventare un numero preciso — dove il PDF non permette una lettura certa, presentare solo i campi leggibili con certezza e aggiungere una nota di trasparenza esplicita nell'HTML, stesso pattern già usato dagli agenti reali quando manca un dato.
  Alternative scartate: tentare comunque una ricostruzione numerica precisa presentata come dato certo — scartata perché avrebbe introdotto numeri falsi nella storia del progetto.
- Contesto: come trattare le classificazioni storiche superate da decisioni successive (es. tassonomia DIVULGAZIONE, introdotta dopo Settembre 2026).
  Decisione: ogni mese riflette la classificazione che l'agente aveva davvero usato in quel momento, non quella "corretta" col senno di poi.
  Alternative scartate: applicare retroattivamente le tassonomie più recenti a tutta la storia — scartata perché contraddice il principio "cambia solo il contenitore" e falsificherebbe la cronologia reale delle decisioni di progetto.

**File consegnati/modificati:** nessun file di codice — solo 22 nuove righe in `report_mensili` su Supabase (nessuna migrazione di schema necessaria, tabella già condivisa a2/a3/a4 dallo Step 5); `docs/documento-sessione-gdc-ia-team.md`.

**Impatto su Vision/Pipeline:** Step 7 passa da "da fare" a "completato". Prossimo passo in pipeline: Step 8 (sessione Claude Code dedicata per l'intera catena A1→A4), poi Step 6 (pulizia grafica/organizzazione) per ultimo, come già deciso. Discussione aperta con Gianluca su un possibile allargamento di scope per lo Step 8 (includere la modalità itinerante di A4, finora esplicitamente fuori dall'automazione) e su una vision a lungo termine ulteriore (editing video e gestione pubblicazione post direttamente dalla stessa catena) — entrambe non ancora decise, solo discusse; vedi conversazione per il ragionamento, non ancora trascritto come decisione.

---

### [2026-11-15 16:15] Step 5 completato — run reali di verifica A3 e A4

**Riepilogo:** Gianluca ha fatto girare per davvero A3 (prompt v13, piano Novembre 2026) e A4 (prompt v8, brief Novembre 2026): entrambi hanno scritto correttamente su Supabase, verificato leggendo l'HTML reale e gli stati agenti. Entrambi hanno incontrato lo stesso gap sui dati a cavallo della migrazione (mesi precedenti non ancora su Supabase) — gestito diversamente da ciascuno, risolto in entrambi i casi senza toccare i prompt. Lo Step 5 (migrazione A2/A3/A4 da pptx/pdf a HTML/Supabase) è ora completato in tutti i suoi 5 punti.

**Cosa è stato fatto:**
- Verificata la run reale di A3: `report_mensili` (a3, Novembre 2026, 21.613 caratteri) e `agent_states` (a3→done, a4→ready) corretti. A3 ha incontrato da solo il gap (piano Ottobre non su Supabase, perché generato prima della migrazione di A2/A3) e l'ha risolto di propria iniziativa leggendo il vecchio file da Drive, segnalandolo sia in chat che come nota esplicita nel piano stesso.
- Verificata la run reale di A4: `report_mensili` (a4, Novembre 2026, 19.744 caratteri) e `agent_states` (a4→done) corretti, `activity_log` con il primo link che punta al nuovo sistema (`brief.html?mese=...`) invece che a una cartella Drive. A4 ha incontrato lo stesso gap (report A2 Settembre, piano A3 Ottobre) ma si è fermato come da prompt v8 ("fermati e comunica se manca un dato obbligatorio") invece di risolverlo da solo — risolto passandogli i link Drive diretti ai due file mancanti.

**Decisioni prese:**
- Contesto: come gestire il gap sui dati dei mesi a cavallo della migrazione (report/piani prodotti prima che A2/A3 scrivessero su Supabase, quindi assenti quando l'agente successivo li cerca).
  Decisione: non è un bug da correggere nei prompt — il comportamento di A4 (fermarsi e comunicare) era quello corretto e voluto. L'intervento giusto è fornire i dati mancanti al momento (link Drive ai vecchi file), non modificare l'automazione. Il gap è transitorio: da Dicembre 2026 in avanti non si ripresenta, perché ogni documento nuovo sarà già su Supabase quando il mese successivo lo richiede.
  Alternative scartate: backfillare manualmente su Supabase i report/piani storici pre-migrazione solo per chiudere questo gap — non necessario, il problema si risolve da solo col passare dei mesi.

**File consegnati/modificati:** `docs/documento-sessione-gdc-ia-team.md` (nessuna modifica a codice/prompt in questa sessione — solo verifica e aggiornamento pipeline).

**Impatto su Vision/Pipeline:** Step 5 passa da "in corso" a "completato". Prossimo step della pipeline: Step 7 (migrazione storico Drive→Supabase) e Step 8 (sessione Claude Code dedicata per l'intera catena A1→A4), poi Step 6 (pulizia grafica/organizzazione) per ultimo, come già deciso.

---

### [2026-11-15 11:45] Step 5 punto 5 — A4 su HTML/Supabase (non ancora verificato con run reale) — tutti i 5 punti ora costruiti

**Riepilogo:** Costruito per A4 lo stesso lavoro già fatto per A2 e A3 (punto 5/5, ultimo della scomposizione dello Step 5), adattato alla natura particolare di A4: solo il brief di apertura mese è stato migrato a HTML/Supabase, il lavoro libero post per post (sez. 6 del suo prompt) resta conversazione non automatizzata, come già deciso il 12/11.

**Cosa è stato fatto:**
- Nessuno schema nuovo: riusata `report_mensili` (agente='a4').
- Nuova `app/agenti/a4-brief/brief.html` (stesso meccanismo lista+iframe di `report.html`/`piano.html`), card "Brief mensili" su `page_agent_a4_v1.html`.
- Aggiornato il messaggio precompilato di A4 (`page_agent_a4_v1.html`): citava ancora file pptx su Drive per piano A3 e report A2 (già rotti dalla migrazione di A2/A3); i dati A1 restano sul Google Sheet, link diretto aggiunto come già fatto per A3.
- Prompt A4 v7→v8 (`Agente4_auto_prompt_v8.md`, v7 rimosso): output pagina HTML su Supabase invece di PDF via `present_files` + upload manuale su Drive; input piano A3/report A2 spostato su Supabase (stessa logica di A3); nuova sez. 4.3 con la struttura tecnica HTML (palette blu propria, card responsive, nessuno script/font esterno); `agent_states`→'working' all'apertura e →'done' alla chiusura incluse fin da subito — nessuna riga 'ready' per un agente successivo (A4 è l'ultimo della catena A1→A4 migrata, A5-A7 non sequenziali a questo passaggio). Sezioni 5-9 (struttura brief, lavoro post per post, serie Capiamo la Sabbia, revisione, tono) invariate in sostanza.

**File consegnati/modificati:**
- `app/agenti/a4-brief/brief.html` (nuovo)
- `app/agenti/a4-brief/page_agent_a4_v1.html` (card azione + messaggio precompilato)
- `docs/prompts/Agente4_auto_prompt_v8.md` (nuovo, sostituisce `Agente4_auto_prompt_v7.md`)
- `docs/documento-sessione-gdc-ia-team.md`

**Impatto su Vision/Pipeline:** Step 5 — tutti i 5 punti della scomposizione ora costruiti (A2 verificato con run reali; A3 e A4 non ancora verificati con una run reale). Prossimo passo: Gianluca prova A3 e A4 per davvero, poi lo step si considera completo.

---

### [2026-11-15 10:15] Step 5 punto 4 — A3 su HTML/Supabase (non ancora verificato con run reale)

**Riepilogo:** Costruito per A3 lo stesso lavoro già fatto per A2 (punto 4 su 5 della scomposizione dello Step 5): pagina piano, prompt v12→v13. In più, migrando A3 è emerso che anche il suo input dipendeva da file pptx ormai inesistenti (report A2, piano precedente) — spostato anche quello su Supabase. Corretta anche A2 (v18→v19) per completare la catena di stati A1→A2→A3→A4.

**Cosa è stato fatto:**
- Nessuno schema nuovo: riusata `report_mensili` (già condivisa a2/a3/a4). Verificata la pipeline con una riga di test (da eliminare — conferma `DELETE` non ricevuta in tempo, come già successo per A2).
- Nuova `app/agenti/a3-planner/piano.html` (stesso meccanismo `<iframe srcdoc>` di `report.html`), card "Piani editoriali" su A3.
- Aggiornato il messaggio precompilato di A3 (`page_agent_a3_v1.html`): citava ancora file pptx su Drive per il report di A2 e il proprio piano precedente, entrambi non più prodotti lì dalla v18 di A2 in avanti.
- Prompt A3 v12→v13 (`Agente3_auto_prompt_v13.md`): output HTML su Supabase (stessa logica della v16 di A2); **input** report A2 e piano precedente letti da Supabase invece che da pptx su Drive (cambio non necessario per A2, ma necessario qui perché A3 dipende da output che A2 non produce più); auto-segnalazione di stato su `agent_states` inclusa fin da subito (non dopo, come per A2); segnalazione di A4 pronto alla chiusura di A3.
- Prompt A2 v18→v19 (`Agente2_auto_prompt_v19.md`): aggiunta la riga mancante della catena — A2 ora segnala A3 pronto quando finisce (stesso bug del pallino bloccato, qui chiuso anche per lo step successivo).

**File consegnati/modificati:**
- `app/agenti/a3-planner/piano.html` (nuovo)
- `app/agenti/a3-planner/page_agent_a3_v1.html` (modificato: card "Piani editoriali", messaggio precompilato)
- `docs/prompts/Agente3_auto_prompt_v13.md` (nuovo, sostituisce `Agente3_auto_prompt_v12.md`)
- `docs/prompts/Agente2_auto_prompt_v19.md` (nuovo, sostituisce `Agente2_auto_prompt_v18.md`)

---

### [2026-11-15 09:20] Decisione: pulizia grafica/organizzazione rimandata a fine pipeline

**Riepilogo:** Gianluca ha chiesto di accodare in pipeline (Step 6), da fare solo dopo aver completato tutti gli step di funzionamento, una pulizia di grafica e organizzazione delle sezioni — niente eseguito ora, solo registrato.

**Decisioni prese:**
- Contesto: lavorando sulla webapp sono emerse cose che a Gianluca non piacciono (es. la Dashboard KPI di A2 richiede di entrare in una scheda separata) e residui della versione precedente non più usati.
- Decisione: questa pulizia va fatta per ultima, dopo Step 5 (punti 4-5, A3/A4), 7, 8, 9 — prima si finisce il funzionamento, poi si riordina com'è fatto. Aggiunta come nuova parte dello Step 6 (già esistente per la riorganizzazione cartelle), non come step separato.
- Da rivedere se: quando si arriva a quel punto, serve un audit dedicato per l'elenco completo dei residui da rimuovere — i due esempi dati non sono esaustivi.

**File consegnati/modificati:**
- `docs/documento-sessione-gdc-ia-team.md` (Pipeline, Step 6 aggiornato)

---

### [2026-11-15 09:05] Copertine confermate + bug pallino A2 bloccato (prompt A2 v18)

**Riepilogo:** Gianluca ha confermato che le copertine reali funzionano nel report (foto quadrate invece di 190×150, rimandato — non urgente). Notando poi che il logo di A2 in home restava rosso dopo il completamento, trovato e risolto un secondo bug reale: nessuno script segnalava mai il completamento di A2 su `agent_states`.

**Cosa è stato fatto:**
- Verificato `agent_states` per `a2`: la riga era già `done` (A2 l'aveva scritta di propria iniziativa durante il run v17, non essendo nel prompt) — spiegazione più probabile per quanto visto da Gianluca: pagina caricata prima di quell'aggiornamento, da ricaricare.
- Confermato via grep su tutti gli script che solo `a1_monthly.py` scrive lo stato di A2 ("ready"), nessuno scrive "done" — il comportamento osservato era un'iniziativa non garantita dell'agente, non una regola scritta.
- Prompt A2 v17→v18 (`Agente2_auto_prompt_v18.md`): nuovo Step 0 (sez. 4) — scrive `agent_states`→'working' prima di leggere i dati; Chiusura (sez. 11) — scrive `agent_states`→'done' con mese/n_post/n_stories, stesso pattern già usato da A1 per sé.

**File consegnati/modificati:**
- `docs/prompts/Agente2_auto_prompt_v18.md` (nuovo, sostituisce `Agente2_auto_prompt_v17.md`)

---

### [2026-11-15 08:10] Copertine reali dei post (prompt A2 v17)

**Riepilogo:** Dopo aver verificato il report corretto, Gianluca ha chiesto se fosse possibile sostituire il placeholder colorato con l'immagine vera del post. Verificato che l'API Instagram la fornisce già (solo non richiesta finora), controllati i limiti del piano free Supabase (nessun rischio), implementato il download/upload permanente e il rendering a dimensione fissa nel report — verificato con una run reale di A1, non ancora con una run reale di A2.

**Cosa è stato fatto:**
- Creato il bucket pubblico Supabase Storage `post-covers`.
- Nuova `upload_post_cover_image()` in `a1_monthly.py`: scarica la copertina giusta per tipo di post (thumbnail per i Reel, prima slide per i caroselli, immagine diretta per i post singoli) e la ri-ospita sul bucket — necessario perché gli URL che Instagram restituisce sono firmati e scadono in poco tempo, non vanno bene per un report che deve restare leggibile per mesi.
- Nuova colonna `posts.image_url` su Supabase e nuova colonna 24 "Immagine URL" sul Google Sheet (gestita da `_ensure_post_header_v4()`, generalizzata per aggiungere colonne in coda oltre "Episodio Serie").
- Prompt A2 v16→v17 (`Agente2_auto_prompt_v17.md`): nuove classi `.gdc-cover`/`.gdc-cover img` (dimensione fissa, `object-fit:cover`, responsive), markup con fallback `onerror` al placeholder colorato. Nessun'altra modifica alla sostanza del report.
- Verificato con una run reale di A1 Monthly (Ottobre 2026): 7/7 post ORIGINALE con `image_url` valido, file caricati controllati come JPEG reali (116–339 KB) via metadati di `storage.objects`, colonna 24 del Google Sheet popolata correttamente.

**File consegnati/modificati:**
- `scripts/a1_monthly.py` (modificato: `upload_post_cover_image()`, nuova colonna Immagine URL, generalizzato `_ensure_post_header_v4()`)
- `supabase/migrations/20261115_add_post_covers_storage.sql` (nuovo)
- `docs/prompts/Agente2_auto_prompt_v17.md` (nuovo, sostituisce `Agente2_auto_prompt_v16.md`)

---

### [2026-11-14 23:05] Prima run reale di A2 v16 — trovato e risolto bug di sincronizzazione categorie

**Riepilogo:** Gianluca ha fatto girare per davvero A2 v16 su Ottobre 2026: report visibile sulla webapp, ma con Mix Topic incompleto. Causa trovata e risolta: le categorie inserite a mano dalla webapp (Step 4) non arrivavano al Google Sheet che A2 legge ancora. Verificato con una seconda run reale di A1 Monthly che il fix funziona.

**Cosa è stato fatto:** vedi il bug Sintomo/Causa/Fix nelle Note dello Step 5 (Pipeline) — stesso livello di dettaglio, non duplicato qui.

**File consegnati/modificati:**
- `scripts/a1_monthly.py` (modificato: nuova `fetch_posts_categorization_overrides()`, usata in `compile_sheet_post()`)

---

### [2026-11-14 14:10] Step 5 — pagina Report + prompt A2 v16 (punto 3 su 5)

**Riepilogo:** Completato lo schema e la pagina per i report HTML (condivisa a2/a3/a4) e riscritto il prompt di A2 (v15→v16): stesso contenuto e stessa sostanza di sempre, cambia solo il contenitore (HTML su Supabase invece di PPTX su Drive). Manca ancora una run reale di A2 per verificare che il nuovo prompt produca davvero l'HTML atteso.

**Cosa è stato fatto:**
- Tabella Supabase `report_mensili` (agente a2/a3/a4, chiave agente+mese, RLS `authenticated_all_report_mensili`), migrazione registrata in `supabase/migrations/20261114_add_report_mensili.sql`.
- Nuova `app/agenti/a2-analyst/report.html`: senza `?mese=` mostra l'elenco dei mesi con report disponibili; con `?mese=X` apre quel report dentro un `<iframe srcdoc>` — scelta deliberata per isolare lo stile scuro/Impact/Courier New del report dallo stile chiaro/Jost dell'app, senza dover scrivere regole CSS "scoped" fragili. Card "Report mensili" aggiunta alle Azioni di A2.
- Verificata la pipeline con una riga di test scritta ed eliminata subito su Supabase (nessun dato reale), oltre ai controlli di link/sintassi già in uso.
- Riscritto `Agente2_auto_prompt_v16.md` (sostituisce la v15): la sostanza progettuale — formule, normalizzazione categorie, regole della serie "Capiamo la Sabbia", badge, Top3, Mix Topic, Checklist — resta identica; cambiano solo le parti tecniche legate al contenitore (layout PptxGenJS→CSS responsive, convenzione colori hex, consegna via scrittura Supabase invece di `present_files`+upload Drive). Rimossa anche una regola che nella v15 esisteva solo per il vincolo di altezza fissa delle slide (scala adattiva delle righe stories), non più necessaria con una pagina che scorre liberamente.

**File consegnati/modificati:**
- `supabase/migrations/20261114_add_report_mensili.sql` (nuovo)
- `app/agenti/a2-analyst/report.html` (nuovo)
- `app/agenti/a2-analyst/page_agent_a2_v3.html` (modificato: card "Report mensili")
- `docs/prompts/Agente2_auto_prompt_v16.md` (nuovo, sostituisce `Agente2_auto_prompt_v15.md`)

---

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
