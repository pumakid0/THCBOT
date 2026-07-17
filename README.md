# ⚡ THCBOT v1.0 — Bitcoin as a Computer

Bot de Telegram para gestionar BSV, BTC, LTC, MNEE y EUR.  
Extensión Chrome para pagar con BSV en 9 tiendas sin tarjeta ni KYC.

---

## Stack

| Servicio     | Función                            | Coste         |
|--------------|------------------------------------|---------------|
| **Railway**  | Bot Telegram (polling)             | $5/mes Hobby  |
| **Vercel**   | API endpoints + frontend + crons   | Free (serverless) |
| **Supabase** | PostgreSQL                         | Free (500 MB) |
| **Telegram** | Bot API + Mini App                 | Gratis        |
| **CoinGecko**| Precios en tiempo real             | Gratis        |
| **CoinGate** | Gift cards digitales               | Por transacción|

---

## Estructura del proyecto

```
thcbot/
├── main.py                    # Railway — polling mode
├── requirements.txt
├── railway.toml
├── vercel.json
├── .env.example
│
├── api/
│   ├── handlers.py            # 23 comandos Telegram
│   ├── db.py                  # Database layer
│   ├── utils.py               # Tasas, parse_amount
│   ├── webhook.py             # Vercel — modo webhook alternativo
│   ├── balance.py             # GET /api/balance
│   ├── connect_extension.py   # POST /api/connect_extension
│   ├── buy_giftcard.py        # POST /api/buy_giftcard
│   ├── paylink.py             # GET/POST /api/paylink
│   ├── cron_cleanup.py        # Cron cada 5 min
│   └── cron_streams.py        # Cron cada 1 min
│
├── extension/                 # Extensión Chrome MV3
│   ├── manifest.json
│   ├── content/
│   │   ├── stores.js          # Registry 9 tiendas
│   │   ├── universal.js       # Injector universal
│   │   └── styles.css
│   ├── popup/
│   │   ├── popup.html
│   │   ├── popup.css
│   │   └── popup.js
│   ├── background/
│   │   └── service_worker.js
│   └── icons/
│
├── supabase_schema.sql        # Ejecutar en Supabase SQL Editor
├── extension.html             # Landing extensión
├── index.html                 # Landing principal
└── pay.html                   # Página paylinks
```

---

## Deploy en 5 pasos

### 1. Supabase
1. Crea proyecto en [supabase.com](https://supabase.com)
2. Ve a **SQL Editor → New query**
3. Pega el contenido de `supabase_schema.sql` y ejecuta
4. Copia la **Connection string** (Settings → Database → URI)

### 2. BotFather
1. Abre [@BotFather](https://t.me/BotFather)
2. `/newbot` → elige nombre y username
3. Copia el **token**
4. `/setcommands` → pega el contenido de `botfather_commands.txt`
5. `/setmenubutton` → URL: `https://thcbot.vercel.app/miniapp`

### 3. Variables de entorno
Crea un archivo `.env` basado en `.env.example`:
```bash
cp .env.example .env
# Edita con tus valores reales
```

### 4. Railway (bot polling)
```bash
# Instala Railway CLI
npm install -g @railway/cli

# Login y deploy
railway login
railway init
railway up

# Variables de entorno (en Railway Dashboard → Variables):
TELEGRAM_TOKEN=xxx
SUPABASE_URL=postgresql://...
OWNER_TG_ID=123456789
FRONTEND_URL=https://thcbot.vercel.app
```

### 5. Vercel (API + frontend)
```bash
# Instala Vercel CLI
npm install -g vercel

# Login y deploy
vercel login
vercel

# Variables de entorno (Vercel Dashboard → Settings → Environment Variables):
SUPABASE_URL       → postgresql://...
TELEGRAM_TOKEN     → tu_token
WEBHOOK_SECRET     → string_aleatorio
FRONTEND_URL       → https://thcbot.vercel.app
COINGATE_API_KEY   → tu_clave (vacío = modo demo)
OWNER_TG_ID        → 123456789
```

---

## Comandos del bot (23)

| Comando | Función |
|---------|---------|
| `/start` | Bienvenida y menú principal |
| `/help` | Lista de comandos |
| `/balance` | Saldo multi-asset con precios live |
| `/link paymail` | Vincular HandCash / RelayX |
| `/rate BSV` | Precio spot |
| `/pay 5 EUR @alice` | Enviar pago |
| `/pew 0.1 BSV` | A todos los activos |
| `/rain 1 BSV 10` | A 10 usuarios aleatorios |
| `/paylink 25 EUR Cena` | Crear enlace de cobro |
| `/mylinks` | Ver mis paylinks |
| `/seal texto` | Notaría BSV (hash SHA-256) |
| `/swap 0.1 BSV LTC` | Intercambiar assets |
| `/dice 0.01 BSV` | Dados — gana x1.9 |
| `/flip 0.01 BSV` | Cara/Cruz — gana x1.94 |
| `/rps 0.01 BSV` | Piedra Papel Tijera |
| `/leaderboard` | Top 10 BSV holders |
| `/stats` | Estadísticas globales |
| `/active` | Toggle rain/pew |
| `/stream @bob 0.000001 BSV` | Micropago/segundo |
| `/streamers` | Streams activos |
| `/fund` | Donar al proyecto |
| `/version` | Versión y stats |
| `/connect_extension` | Vincular extensión Chrome |

---

## Extensión Chrome — Tiendas soportadas

| Tienda | Dominios |
|--------|---------|
| 🛒 Amazon | .es .com .co.uk .de .fr .it .nl |
| 🎮 Steam | steampowered.com |
| 👟 Zalando | .es .com .de .fr .it .nl |
| 📺 MediaMarkt | .es .de .at .nl .be |
| 🎵 Fnac | .es .com .fr .pt .be |
| 🏬 El Corte Inglés | elcorteingles.es |
| 🎧 Spotify | spotify.com/premium |
| 🎮 PlayStation | store.playstation.com |
| 🟢 Xbox | xbox.com · microsoft.com |

---

## Licencia
MIT — Build on Bitcoin SV
