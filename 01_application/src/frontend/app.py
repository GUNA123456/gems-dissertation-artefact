"""
StyleHub - Storefront Web App Gateway
Clean FastAPI Storefront app communicating with microservices via HTTP REST APIs.
Features: Search, Category Filters, Product Details + Quantity Selector, Recommendations,
Cart Item Removal, Quantity Adjustments, Shipping & Payment Checkout Forms.
"""

from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os, sys, time, logging, requests

# ─────────────────────────────────────────────────────────────────────────────
# Root cause fix: Uvicorn's default keep-alive timeout is 5s. After 5s idle,
# the backend closes the TCP socket. Our session pool still holds a reference
# to that dead socket. Next request → ConnectionResetError(104, 'Connection
# reset by peer'). Fix: HTTPAdapter with connect=3 / read=3 retries so urllib3
# detects the dead socket and transparently opens a fresh connection.
# ─────────────────────────────────────────────────────────────────────────────
_retry = Retry(
    total=3,          # max total retries
    connect=3,        # retries on new-connection failures
    read=3,           # retries on read/reset errors (covers errno 104)
    backoff_factor=0.1,              # 0.1s, 0.2s, 0.4s between retries
    status_forcelist=[500, 502, 503, 504],
    raise_on_status=False,
)
_adapter = HTTPAdapter(
    max_retries=_retry,
    pool_connections=10,   # number of host connection pools
    pool_maxsize=20,       # connections per pool
    pool_block=False,
)
_session = requests.Session()
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)
_executor = ThreadPoolExecutor(max_workers=8)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Frontend")

app = FastAPI(title="StyleHub Storefront")

# Microservice Endpoints
PRODUCT_CATALOG_URL = os.getenv("PRODUCT_CATALOG_SERVICE_URL", os.getenv("PRODUCT_CATALOG_URL", "http://localhost:8081"))
CART_URL = os.getenv("CART_SERVICE_URL", os.getenv("CART_URL", "http://localhost:8082"))
CURRENCY_URL = os.getenv("CURRENCY_SERVICE_URL", os.getenv("CURRENCY_URL", "http://localhost:8083"))
RECOMMENDATION_URL = os.getenv("RECOMMENDATION_SERVICE_URL", os.getenv("RECOMMENDATION_URL", "http://localhost:8084"))
SHIPPING_URL = os.getenv("SHIPPING_SERVICE_URL", os.getenv("SHIPPING_URL", "http://localhost:8085"))
CHECKOUT_URL = os.getenv("CHECKOUT_SERVICE_URL", os.getenv("CHECKOUT_URL", "http://localhost:8086"))
AD_URL = os.getenv("AD_SERVICE_URL", os.getenv("AD_URL", "http://localhost:8087"))

# Phase 4 timeout policy: two documented tiers replace the former 1.5/2/3/5s scatter,
# which made every cascade's latency signature an accident of whichever call site it
# crossed. TIMEOUT_S bounds any single dependency call. ORCH_TIMEOUT_S bounds the one
# call into the checkout orchestrator, and must exceed checkout's worst-case sequential
# chain (~5 dependency calls) or the frontend gives up before checkout can report WHICH
# dependency failed — turning a named 502 into an anonymous ReadTimeout.
TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_SECONDS", "2"))
ORCH_TIMEOUT_S = float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "10"))

import obs  # /metrics + dependency-edge counters + optional OTel tracing (Phase 1)
obs.install(app, "stylehub-frontend", dependencies={
    "product-catalog": PRODUCT_CATALOG_URL, "cart": CART_URL, "currency": CURRENCY_URL,
    "recommendation": RECOMMENDATION_URL, "shipping": SHIPPING_URL,
    "checkout": CHECKOUT_URL, "ad": AD_URL,
})

TOP_TICKER = """
<div style="background: linear-gradient(90deg, #ea580c, #f97316); color: white; text-align: center; padding: 0.5rem 1rem; font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;">
    🚚 FREE SHIPPING ON ALL ORDERS OVER $50 • USE CODE <span style="text-decoration: underline;">STYLEHUB2026</span>
</div>
"""

FOOTER_HTML = """
<footer style="background:#f8fafc; color:#64748b; text-align:center; padding:2.5rem 1rem; margin-top:4rem; border-top:1px solid #e2e8f0; font-size:0.9rem;">
    <p>© 2026 StyleHub Microservices | Built with Python FastAPI, Docker & Kubernetes</p>
</footer>
"""

