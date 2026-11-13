# Documento di Sessione — GDC IA TEAM

**Versione:** 3
**Ultimo aggiornamento:** 2026-11-13 15:49

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

**Stato:** da fare — urgente

**Obiettivo:** il rinnovo del token Instagram torna a funzionare prima della scadenza reale (non dopo), e A1 Stories Daily non segnala più "successo" quando in realtà non ha salvato nulla.

**Decisioni progettuali:**
- Il token è scaduto per davvero il 31/10/2026 — un token scaduto non si può rinnovare via refresh, serve un nuovo login manuale Meta da parte di Gianluca (passaggio che richiede browser, non automatizzabile da script).
- `ig_token_refresh.py` ha un bug di timing: il run del 2/11 si è attivato quando il token era già scaduto da "-1.9 giorni" — il margine di anticipo rispetto alla vera scadenza non è sufficiente. Da investigare la causa radice, non solo rigenerare il token.
- `a1_stories_daily.py`: un errore OAuth 400 viene interpretato come "nessuna story attiva" e lo script esce con successo — da quasi due settimane (inizio novembre) non vengono salvate stories, senza nessun alert perché il workflow risulta verde. Fix: distinguere l'errore OAuth da una lista vuota legittima.

**Criterio di completamento:** `ig_token_refresh.py` rinnova con margine sufficiente prima della scadenza; `a1_stories_daily.py` segnala (fallimento visibile) se riceve un errore di autenticazione, non lo confonde con "nessuna story".

**Note (cronologia dello step):**
- [2026-11-12] Trovato durante l'audit completo dei 10 GitHub Actions workflow del repo: `A1 Monthly` fallito il 2/11 (stesso token morto), `IG Token Refresh` fallito 2 volte consecutive (2/11, 9/11), `A1 Stories Daily` sempre verde ma silenziosamente inattivo da inizio mese. Audit ha anche rilevato che i workflow con cron frequente (ogni 30 min / ogni ora: `A1 MBS Watcher`, `Pipeline Watcher`) girano in realtà ogni 7-9 ore — limite di scheduling lato GitHub Actions sotto carico, non un bug nostro, solo da tenerne conto.

### Step 3 — Tassonomia DIVULGAZIONE

**Stato:** da fare

**Obiettivo:** la serie "Capiamo la Sabbia" ha una categoria primaria propria (DIVULGAZIONE) coerente su tutti i documenti/script che la leggono.

**Decisioni progettuali:**
- Trovata incongruenza reale tra i 4 prompt agente: A3 (v12) assume già l'esistenza di una categoria primaria DIVULGAZIONE; A1 (v4), A2 (v14) e A4 (v6) la classificano ancora come combinazione GDC STUFF (primaria) + SPORT (secondaria).
- Decisione di Gianluca: creare DIVULGAZIONE come quarta categoria primaria vera. Secondaria = GDC STUFF (per mantenere traccia del marchio sotto cui vive la serie).
- Beneficio collaterale: A2 e A4 oggi isolano la serie leggendo il nome del post via regex sulla caption — con la categoria dedicata possono filtrare direttamente sul campo categoria, più robusto.
- Vanno aggiornati: A1 (regola di classificazione automatica), A2 (sezioni che leggono/normalizzano categorie, slide/sezione serie), A4 (tabella categorie di riferimento). A3 non necessita modifiche.

**Criterio di completamento:** tutti e 4 i documenti/script concordano su DIVULGAZIONE come quarta categoria primaria; il riconoscimento della serie non dipende più dal solo nome del post.

**Note (cronologia dello step):**
- [2026-11-12] Decisione presa dopo discussione con Gianluca, inclusa correzione di un'inversione primaria/secondaria che Gianluca aveva scritto a parole ("Sport primaria, GDC Stuff secondaria") rispetto a quanto documentato in A1/A2/A4 (GDC STUFF primaria, SPORT secondaria) — chiarito che la documentazione corrente è quella corretta, resa comunque superata dalla nuova categoria dedicata.

### Step 4 — Schermata di categorizzazione post

**Stato:** da fare

**Obiettivo:** Gianluca categorizza i post del mese (oggi: celle gialle manuali in uno spreadsheet) da un'interfaccia comoda nella webapp, con suggerimento automatico.

**Decisioni progettuali:**
- Categoria primaria: elenco fisso (ora 4 valori incluso DIVULGAZIONE) + suggerimento di Claude + possibilità di modifica manuale.
- Categoria secondaria: menù a tendina filtrato per categoria primaria selezionata + suggerimento di Claude + possibilità di testo libero; ogni testo libero nuovo inserito si aggiunge al menù per le volte successive (vocabolario che cresce, non si fraziona in varianti).
- Vocabolario di partenza per la secondaria (estratto da A4 v6, sez. 2): SPORT → Torneo/Gara, Allenamento, Nazionale, Viaggio/Trasferta; RELATION → Coppia, Famiglia, Amici; GDC STUFF → Stampa 3D, Elettronica/Coding, Prodotto finito, Making of.
- Diventa un passaggio esplicito e visibile della pipeline (es. "Ottobre: 2 post da categorizzare"), non più invisibile come oggi — gate prima che A2 possa partire sensatamente.

**Criterio di completamento:** Gianluca può categorizzare un mese intero dalla webapp senza aprire lo spreadsheet; i valori usati si accumulano nel menù secondario nel tempo.

**Note (cronologia dello step):**
- Nessuna nota ancora — step discusso e deciso, non ancora iniziato.

### Step 5 — Schema Supabase + pagine HTML (dashboard A2, calendari A3/A4)

**Stato:** da fare

**Obiettivo:** A2, A3 e A4 (solo apertura mese) producono pagine HTML invece di pptx/pdf, con lo stesso contenuto/struttura/voce di oggi; il contenuto vero vive su Supabase protetto da login, i template sono pubblici su GitHub Pages.

**Decisioni progettuali:**
- Pagina cliccando il logo di A2: piccola dashboard con numeri/grafici che si riempiono mese per mese (stile GDC), letti da una tabella Supabase leggera e strutturata, separata dal contenuto narrativo del report.
- Pagine di A3/A4: niente grafici (non hanno dati numerici da rappresentare allo stesso modo) — un calendario/elenco semplice di mesi, ognuno con link al proprio documento.
- Il report/piano/brief aperto cliccando un mese resta lo stesso contenuto prodotto oggi — cambia solo il contenitore (HTML invece di pptx/pdf).
- Motivazione privacy: il repo GitHub è pubblico (verificato), quindi i template/shell HTML restano vuoti e pubblici; i dati veri (metriche, testo dei report) vivono in Supabase dietro lo stesso sistema di login/sessione già usato dal resto della webapp (stesso comportamento di scadenza token già presente).

**Criterio di completamento:** apertura di un mese passato mostra lo stesso contenuto che oggi è nel pptx/pdf corrispondente, ma come pagina HTML raggiungibile solo da sessione autenticata.

**Note (cronologia dello step):**
- Nessuna nota ancora — step discusso e deciso, non ancora iniziato. Ricevuti e letti integralmente i 4 prompt agente (A1 v4, A2 v14, A3 v12, A4 v6) come base per la ricostruzione fedele dei contenuti.

### Step 6 — Riorganizzazione cartelle GitHub

**Stato:** da fare — da svolgere insieme allo Step 5, non separatamente

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
