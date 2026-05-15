# Alpaca Swing Trading Bot

Bot Python autonomo per swing trading su ETF USA (SPY, QQQ, IWM) tramite Alpaca,
con notifiche Telegram in tempo reale. Gira 24/7 in background e opera solo
negli orari di mercato USA.

---

## Indice

1. [Aprire un account Alpaca](#1-aprire-un-account-alpaca)
2. [Generare le API key](#2-generare-le-api-key)
3. [Creare il bot Telegram](#3-creare-il-bot-telegram-con-botfather)
4. [Ottenere il CHAT_ID](#4-ottenere-il-proprio-chat_id)
5. [Installazione](#5-installazione)
6. [Avviare il bot](#6-avviare-il-bot)
7. [Eseguire i test](#7-eseguire-i-test)
8. [Background su Linux (systemd)](#8-girare-in-background-su-linux-con-systemd)
9. [Background su Windows (Task Scheduler)](#9-girare-su-windows-con-task-scheduler)
10. [Paper vs Live trading](#10-differenza-tra-paper-trading-e-live-trading)
11. [Nota su residenza USA](#11-nota-su-residenza-usa-e-trading-live)
12. [Strategia](#12-strategia)
13. [Notifiche Telegram](#13-notifiche-telegram)
14. [Struttura del progetto](#14-struttura-del-progetto)

---

## 1. Aprire un account Alpaca

1. Vai su [alpaca.markets](https://alpaca.markets) e clicca **Sign Up**.
2. Compila i dati e verifica l'email.
3. Per il **paper trading** (simulazione, consigliato per iniziare) non è richiesta
   alcuna verifica d'identità: puoi operare subito.
4. Per il **live trading** Alpaca richiede residenza USA oppure l'apertura tramite
   un broker partner (vedi nota in fondo).

---

## 2. Generare le API key

1. Accedi alla dashboard Alpaca.
2. In alto a destra seleziona **Paper Trading** oppure **Live Trading** in base
   all'ambiente che vuoi usare.
3. Vai su **Overview → API Keys → Generate New Key**.
4. Copia subito la **Key ID** e il **Secret Key**: il secret non viene mostrato
   di nuovo dopo la prima visualizzazione.
5. Incolla i valori nel file `.env` (vedi sezione installazione).

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

## 5. Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# oppure: .venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

Copia `.env.example` in `.env` e compila i valori:

```bash
cp .env.example .env
nano .env
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

All'avvio il bot:
- Invia su Telegram la conferma di avvio.
- Esegue subito il primo ciclo di analisi.
- Poi si ripete ogni ora (alle `:00`, `:25` e `:55`).

Comportamento per orario:

| Orario ET | Azione |
|---|---|
| 09:25 | Briefing pre-mercato su Telegram |
| 09:30–15:00 | Ciclo di analisi attivo, ordini consentiti |
| 15:00–16:00 | Ciclo attivo, nessun nuovo ingresso |
| 16:00 | Report chiusura giornata su Telegram |
| Fuori orario / weekend | Bot attivo, silenzioso (una sola notifica `😴` per chiusura) |

I log vengono scritti su terminale e su `bot.log` con rotazione automatica a 7 giorni.

---

## 7. Eseguire i test

La suite copre tutti i moduli senza chiamate reali ad Alpaca o Telegram:

```bash
pytest test_bot.py -v
```

Output atteso: **60 test, 0 fallimenti**.

| Classe di test | Modulo testato | N. test |
|---|---|---|
| `TestMarketHours` | `market_hours.py` | 17 |
| `TestPositionManager` | `position_manager.py` | 7 |
| `TestRiskManager` | `risk_manager.py` | 16 |
| `TestStrategy` | `strategy.py` | 9 |
| `TestTelegramNotify` | `telegram_notify.py` | 11 |

---

## 8. Girare in background su Linux con systemd

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
# EnvironmentFile=/percorso/assoluto/alpaca-bot/.env

[Install]
WantedBy=multi-user.target
```

Sostituisci `<tuo_utente>` e i percorsi con i tuoi valori, poi:

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot

sudo systemctl status trading-bot   # verifica stato
sudo journalctl -u trading-bot -f   # segui i log
```

---

## 9. Girare su Windows con Task Scheduler

1. Apri **Task Scheduler** → **Crea attività** (non "attività di base").
2. Scheda **Generale**: nome `TradingBot`, spunta *Esegui che l'utente sia connesso o meno* e *Esegui con i privilegi più elevati*.
3. Scheda **Trigger** → Nuovo → Avvia l'attività: **All'avvio**.
4. Scheda **Azioni** → Nuova:
   - Programma: `C:\percorso\.venv\Scripts\python.exe`
   - Argomenti: `bot.py`
   - Inizia in: `C:\percorso\alpaca-bot`
5. Scheda **Impostazioni**: spunta *Riavvia l'attività se si interrompe* ogni 5 minuti.
6. Clicca OK e inserisci la password di Windows.

```powershell
Get-Process python   # verifica che il bot sia in esecuzione
```

---

## 10. Differenza tra paper trading e live trading

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

## 11. Nota su residenza USA e trading live

Alpaca Markets richiede **residenza negli Stati Uniti** per aprire un conto live
direttamente su alpaca.markets.

Opzioni per residenti fuori dagli USA:
- Usare il **paper trading** (nessuna restrizione geografica).
- Aprire tramite un **broker partner** Alpaca che supporta clienti internazionali
  (lista aggiornata su alpaca.markets/brokers).
- Valutare broker alternativi con API compatibili (Interactive Brokers, Tastytrade)
  e adattare `alpaca_client.py`.

> **Disclaimer**: questo bot è fornito a scopo educativo. Il trading di strumenti
> finanziari comporta rischi significativi di perdita del capitale. Non costituisce
> consulenza finanziaria. Testa sempre in paper trading prima di usare denaro reale.

---

## 12. Strategia

### Asset e allocazione

| Asset | Indice | Allocazione |
|---|---|---|
| SPY | S&P 500 | 50% |
| QQQ | Nasdaq 100 | 30% |
| IWM | Russell 2000 | 20% |

Timeframe: candele **1h**. Capitale configurabile (default $100).

### Indicatori

| Indicatore | Parametri | Uso |
|---|---|---|
| RSI | 14 periodi | Zona buy 35–50, sell >72 |
| EMA | 20 / 50 / 200 | Trend e filtro direzione |
| MACD | 12, 26, 9 | Momentum e crossover |
| Volume | Media 20 periodi | Conferma forza del movimento |
| VWAP | Anchor giornaliero | Filtro istituzionale — close deve essere sopra |

### Criteri BUY (tutti devono essere veri)

- RSI tra 35 e 50
- Close > EMA50
- MACD histogram > 0 oppure crossover bullish nell'ultima candela
- Volume > media 20 periodi × 1.3
- Close > VWAP giornaliero
- Mercato aperto, non nell'ultima ora (15:00–16:00 ET)

### Criteri SELL (basta uno)

- Close ≤ Stop loss (–3% dall'entry)
- RSI > 72
- Divergenza bearish MACD
- TP1 raggiunto (+4%) → chiude 50%, sposta SL al breakeven, apre TP2
- TP2 raggiunto (+8%) → chiude il restante 50%

### Gestione del rischio

| Regola | Valore |
|---|---|
| Stop loss | –3% dall'entry |
| Take profit 1 | +4% (chiude 50%) |
| Take profit 2 | +8% (chiude il restante) |
| Allocazione per asset | 50% / 30% / 20% del capitale |
| Max posizioni simultanee | 1 per asset |
| Cooldown dopo chiusura | 2 ore |
| Pausa dopo SL consecutivi | 2 SL → stop fino al giorno successivo |
| No nuovi ingressi | Ultima ora (15:00–16:00 ET) |
| No nuovi ingressi | Venerdì dopo le 14:00 ET |
| Posizioni overnight | Consentite solo se close > EMA200 daily |
| VIX proxy | Se SPY scende >1.5% in 1h → nessun ingresso |

### Esecuzione ordini

- Ordini **bracket nativi Alpaca**: un singolo ordine apre la posizione con SL e TP1 simultanei.
- Prezzo limit = ask + $0.01 per favorire l'esecuzione rapida.
- Se l'ordine non si esegue entro **5 minuti**: cancella e riprova con il prezzo aggiornato.
- Usa **fractional shares** per rispettare l'allocazione esatta anche con capitali piccoli.
- Commissioni: $0.00 (Alpaca zero-fee).

---

## 13. Notifiche Telegram

### Tabella messaggi

| Momento | Messaggio |
|---|---|
| Avvio bot | Conferma avvio + asset monitorati |
| 09:25 ET | Briefing pre-mercato |
| Ogni ora (mercato aperto) | Riepilogo ciclo di analisi |
| Prima chiusura rilevata | Notifica mercato chiuso (poi silenzio) |
| Ordine inviato | Dettagli limit order + SL/TP automatici |
| Ordine eseguito | Conferma posizione aperta + indicatori |
| TP1 raggiunto | Vendita parziale, SL al breakeven, TP2 aperto |
| TP2 raggiunto | Chiusura completa con profitto |
| Stop loss | Chiusura con perdita + contatore SL |
| 2 SL consecutivi | Alert pausa fino al giorno successivo |
| 16:00 ET | Report chiusura giornata |
| Errore non gestito | Notifica immediata con descrizione |

### Riepilogo ciclo orario

Messaggio inviato al termine di ogni ciclo a mercato aperto:

```
🔍 Analisi 11:00 ET
━━━━━━━━━━━━━━━
SPY ⚪ HOLD
  💲 $528.40 | RSI 55.2 | Vol 0.9x ❌
  EMA50 $512.30 (+3.1%) ✅
  VWAP $525.10 (+0.6%) ✅
  MACD +0.0821 ✅

QQQ 🟢 BUY
  💲 $441.20 | RSI 44.8 | Vol 1.6x ✅
  EMA50 $435.10 (+1.4%) ✅
  VWAP $438.90 (+0.5%) ✅
  MACD +0.1243 ✅

IWM 🔵 BUY bloccato
  💲 $198.30 | RSI 39.1 | Vol 1.4x ✅
  EMA50 $195.80 (+1.3%) ✅
  VWAP $197.50 (+0.4%) ✅
  MACD +0.0314 ✅
  📍 Pos: +0.82% | SL $192.35 | TP1 $206.23
  ↳ cooldown 2h: ancora 47 minuti
━━━━━━━━━━━━━━━
💼 Capitale: $101.44
📈 P&L oggi: +$1.44 (+1.44%)
🕐 Close tra: 4h 58m
```

**Legenda segnale:**

| Icona | Significato |
|---|---|
| 🟢 BUY | Tutti i criteri soddisfatti, ordine in corso |
| 🔵 BUY bloccato | Segnale valido ma bloccato da una regola di rischio |
| 🔴 SELL | Segnale di vendita attivato |
| ⚪ HOLD | Nessun segnale operativo |

**Campi per ogni asset:**

| Campo | Descrizione |
|---|---|
| Prezzo | Ultimo close candela 1h |
| RSI | RSI(14) — zona buy 35–50, sell >72 |
| Volume | Moltiplicatore vs media 20 periodi (soglia ≥1.3x) |
| EMA50 | Valore + distanza % dal prezzo corrente |
| VWAP | Valore giornaliero + distanza % dal prezzo corrente |
| MACD | Valore histogram (positivo = bullish) |
| Posizione | P&L non realizzato + livelli SL e TP1/TP2 attivi |

**Footer del messaggio:**

| Campo | Descrizione |
|---|---|
| Capitale | Valore corrente portafoglio da Alpaca |
| P&L oggi | Variazione vs capitale iniziale configurato |
| Close tra | Countdown alla chiusura del mercato (16:00 ET) |

---

## 14. Struttura del progetto

```
alpaca-bot/
├── bot.py               # Entry point — loop orario, orchestrazione cicli
├── strategy.py          # Indicatori (RSI, EMA, MACD, VWAP) e segnali BUY/SELL
├── alpaca_client.py     # Wrapper alpaca-py: dati storici, ordini, clock
├── telegram_notify.py   # Tutti i messaggi Telegram
├── position_manager.py  # CRUD su positions.json
├── order_manager.py     # Bracket orders, polling fill, gestione TP/SL
├── risk_manager.py      # Sizing, pausa, regole orario e overnight
├── market_hours.py      # Fuso orario ET, festività NYSE 2025-2026
├── test_bot.py          # Suite 60 test (pytest) — nessuna chiamata reale
├── .env                 # Configurazione locale (non committare)
├── .env.example         # Template configurazione
├── requirements.txt     # Dipendenze Python
├── positions.json       # Stato posizioni (generato automaticamente)
├── risk_state.json      # Contatore SL e stato pausa (generato automaticamente)
└── bot.log              # Log rotante 7 giorni (generato automaticamente)
```