HTML_LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | StyleHub Storefront</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin:0; padding:0; font-family: 'Inter', sans-serif; }}
        body {{ background: #ffffff; color: #0f172a; min-height: 100vh; display: flex; flex-direction: column; }}
        header {{ background: #ffffff; border-bottom: 1px solid #e2e8f0; sticky: top; z-index: 50; padding: 1rem 2rem; }}
        .header-inner {{ max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }}
        .logo {{ font-size: 1.6rem; font-weight: 800; color: #0f172a; text-decoration: none; display: flex; align-items: center; letter-spacing: -0.03em; }}
        .logo span {{ color: #ea580c; }}
        .search-form {{ display: flex; flex: 1; max-width: 400px; }}
        .search-input {{ flex: 1; border: 1px solid #cbd5e1; padding: 0.5rem 0.9rem; border-radius: 0.5rem 0 0 0.5rem; font-size: 0.9rem; outline: none; }}
        .search-btn {{ background: #ea580c; color: white; border: none; padding: 0.5rem 1rem; border-radius: 0 0.5rem 0.5rem 0; font-weight: 700; cursor: pointer; }}
        .nav {{ display: flex; align-items: center; gap: 1rem; }}
        .btn {{ background: #ea580c; color: white; border: none; padding: 0.6rem 1.25rem; border-radius: 0.5rem; font-weight: 700; text-decoration: none; cursor: pointer; text-align: center; transition: background 0.2s; }}
        .btn:hover {{ background: #c2410c; }}
        .btn-outline {{ background: #f8fafc; color: #0f172a; border: 1px solid #cbd5e1; }}
        .btn-outline:hover {{ background: #e2e8f0; }}
        .btn-danger {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; padding: 0.35rem 0.75rem; border-radius: 0.4rem; font-size: 0.8rem; font-weight: 700; cursor: pointer; }}
        .btn-danger:hover {{ background: #fecaca; }}
        .qty-btn {{ background: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; width: 28px; height: 28px; border-radius: 0.25rem; font-weight: 800; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }}
        .qty-btn:hover {{ background: #e2e8f0; }}
        .container {{ max-width: 1200px; margin: 2rem auto; padding: 0 1.5rem; flex: 1; width: 100%; }}
        .product-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1.75rem; margin-top: 1.5rem; }}
        .card {{ background: white; border-radius: 0.75rem; padding: 1.5rem; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: transform 0.2s, box-shadow 0.2s; display: flex; flex-direction: column; justify-content: space-between; }}
        .card:hover {{ transform: translateY(-3px); box-shadow: 0 10px 25px -5px rgba(234, 88, 12, 0.12); border-color: #fdba74; }}
        .ad-banner {{ background: #fff7ed; border: 1px solid #ffedd5; border-radius: 0.75rem; padding: 0.9rem 1.5rem; margin-bottom: 1.5rem; color: #c2410c; font-weight: 600; text-align: center; }}
        .cat-bar {{ display: flex; gap: 0.5rem; margin-top: 1rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.75rem; overflow-x: auto; }}
        .cat-tab {{ padding: 0.4rem 1rem; border-radius: 0.5rem; font-weight: 600; font-size: 0.875rem; text-decoration: none; color: #64748b; background: #f1f5f9; }}
        .cat-tab.active {{ background: #ea580c; color: white; }}
        .sku-tag {{ font-size: 0.75rem; font-weight: 700; color: #64748b; background: #f1f5f9; padding: 0.2rem 0.5rem; border-radius: 0.25rem; font-family: monospace; display: inline-block; margin-bottom: 0.4rem; }}
    </style>
</head>
<body>
    {top_ticker}
    <header>
        <div class="header-inner">
            <a href="/" class="logo">🛍️ StyleHub<span>.</span></a>
            
            <form action="/" method="get" class="search-form">
                <input type="text" name="q" value="{search_query}" placeholder="Search jacket, hoodie, sneakers..." class="search-input">
                <button type="submit" class="search-btn">Search</button>
            </form>

            <div class="nav">
                <form action="/set-currency" method="post" style="margin:0;">
                    <select name="currency_code" onchange="this.form.submit()" style="padding:0.45rem 0.75rem; border-radius:0.5rem; font-weight:700; border:1px solid #cbd5e1; background:#f8fafc; cursor:pointer;">
                        <option value="USD" {usd_sel}>🇺🇸 USD</option>
                        <option value="EUR" {eur_sel}>🇪🇺 EUR</option>
                        <option value="GBP" {gbp_sel}>🇬🇧 GBP</option>
                        <option value="JPY" {jpy_sel}>🇯🇵 JPY</option>
                        <option value="CAD" {cad_sel}>🇨🇦 CAD</option>
                        <option value="INR" {inr_sel}>🇮🇳 INR</option>
                    </select>
                </form>
                <a href="/cart" class="btn btn-outline">🛒 Cart <span style="background:#ea580c; color:white; font-size:0.75rem; padding:0.1rem 0.4rem; border-radius:9999px; margin-left:0.2rem;">{cart_count}</span></a>
            </div>
        </div>
    </header>

    <div class="container">
        {ad_banner}
        {content}
    </div>
    {footer}
</body>
</html>
"""

# Helper Functions — using session for connection pooling & 1.5s timeout
def _get_cart_items(user_id: str = "user-demo-123") -> list:
    try:
        res = _session.get(f"{CART_URL}/api/cart/{user_id}", timeout=TIMEOUT_S).json()
        return res.get("items", [])
    except Exception: return []

def _get_cart_count(user_id: str = "user-demo-123") -> int:
    return sum(item.get("quantity", 1) for item in _get_cart_items(user_id))

def _get_ads(category: str = "clothing") -> str:
    try:
        res = _session.post(f"{AD_URL}/api/ads", json=[category], timeout=TIMEOUT_S).json()
        ads = res.get("ads", [])
        if ads: return f'<div class="ad-banner">📢 {ads[0]["text"]}</div>'
    except Exception: pass
    return ""

# N+1 fix (Phase 1): Round 1 made one HTTP call to currency-service PER PRICE rendered —
# a homepage with N products issued N sequential conversions, putting the storefront's
# NORMAL latency at ~745 ms against ~90 ms for every other service. That noise floor is
# what made a flat latency SLO fire on 100% of normal traffic. Now the full rate table is
# fetched once and cached for RATES_TTL; each price converts locally. The
# frontend->currency edge stays alive (one call per TTL per pod), so currency-service
# faults remain observable — at the cache boundary instead of on every price.
RATES_TTL_SECONDS = 30.0
_rates_cache = {"rates": None, "fetched_at": 0.0}

def _get_rates():
    now = time.time()
    if now - _rates_cache["fetched_at"] > RATES_TTL_SECONDS:
        _rates_cache["fetched_at"] = now  # even on failure: don't hammer a dead service
        try:
            res = _session.get(f"{CURRENCY_URL}/api/currency/rates", timeout=TIMEOUT_S)
            res.raise_for_status()
            _rates_cache["rates"] = res.json().get("rates", {})
        except Exception as e:
            logger.warning(f"currency rates refresh failed ({type(e).__name__}); serving USD")
            _rates_cache["rates"] = None
    return _rates_cache["rates"]

def _convert_price(units: int, nanos: int, to_code: str) -> str:
    if to_code == "USD": return f"${units}.00 USD"
    rates = _get_rates()
    if not rates or to_code not in rates:
        return f"${units}.00 USD"
    converted = (units + nanos / 1e9) * rates[to_code]
    return f"{int(converted)} {to_code}"

@app.get("/healthz")
def health(): return {"status": "ok", "service": "frontend"}

@app.post("/set-currency")
def set_currency(currency_code: str = Form(...)):
    res = RedirectResponse(url="/", status_code=303)
    res.set_cookie(key="user_currency", value=currency_code)
    return res

@app.get("/", response_class=HTMLResponse)
def index_page(request: Request, q: str = "", category: str = "all"):
    user_currency = request.cookies.get("user_currency", "USD")

    # ⚡ Fire all 3 backend calls in parallel — each has its own 1.5s timeout
    catalog_url = f"{PRODUCT_CATALOG_URL}/api/products/search?q={q}" if q else f"{PRODUCT_CATALOG_URL}/api/products"
    future_cart    = _executor.submit(_session.get,  f"{CART_URL}/api/cart/user-demo-123", timeout=TIMEOUT_S)
    future_ads     = _executor.submit(_session.post, f"{AD_URL}/api/ads", json=[category if category != 'all' else 'clothing'], timeout=TIMEOUT_S)
    future_catalog = _executor.submit(_session.get,  catalog_url, timeout=TIMEOUT_S)

    # Gather results — individual timeouts act as safety nets, no global deadline to crash on
    cart_count, ad_html, products, products_error = 0, "", [], None

    try:
        data = future_cart.result(timeout=TIMEOUT_S + 0.5)
        cart_count = sum(i.get("quantity", 1) for i in data.json().get("items", []))
    except Exception:
        pass

    try:
        data = future_ads.result(timeout=TIMEOUT_S + 0.5)
        ads = data.json().get("ads", [])
        if ads: ad_html = f'<div class="ad-banner">📢 {ads[0]["text"]}</div>'
    except Exception:
        pass

    try:
        data = future_catalog.result(timeout=TIMEOUT_S + 0.5)
        products = data.json().get("products", [])
        if category != "all" and not q:
            products = [p for p in products if category.lower() in [c.lower() for c in p.get("categories", [])]]
    except Exception as e:
        products_error = e

    if products_error is not None and not products:
        content = f'<h2 style="color:#ef4444;">Product Catalog Service Unreachable ({PRODUCT_CATALOG_URL})</h2><p>{products_error}</p>'
        return HTML_LAYOUT.format(title="Error", content=content, ad_banner="", cart_count=cart_count, search_query=q, top_ticker=TOP_TICKER, footer=FOOTER_HTML, usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")

    cat_bar = f"""
    <div class="cat-bar">
        <a href="/?category=all" class="cat-tab {'active' if category=='all' else ''}">All Apparel</a>
        <a href="/?category=clothing" class="cat-tab {'active' if category=='clothing' else ''}">Clothing</a>
        <a href="/?category=footwear" class="cat-tab {'active' if category=='footwear' else ''}">Footwear</a>
        <a href="/?category=accessories" class="cat-tab {'active' if category=='accessories' else ''}">Accessories</a>
    </div>
    """

    cards = ""
    for p in products:
        p_price = p.get("price_usd", {"units": 50, "nanos": 0})
        price_str = _convert_price(p_price["units"], p_price["nanos"], user_currency)
        cards += f"""
        <div class="card">
            <div>
                <span class="sku-tag">SKU #{p['id']}</span>
                <h3 style="font-size:1.15rem; font-weight:700; margin-top:0.2rem;"><a href="/product/{p['id']}" style="text-decoration:none; color:#0f172a;">{p['name']}</a></h3>
                <p style="color:#64748b; font-size:0.875rem; margin-top:0.4rem; line-height:1.4;">{p['description']}</p>
            </div>
            <div style="margin-top:1.25rem;">
                <div style="font-size:1.25rem; font-weight:800; color:#ea580c;">{price_str}</div>
                <div style="display:flex; gap:0.5rem; margin-top:0.75rem;">
                    <a href="/product/{p['id']}" class="btn btn-outline" style="flex:1; font-size:0.85rem; padding:0.5rem;">Details</a>
                    <form action="/add-to-cart" method="post" style="flex:1; margin:0;">
                        <input type="hidden" name="product_id" value="{p['id']}">
                        <input type="hidden" name="quantity" value="1">
                        <button type="submit" class="btn" style="width:100%; font-size:0.85rem; padding:0.5rem;">Add to Cart</button>
                    </form>
                </div>
            </div>
        </div>
        """

    content = f"""
    {cat_bar}
    <div style="margin-top: 1.5rem;">
        <h1 style="font-size:1.8rem; font-weight:800;">StyleHub Fashion Catalog</h1>
    </div>
    <div class="product-grid">{cards}</div>
    """

    return HTML_LAYOUT.format(
        title="Storefront", ad_banner=ad_html, content=content, cart_count=cart_count, search_query=q,
        top_ticker=TOP_TICKER, footer=FOOTER_HTML,
        usd_sel="selected" if user_currency=="USD" else "",
        eur_sel="selected" if user_currency=="EUR" else "",
        gbp_sel="selected" if user_currency=="GBP" else "",
        jpy_sel="selected" if user_currency=="JPY" else "",
        cad_sel="selected" if user_currency=="CAD" else "",
        inr_sel="selected" if user_currency=="INR" else ""
    )

@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_detail_page(product_id: str, request: Request):
    user_currency = request.cookies.get("user_currency", "USD")
    cart_count = _get_cart_count()

    try:
        resp = requests.get(f"{PRODUCT_CATALOG_URL}/api/products/{product_id}", timeout=TIMEOUT_S)
    except requests.exceptions.RequestException as e:
        content = f'<h2 style="color:#ef4444;">Product Catalog Service Unreachable ({PRODUCT_CATALOG_URL})</h2><p>{e}</p>'
        return HTML_LAYOUT.format(title="Error", content=content, ad_banner="", cart_count=cart_count, search_query="", top_ticker=TOP_TICKER, footer=FOOTER_HTML, usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")

    if resp.status_code == 404:
        return HTML_LAYOUT.format(title="Not Found", content=f"<h2>Product Not Found</h2><p>No product with SKU {product_id}.</p>", ad_banner="", cart_count=cart_count, search_query="", top_ticker=TOP_TICKER, footer=FOOTER_HTML, usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")
    if resp.status_code != 200:
        content = f'<h2 style="color:#ef4444;">Product Catalog Service Error (HTTP {resp.status_code})</h2>'
        return HTML_LAYOUT.format(title="Error", content=content, ad_banner="", cart_count=cart_count, search_query="", top_ticker=TOP_TICKER, footer=FOOTER_HTML, usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")

    product = resp.json()

    p_price = product.get("price_usd", {"units": 50, "nanos": 0})
    price_str = _convert_price(p_price["units"], p_price["nanos"], user_currency)

    # Recommendations
    recommended_cards = ""
    try:
        rec_res = requests.post(f"{RECOMMENDATION_URL}/api/recommendations", params={"user_id": "user-demo-123"}, json=[product_id], timeout=TIMEOUT_S).json()
        for r_id in rec_res.get("product_ids", []):
            try:
                rp = requests.get(f"{PRODUCT_CATALOG_URL}/api/products/{r_id}", timeout=TIMEOUT_S).json()
                rp_price = rp.get("price_usd", {"units": 50, "nanos": 0})
                r_price = _convert_price(rp_price["units"], rp_price["nanos"], user_currency)
                recommended_cards += f"""
                <div class="card" style="padding:1rem;">
                    <span class="sku-tag">SKU #{rp['id']}</span>
                    <h4 style="font-size:1rem; font-weight:700;"><a href="/product/{rp['id']}" style="color:#0f172a; text-decoration:none;">{rp['name']}</a></h4>
                    <div style="font-weight:800; color:#ea580c; margin-top:0.5rem;">{r_price}</div>
                    <a href="/product/{rp['id']}" class="btn btn-outline" style="margin-top:0.75rem; font-size:0.8rem; padding:0.4rem;">View Details</a>
                </div>
                """
            except Exception: pass
    except Exception: pass

    content = f"""
    <div style="background:white; border:1px solid #e2e8f0; border-radius:0.75rem; padding:2rem; margin-top:1rem; display:grid; grid-template-columns:1fr 1fr; gap:2.5rem;">
        <div style="background:#f8fafc; border-radius:0.5rem; display:flex; align-items:center; justify-content:center; min-height:300px; border:1px solid #e2e8f0;">
            <div style="font-size:4rem;">👕</div>
        </div>
        <div>
            <span class="sku-tag">SKU #{product['id']}</span>
            <h1 style="font-size:2.2rem; font-weight:800; color:#0f172a; margin-top:0.25rem;">{product['name']}</h1>
            <div style="font-size:1.8rem; font-weight:800; color:#ea580c; margin:1rem 0;">{price_str}</div>
            <p style="color:#475569; line-height:1.6; font-size:1rem; margin-bottom:1.5rem;">{product['description']}</p>
            
            <form action="/add-to-cart" method="post">
                <input type="hidden" name="product_id" value="{product['id']}">
                <div style="display:flex; align-items:center; gap:1rem; margin-bottom:1.5rem;">
                    <label style="font-weight:700; font-size:0.9rem;">Quantity:</label>
                    <select name="quantity" style="padding:0.5rem 1rem; border-radius:0.5rem; font-weight:700; border:1px solid #cbd5e1;">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="3">3</option>
                        <option value="4">4</option>
                        <option value="5">5</option>
                    </select>
                </div>
                <button type="submit" class="btn" style="padding:0.9rem 2rem; font-size:1rem; width:100%;">Add to Shopping Cart</button>
            </form>
        </div>
    </div>

    <div style="margin-top:3rem;">
        <h3 style="font-size:1.4rem; font-weight:800; margin-bottom:1rem;">✨ You May Also Like</h3>
        <div class="product-grid" style="grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));">{recommended_cards}</div>
    </div>
    """

    return HTML_LAYOUT.format(
        title=product['name'], ad_banner="", content=content, cart_count=cart_count, search_query="",
        top_ticker=TOP_TICKER, footer=FOOTER_HTML,
        usd_sel="selected" if user_currency=="USD" else "",
        eur_sel="selected" if user_currency=="EUR" else "",
        gbp_sel="selected" if user_currency=="GBP" else "",
        jpy_sel="selected" if user_currency=="JPY" else "",
        cad_sel="selected" if user_currency=="CAD" else "",
        inr_sel="selected" if user_currency=="INR" else ""
    )

@app.post("/add-to-cart")
def add_to_cart(product_id: str = Form(...), quantity: int = Form(1), user_id: str = "user-demo-123"):
    try:
        resp = requests.post(f"{CART_URL}/api/cart/add", json={"user_id": user_id, "item": {"product_id": product_id, "quantity": quantity}}, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Cart add error: {e}")
        return RedirectResponse(url="/cart?error=add_failed", status_code=303)
    return RedirectResponse(url="/cart", status_code=303)

@app.post("/cart/remove-item")
def remove_cart_item(product_id: str = Form(...), user_id: str = "user-demo-123"):
    try:
        resp = requests.delete(f"{CART_URL}/api/cart/{user_id}/item/{product_id}", timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Cart remove error: {e}")
        return RedirectResponse(url="/cart?error=remove_failed", status_code=303)
    return RedirectResponse(url="/cart", status_code=303)

@app.post("/cart/update-quantity")
def update_cart_quantity(product_id: str = Form(...), action: str = Form(...), user_id: str = "user-demo-123"):
    try:
        cart_items = _get_cart_items(user_id)
        current_qty = 1
        for item in cart_items:
            if item.get("product_id") == product_id:
                current_qty = item.get("quantity", 1)
                break

        new_qty = current_qty + 1 if action == "increase" else current_qty - 1
        resp = requests.post(f"{CART_URL}/api/cart/update-quantity", json={"user_id": user_id, "product_id": product_id, "quantity": new_qty}, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Cart update quantity error: {e}")
        return RedirectResponse(url="/cart?error=update_failed", status_code=303)
    return RedirectResponse(url="/cart", status_code=303)

CART_ERROR_MESSAGES = {
    "add_failed": "Couldn't add that item to your cart — the cart service didn't respond. Please try again.",
    "remove_failed": "Couldn't remove that item from your cart — the cart service didn't respond. Please try again.",
    "update_failed": "Couldn't update the quantity — the cart service didn't respond. Please try again.",
}

@app.get("/cart", response_class=HTMLResponse)
def view_cart(request: Request, user_id: str = "user-demo-123"):
    user_currency = request.cookies.get("user_currency", "USD")
    cart_items = _get_cart_items(user_id)
    error_banner = ""
    error_code = request.query_params.get("error")
    if error_code in CART_ERROR_MESSAGES:
        error_banner = f'<div style="background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; padding:0.85rem 1rem; border-radius:0.5rem; margin-bottom:1.25rem;">⚠️ {CART_ERROR_MESSAGES[error_code]}</div>'
    cart_count = sum(i.get("quantity", 1) for i in cart_items)

    if not cart_items:
        content = error_banner + '<div style="text-align:center; padding:4rem 1rem;"><h2>🛒 Your Shopping Cart is Empty</h2><a href="/" class="btn" style="display:inline-block; margin-top:1.5rem; padding:0.75rem 2rem;">Explore Store Collection</a></div>'
    else:
        rows, subtotal_usd = "", 0
        # A price the catalog can't confirm is shown as unavailable, never invented — this
        # was the last invented-data fallback in the app (unknown SKUs rendered at $50 with
        # the catalog down). Totals covering unpriced items are suppressed for the same
        # reason; the order button stays live because checkout re-validates every price
        # critically and will answer with its own 502 naming the catalog.
        catalog_failed = False
        for item in cart_items:
            p_sku = item.get("product_id")
            p_qty = item.get("quantity", 1)
            p_name, p_price = p_sku, None
            try:
                p_res = requests.get(f"{PRODUCT_CATALOG_URL}/api/products/{p_sku}", timeout=TIMEOUT_S)
                p_res.raise_for_status()
                p = p_res.json()
                p_name = p.get("name", p_sku)
                p_price = p.get("price_usd", {}).get("units", 0)
            except Exception:
                catalog_failed = True

            if p_price is None:
                price_formatted = '<span style="color:#b91c1c;">unavailable</span>'
                subtotal_formatted = '<span style="color:#b91c1c;">—</span>'
            else:
                item_total = p_price * p_qty
                subtotal_usd += item_total
                price_formatted = _convert_price(p_price, 0, user_currency)
                subtotal_formatted = _convert_price(item_total, 0, user_currency)

            rows += f"""
            <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:1rem;">
                    <span class="sku-tag">SKU #{p_sku}</span>
                    <div style="font-weight:700; font-size:1.05rem;"><a href="/product/{p_sku}" style="color:#0f172a; text-decoration:none;">{p_name}</a></div>
                </td>
                <td style="padding:1rem; color:#64748b;">{price_formatted}</td>
                <td style="padding:1rem;">
                    <div style="display:flex; align-items:center; gap:0.4rem;">
                        <form action="/cart/update-quantity" method="post" style="margin:0;">
                            <input type="hidden" name="product_id" value="{p_sku}">
                            <input type="hidden" name="action" value="decrease">
                            <button type="submit" class="qty-btn">-</button>
                        </form>
                        <span style="font-weight:700; min-width:24px; text-align:center;">{p_qty}</span>
                        <form action="/cart/update-quantity" method="post" style="margin:0;">
                            <input type="hidden" name="product_id" value="{p_sku}">
                            <input type="hidden" name="action" value="increase">
                            <button type="submit" class="qty-btn">+</button>
                        </form>
                    </div>
                </td>
                <td style="padding:1rem; font-weight:800; color:#ea580c;">{subtotal_formatted}</td>
                <td style="padding:1rem; text-align:right;">
                    <form action="/cart/remove-item" method="post" style="margin:0;">
                        <input type="hidden" name="product_id" value="{p_sku}">
                        <button type="submit" class="btn-danger">🗑️ Remove</button>
                    </form>
                </td>
            </tr>
            """

        # Dynamic Shipping Quote
        shipping_usd = 12.00
        try:
            quote = requests.post(f"{SHIPPING_URL}/api/shipping/quote", json=cart_items, timeout=TIMEOUT_S).json()
            cost_info = quote.get("cost_usd", {})
            shipping_usd = cost_info.get("units", 12) + (cost_info.get("nanos", 0) / 1e9)
        except Exception: pass

        total_usd = int(subtotal_usd + shipping_usd)
        shipping_formatted = _convert_price(int(shipping_usd), 0, user_currency)
        if catalog_failed:
            error_banner += '<div style="background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; padding:0.85rem 1rem; border-radius:0.5rem; margin-bottom:1.25rem;">⚠️ Some prices could not be loaded — product-catalog-service is unavailable. Totals are incomplete until it recovers.</div>'
            subtotal_formatted_summary = '<span style="color:#b91c1c;">unavailable</span>'
            total_formatted = '<span style="color:#b91c1c;">unavailable</span>'
        else:
            subtotal_formatted_summary = _convert_price(subtotal_usd, 0, user_currency)
            total_formatted = _convert_price(total_usd, 0, user_currency)

        content = f"""
        {error_banner}
        <h1 style="font-size:2rem; font-weight:800; margin-bottom:1.5rem;">Shopping Cart ({cart_count} items)</h1>
        
        <div style="display:grid; grid-template-columns: 1fr 400px; gap:2rem; align-items:start;">
            <div>
                <table style="width:100%; background:white; border-radius:0.75rem; padding:1rem; border-collapse:collapse; border:1px solid #e2e8f0; text-align:left;">
                    <thead>
                        <tr style="border-bottom:2px solid #e2e8f0; color:#64748b; font-size:0.85rem;">
                            <th style="padding:0.75rem;">Product</th>
                            <th style="padding:0.75rem;">Price</th>
                            <th style="padding:0.75rem;">Quantity</th>
                            <th style="padding:0.75rem;">Subtotal</th>
                            <th style="padding:0.75rem; text-align:right;">Action</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                <div style="display:flex; justify-content:space-between; margin-top:1rem;">
                    <form action="/empty-cart" method="post" style="margin:0;">
                        <button type="submit" class="btn btn-outline" style="font-size:0.85rem;">Empty Entire Cart</button>
                    </form>
                    <a href="/" class="btn btn-outline" style="font-size:0.85rem;">Continue Shopping</a>
                </div>
            </div>

            <!-- Checkout Form & Summary Panel -->
            <div style="background:white; border:1px solid #e2e8f0; border-radius:0.75rem; padding:1.5rem; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
                <h3 style="font-size:1.2rem; font-weight:800; margin-bottom:1rem; border-bottom:1px solid #e2e8f0; padding-bottom:0.5rem;">Checkout & Delivery</h3>
                
                <form action="/checkout" method="post">
                    <!-- Shipping Address Section -->
                    <div style="margin-bottom:1.25rem;">
                        <h4 style="font-size:0.9rem; font-weight:700; color:#475569; margin-bottom:0.5rem;">Shipping Address</h4>
                        <input type="email" name="email" value="someone@example.com" placeholder="Email Address" required style="width:100%; padding:0.5rem; margin-bottom:0.4rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                        <input type="text" name="street_address" value="1600 Amphitheatre Parkway" placeholder="Street Address" required style="width:100%; padding:0.5rem; margin-bottom:0.4rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                        <div style="display:flex; gap:0.4rem;">
                            <input type="text" name="city" value="Mountain View" placeholder="City" required style="flex:1; padding:0.5rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                            <input type="text" name="state" value="CA" placeholder="State" required style="width:70px; padding:0.5rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                            <input type="text" name="zip_code" value="94043" placeholder="Zip" required style="width:80px; padding:0.5rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                        </div>
                    </div>

                    <!-- Payment Method Section -->
                    <div style="margin-bottom:1.5rem;">
                        <h4 style="font-size:0.9rem; font-weight:700; color:#475569; margin-bottom:0.5rem;">Payment Method</h4>
                        <input type="text" name="credit_card_number" value="4432-8015-6152-0454" placeholder="Credit Card Number" required style="width:100%; padding:0.5rem; margin-bottom:0.4rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem; font-family:monospace;">
                        <div style="display:flex; gap:0.4rem;">
                            <select name="exp_month" style="flex:1; padding:0.5rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                                <option value="1" selected>01 - January</option>
                                <option value="12">12 - December</option>
                            </select>
                            <select name="exp_year" style="width:90px; padding:0.5rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                                <option value="2026">2026</option>
                                <option value="2028" selected>2028</option>
                            </select>
                            <input type="password" name="cvv" value="123" placeholder="CVV" required style="width:60px; padding:0.5rem; border:1px solid #cbd5e1; border-radius:0.4rem; font-size:0.85rem;">
                        </div>
                    </div>

                    <!-- Order Summary Calculation -->
                    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:0.5rem; padding:1rem; margin-bottom:1.5rem;">
                        <div style="display:flex; justify-content:space-between; font-size:0.9rem; margin-bottom:0.3rem;">
                            <span style="color:#64748b;">Subtotal:</span>
                            <span>{subtotal_formatted_summary}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:0.9rem; margin-bottom:0.5rem;">
                            <span style="color:#64748b;">Shipping:</span>
                            <span>{shipping_formatted}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:1.25rem; font-weight:800; color:#ea580c; border-top:1px solid #cbd5e1; padding-top:0.5rem;">
                            <span>Total Due:</span>
                            <span>{total_formatted}</span>
                        </div>
                    </div>

                    <button type="submit" class="btn" style="width:100%; padding:0.9rem; font-size:1rem;">Place Order Now</button>
                </form>
            </div>
        </div>
        """

    return HTML_LAYOUT.format(
        title="Cart & Checkout", ad_banner="", content=content, cart_count=cart_count, search_query="",
        top_ticker=TOP_TICKER, footer=FOOTER_HTML,
        usd_sel="selected" if user_currency=="USD" else "",
        eur_sel="selected" if user_currency=="EUR" else "",
        gbp_sel="selected" if user_currency=="GBP" else "",
        jpy_sel="selected" if user_currency=="JPY" else "",
        cad_sel="selected" if user_currency=="CAD" else "",
        inr_sel="selected" if user_currency=="INR" else ""
    )

@app.post("/empty-cart")
def empty_cart(user_id: str = "user-demo-123"):
    try:
        requests.delete(f"{CART_URL}/api/cart/{user_id}", timeout=TIMEOUT_S)
    except Exception: pass
    return RedirectResponse(url="/cart", status_code=303)

@app.post("/checkout", response_class=HTMLResponse)
def checkout(
    request: Request,
    email: str = Form("someone@example.com"),
    street_address: str = Form("1600 Amphitheatre Parkway"),
    city: str = Form("Mountain View"),
    state: str = Form("CA"),
    zip_code: int = Form(94043),
    credit_card_number: str = Form("4432-8015-6152-0454"),
    exp_month: int = Form(12),
    exp_year: int = Form(2028),
    cvv: int = Form(123),
    user_id: str = "user-demo-123"
):
    user_currency = request.cookies.get("user_currency", "USD")

    # Phase 1: the failure is the product here. Round 1 rendered "Order Placed
    # Successfully!" with invented IDs (ORD-SH-SUCCESS) even when checkout-service was
    # completely dead — the final and worst link in the failure-masking chain. Now a
    # checkout failure renders an error page carrying checkout's own 502 detail, so a
    # payment-service kill is visible in the browser as
    # "payment-service unavailable — order not placed", three hops upstream.
    def _order_failed_page(status_code, detail):
        content = f"""
        <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:0.75rem; padding:2.5rem; max-width:650px; margin:2rem auto; text-align:center;">
            <div style="font-size:3.5rem;">🚫</div>
            <h1 style="color:#b91c1c; font-weight:800; font-size:2rem; margin-top:0.5rem;">Order Could Not Be Placed</h1>
            <p style="color:#991b1b; margin-top:0.4rem;">No payment was taken and no shipment was booked.</p>
            <div style="background:white; border:1px solid #fecaca; border-radius:0.5rem; padding:1.25rem; margin-top:1.5rem; text-align:left;">
                <p style="font-family:monospace; color:#b91c1c; margin:0;">HTTP {status_code} — {detail}</p>
            </div>
            <a href="/cart" class="btn" style="display:inline-block; margin-top:2rem; padding:0.8rem 2rem; background:#b91c1c;">Back to Cart</a>
        </div>
        """
        page = HTML_LAYOUT.format(title="Order Failed", ad_banner="", content=content,
                                  cart_count=0, search_query="", top_ticker=TOP_TICKER, footer=FOOTER_HTML,
                                  usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")
        return HTMLResponse(content=page, status_code=status_code)

    try:
        res = requests.post(f"{CHECKOUT_URL}/api/checkout", json={
            "user_id": user_id,
            "user_currency": user_currency,
            "email": email,
            "address": {"street_address": street_address, "city": city, "state": state, "country": "United States", "zip_code": zip_code},
            "credit_card": {"credit_card_number": credit_card_number, "credit_card_cvv": cvv, "credit_card_expiration_year": exp_year, "credit_card_expiration_month": exp_month}
        }, timeout=ORCH_TIMEOUT_S)
    except requests.RequestException as e:
        logger.error(f"Checkout unreachable: {e}")
        return _order_failed_page(502, f"checkout-service unreachable ({type(e).__name__})")

    if res.status_code >= 400:
        try:
            detail = res.json().get("detail", res.text[:200])
        except Exception:
            detail = res.text[:200]
        logger.error(f"Checkout failed: HTTP {res.status_code} — {detail}")
        return _order_failed_page(res.status_code, detail)

    order_info = res.json().get("order", {})
    order_id = order_info.get("order_id", "ORD-UNKNOWN")
    tracking_id = order_info.get("shipping_tracking_id", "TRK-UNKNOWN")

    content = f"""
    <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:0.75rem; padding:2.5rem; max-width:650px; margin:2rem auto; text-align:center;">
        <div style="font-size:3.5rem;">🎉</div>
        <h1 style="color:#166534; font-weight:800; font-size:2rem; margin-top:0.5rem;">Order Placed Successfully!</h1>
        <p style="color:#15803d; margin-top:0.4rem;">Your order has been processed across our microservices mesh.</p>
        
        <div style="background:white; border:1px solid #dcfce7; border-radius:0.5rem; padding:1.5rem; margin-top:1.5rem; text-align:left; line-height:1.6;">
            <p><strong>Order ID:</strong> <span style="font-family:monospace; color:#166534;">{order_id}</span></p>
            <p><strong>Carrier Tracking ID:</strong> <span style="font-family:monospace; color:#166534;">{tracking_id}</span></p>
            <p><strong>Confirmation Sent To:</strong> {email}</p>
            <p><strong>Delivery Address:</strong> {street_address}, {city}, {state} {zip_code}</p>
            <p><strong>Payment Method:</strong> Credit Card ending in {credit_card_number[-4:]}</p>
        </div>

        <a href="/" class="btn" style="display:inline-block; margin-top:2rem; padding:0.8rem 2rem; background:#16a34a;">Continue Shopping</a>
    </div>
    """
    return HTML_LAYOUT.format(title="Order Complete", ad_banner="", content=content, cart_count=0, search_query="", top_ticker=TOP_TICKER, footer=FOOTER_HTML, usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")

ALL_SERVICES_CONFIG = [
    ("Frontend Storefront", "frontend", 8080, "http://localhost:8080"),
    ("Product Catalog Service", "product-catalog-service", 8081, "http://localhost:8081"),
    ("Cart Service", "cart-service", 8082, "http://localhost:8082"),
    ("Currency Service", "currency-service", 8083, "http://localhost:8083"),
    ("Recommendation Service", "recommendation-service", 8084, "http://localhost:8084"),
    ("Shipping Service", "shipping-service", 8085, "http://localhost:8085"),
    ("Checkout Orchestrator", "checkout-service", 8086, "http://localhost:8086"),
    ("Ad Service", "ad-service", 8087, "http://localhost:8087"),
    ("Email Service", "email-service", 8088, "http://localhost:8088"),
    ("Payment Processing Service", "payment-service", 8089, "http://localhost:8089"),
]

@app.get("/system-status", response_class=HTMLResponse)
def system_status_dashboard(request: Request):
    user_currency = request.cookies.get("user_currency", "USD")
    cart_count = _get_cart_count()

    service_cards = ""
    for name, key, port, url in ALL_SERVICES_CONFIG:
        start_t = time.time()
        try:
            res = requests.get(f"{url}/healthz", timeout=TIMEOUT_S)
            lat_ms = int((time.time() - start_t) * 1000)
            status_badge = '<span style="background:#dcfce7; color:#15803d; padding:0.25rem 0.6rem; border-radius:0.3rem; font-weight:700; font-size:0.75rem;">🟢 SERVING</span>'
            lat_str = f"{lat_ms} ms"
        except Exception:
            status_badge = '<span style="background:#fee2e2; color:#b91c1c; padding:0.25rem 0.6rem; border-radius:0.3rem; font-weight:700; font-size:0.75rem;">🔴 UNREACHABLE</span>'
            lat_str = "TIMEOUT"

        service_cards += f"""
        <div style="background:white; border:1px solid #e2e8f0; border-radius:0.5rem; padding:1.25rem; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <h4 style="font-size:1.05rem; font-weight:700;">{name}</h4>
                <div style="font-size:0.8rem; color:#64748b; font-family:monospace; margin-top:0.2rem;">HTTP Endpoint: {url}</div>
            </div>
            <div style="text-align:right;">
                <div>{status_badge}</div>
                <div style="font-size:0.8rem; font-weight:700; color:#475569; margin-top:0.3rem;">Latency: {lat_str}</div>
            </div>
        </div>
        """

    content = f"""
    <div style="margin-bottom:2rem;">
        <h1 style="font-size:2rem; font-weight:800;">📊 Live System Topology & Microservices Health Dashboard</h1>
        <p style="color:#64748b; margin-top:0.4rem;">Real-time health status, response latency, and network route monitoring across all 10 StyleHub microservices.</p>
    </div>

    <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap:1.25rem;">
        {service_cards}
    </div>
    """

    return HTML_LAYOUT.format(title="System Status", ad_banner="", content=content, cart_count=cart_count, search_query="", top_ticker=TOP_TICKER, footer=FOOTER_HTML, usd_sel="", eur_sel="", gbp_sel="", jpy_sel="", cad_sel="", inr_sel="")

if __name__ == "__main__":
    import uvicorn
    import time
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), timeout_keep_alive=120)
