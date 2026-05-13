# Alpaca Swing Trading Bot

Bot Python autonomo per swing trading su ETF USA (SPY, QQQ, IWM) tramite Alpaca,
con notifiche Telegram in tempo reale.

---

## 1. Aprire un account Alpaca

1. Vai su [alpaca.markets](https://alpaca.markets) e clicca **Sign Up**.
2. Compila i dati e verifica l'email.
3. Per il **paper trading** (simulazione, consigliato per iniziare) non è richiesta
   alcuna verifica d'identità: puoi operare subito.
4. Per il **live trading** Alpaca richiede residenza USA oppure l'apertura tramite
   un broker partner (vedi nota in fondo). Se sei residente fuori dagli USA,
   verifica la tua eligibilità prima di passare al live.

---

## 2. Generare le API key

1. Accedi alla dashboard Alpaca.
2. In alto a destra seleziona **Paper Trading** oppure **Live Trading** in base
   all'ambiente che vuoi usare.
3. Vai su **Overview → API Keys → Generate New Key**.
4. Copia subito la **Key ID** e il **Secret Key**: il secret non viene mostrato
   di nuovo dopo la prima visualizzazione.
5. Incolla i valori nel file `.env` (vedi sotto).

> **Paper vs Live**: i due ambienti hanno URL diversi e API key separate.
> Non mischiare le chiavi.

---

## 3. Creare il bot Telegram con @BotFather

1. Apri Telegram e cerca `@BotFather`.
2. Invia il comando `/newbot`.
3. Scegli un **nome** (es. `Il Mio Trading Bot`) e uno **username** che termina
   in `bot` (es. `mio_trading_bot`).
4. BotFather risponde con il **token** (formato `123456789:ABCdef...`).
   Copialo in `TELEGRAM_BOT_TOKEN` nel file `.env`.

---

## 4. Ottenere il proprio CHAT_ID

1. Avvia una conversazione con il tuo bot su Telegram (invia `/start`).
2. Apri nel browser l'URL:
   ```
   https://api.telegram.org/bot<IL_TUO_TOKEN>/getUpdates
   ```
3. Nella risposta JSON cerca il campo `"chat"` → `"id"`.
   Quel numero è il tuo `CHAT_ID`.
4. Copialo in `TELEGRAM_CHAT_ID` nel file `.env`.

> Se il JSON è vuoto, invia un altro messaggio al bot e ricarica la pagina.

---

## 5. Installazione dipendenze

```bash
# Clona o copia la cartella del progetto, poi:
cd alpaca-bot
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# oppure: .venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

Copia `.env.example` in `.env` e compila i valori:

```bash
cp .env.example .env
nano .env   # oppure usa l'editor che preferisci
```

```env
ALPACA_API_KEY=la_tua_chiave
ALPACA_API_SECRET=il_tuo_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TELEGRAM_BOT_TOKEN=il_tuo_token
TELEGRAM_CHAT_ID=il_tuo_chat_id
CAPITALE_TOTALE=100
RISCHIO_PER_TRADE=0.015
PAPER_TRADING=true
```

---

## 6. Avviare il bot

```bash
python bot.py
```

Il bot:
- Invia un messaggio Telegram di avvio.
- Esegue subito il primo ciclo di analisi.
- Poi gira ogni ora (alle :00, :25 e :55) finché non viene fermato con Ctrl+C.
- Opera **solo** nei giorni e negli orari di mercato USA (Lun–Ven 09:30–16:00 ET).
- Alle 09:25 ET invia il briefing pre-mercato, alle 16:00 il report di chiusura.

I log vengono scritti sia su terminale che su `bot.log` (rotazione 7 giorni).

---

## 7. Girare in background su Linux con systemd

Crea il file `/etc/systemd/system/trading-bot.service`:

```ini
[Unit]
Description=Alpaca Swing Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<tuo_utente>
WorkingDirectory=/percorso/assoluto/alpaca-bot
ExecStart=/percorso/assoluto/alpaca-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
# Variabili d'ambiente (alternativa al file .env)
# EnvironmentFile=/percorso/assoluto/alpaca-bot/.env

[Install]
WantedBy=multi-user.target
```

Sostituisci `<tuo_utente>` e i percorsi con i tuoi valori reali, poi:

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot

# Verifica stato
sudo systemctl status trading-bot

# Leggi i log
sudo journalctl -u trading-bot -f
```

---

## 8. Girare su Windows con Task Scheduler

1. Apri **Task Scheduler** (cerca "Utilità di pianificazione" nel menu Start).
2. Clicca **Crea attività** (non "Crea attività di base").
3. Scheda **Generale**:
   - Nome: `TradingBot`
   - Spunta **Esegui che l'utente sia connesso o meno**
   - Spunta **Esegui con i privilegi più elevati**
4. Scheda **Trigger** → Nuovo:
   - Avvia l'attività: **All'avvio**
5. Scheda **Azioni** → Nuova:
   - Azione: **Avvia un programma**
   - Programma: `C:\percorso\alpaca-bot\.venv\Scripts\python.exe`
   - Argomenti: `bot.py`
   - Inizia in: `C:\percorso\alpaca-bot`
6. Scheda **Impostazioni**:
   - Spunta **Riavvia l'attività se si interrompe** ogni 5 minuti, per un massimo di 3 tentativi.
7. Clicca OK e inserisci la password di Windows quando richiesto.

Per verificare che il bot sia in esecuzione:

```powershell
Get-Process python
# oppure controlla bot.log nella cartella del progetto
```

---

## 9. Differenza tra paper trading e live trading

| Caratteristica | Paper Trading | Live Trading |
|---|---|---|
| URL API | `paper-api.alpaca.markets` | `api.alpaca.markets` |
| Denaro reale | No (simulato) | Sì |
| Commissioni | No | No (Alpaca zero-fee) |
| API Key | Separate (generate in env Paper) | Separate (generate in env Live) |
| Eligibilità | Tutti | Residenti USA o broker partner |
| Consigliato per iniziare | Sì | Solo dopo test approfonditi |

Per passare al live: cambia `ALPACA_BASE_URL` e le API key nel `.env`.

---

## 10. Nota su residenza USA e trading live

Alpaca Markets richiede che gli utenti siano **residenti negli Stati Uniti**
per aprire un conto live direttamente su alpaca.markets.

Se sei residente fuori dagli USA (es. Italia), hai alcune opzioni:
- Usare il **paper trading** (nessuna restrizione geografica).
- Aprire un conto tramite uno dei **broker partner** di Alpaca che supportano
  clienti internazionali (verifica la lista aggiornata su alpaca.markets/brokers).
- Valutare broker alternativi che espongono API compatibili (Interactive Brokers,
  Tastytrade, ecc.) e adattare `alpaca_client.py` di conseguenza.

> **Disclaimer**: questo bot è fornito a scopo educativo. Il trading di strumenti
> finanziari comporta rischi significativi. Non è una consulenza finanziaria.
> Testa sempre in paper trading prima di usare denaro reale.

---

## Struttura del progetto

```
alpaca-bot/
├── bot.py               # Entry point, loop orario
├── strategy.py          # RSI, EMA, MACD, segnali BUY/SELL
├── alpaca_client.py     # Wrapper alpaca-py (dati + ordini)
├── telegram_notify.py   # Tutti i messaggi Telegram
├── position_manager.py  # Lettura/scrittura positions.json
├── order_manager.py     # Bracket orders, polling, TP/SL
├── risk_manager.py      # Sizing, pausa, regole orario
├── market_hours.py      # Fuso orario ET, festività NYSE
├── .env                 # Configurazione (non committare!)
├── .env.example         # Template configurazione
├── requirements.txt     # Dipendenze Python
├── positions.json       # Stato posizioni (generato automaticamente)
├── risk_state.json      # Stato pausa/SL consecutivi (generato automaticamente)
└── bot.log              # Log rotante 7 giorni (generato automaticamente)
```
