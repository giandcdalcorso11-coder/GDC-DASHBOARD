# Pannello per iPad (Spotify + orologio + pulsanti)

Pagina web pensata per **iPad Air 1 / iOS 12** (JavaScript ES5, nessuna funzione moderna).
Un piccolo server sul PC Windows la serve all'iPad via Wi-Fi.

## Installazione (una volta sola)
1. Sul PC installa **Python 3** da python.org (spunta "Add python.exe to PATH").
2. Copia questa cartella sul PC e fai doppio clic su `start.bat`.
3. Alla richiesta del firewall di Windows consenti l'accesso sulle **reti private**.
4. La finestra mostra l'indirizzo, es. `http://192.168.1.20:8080`. Aprilo in Safari sull'iPad (stessa Wi-Fi).

## Far partire il pannello da solo
- **PC:** premi Win+R, scrivi `shell:startup`, e metti lì un collegamento a `start_hidden.vbs`.
- **iPad:** in Safari tocca Condividi → *Aggiungi a Home*, così si apre a schermo intero senza barre.
  - Impostazioni → Schermo e luminosità → **Blocco automatico: Mai**.
  - Impostazioni → Generali → Accessibilità → **Accesso Guidato** (attivalo, poi triplo clic su Home
    nel pannello): l'iPad resta bloccato sul pannello e i tocchi involontari fuori dalla pagina non fanno nulla.
- iOS non permette di aprire un'app in automatico all'accensione: se riavvii l'iPad devi toccare
  l'icona una volta. Finché resta acceso e in carica, il pannello rimane aperto e si ricollega da solo
  quando il PC si riaccende.

## Pulsanti personalizzabili
Modifica `buttons.json` (si ricarica da solo, l'iPad si aggiorna in pochi secondi). Ogni pulsante:
`id` unico, `label`, `icon` (emoji), `color`, e un'`action`:

| type | esempio |
|---|---|
| `hotkey` | `{ "type": "hotkey", "keys": "ctrl+shift+m" }` (tasti: lettere, cifre, f1-f24, ctrl, shift, alt, win, enter, esc, frecce...) |
| `media` | `{ "type": "media", "cmd": "playpause" }` (playpause, next, prev, mute, volup, voldown) |
| `url` | `{ "type": "url", "url": "https://..." }` (solo http/https) |
| `run` | `{ "type": "run", "path": "C:\\Programmi\\App\\app.exe", "args": [] }` |
| `lock` | `{ "type": "lock" }` blocca Windows |

L'iPad può eseguire solo i pulsanti scritti in questo file, mai comandi arbitrari.
Chiunque sia sulla tua Wi-Fi può però aprire la pagina: per proteggerla metti una parola in
`"token"` dentro `settings` e apri `http://IP:8080/?t=LA-TUA-PAROLA`.

## Come funziona e limiti
- **Spotify:** titolo e artista si leggono dal titolo della finestra di Spotify sul PC, quindi l'app
  deve essere aperta (anche ridotta). Non c'è la copertina. I tasti usano i tasti multimediali di
  Windows: agiscono sul player attivo, che potrebbe non essere Spotify se è partito altro (es. un video).
- **Volume:** è il volume di sistema del PC.
- **Luminosità:** tocca l'orologio per attenuare lo schermo (3 livelli).
- Scritto e provato su Linux in modalità simulata; **le parti Windows (lettura di Spotify, tasti) non sono
  ancora state provate su un PC Windows vero**.
