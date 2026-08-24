import os
import re
import json
import time
import statistics
from urllib.parse import urljoin, quote_plus

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, request, jsonify
from dotenv import load_dotenv

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

load_dotenv()

app = Flask(__name__)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

MAX_PRODUCTS = int(os.getenv("MAX_PRODUCTS", "40"))
MAX_PRODUCT_PAGES = int(os.getenv("MAX_PRODUCT_PAGES", "25"))
MAX_COMPETITOR_SEARCHES = int(os.getenv("MAX_COMPETITOR_SEARCHES", "6"))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>Active Online — Trendyol Intelligence</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        @media print {
            body * { visibility: hidden; }
            #printableReport, #printableReport * { visibility: visible; }
            #printableReport { position: absolute; left: 0; top: 0; width: 100%; }
            .no-print { display: none; }
        }
    </style>
</head>
<body class="bg-gray-50 text-gray-900 font-sans">
    <div class="container mx-auto px-4 py-10 max-w-6xl">
        <header class="mb-8 text-center no-print">
            <h1 class="text-3xl font-bold text-blue-900">Active Online — Trendyol Intelligence</h1>
            <p class="text-gray-600 mt-2">منصة ذكاء الأعمال وتحليل الأسعار التنافسية ومقارنة المنافسين في ترينديول</p>
        </header>

        <div class="bg-white p-6 rounded-xl shadow-md mb-8 border border-gray-100 no-print">
            <h2 class="text-xl font-semibold mb-4 text-blue-800">تحليل متجر عميق مع مقارنة الأسعار وروابط المنافسين</h2>
            <div class="flex flex-col md:flex-row gap-4">
                <input type="text" id="storeUrl" placeholder="أدخل رابط متجر Trendyol أو رابط مختصر ty.gl..." 
                       class="flex-1 border border-gray-300 rounded-lg px-4 py-3 focus:outline-none focus:border-blue-600 text-left" dir="ltr">
                <button onclick="analyzeStore()" id="analyzeBtn" class="bg-blue-600 text-white px-8 py-3 rounded-lg font-bold hover:bg-blue-700 transition shadow">
                    بدء التحليل الشامل
                </button>
            </div>
            <div id="loading" class="mt-4 hidden text-blue-600 font-medium text-center">جاري سحب بيانات المنتجات عبر المتصفح السحابي، جلب روابط وأسعار المنافسين، وتوليد التقرير الاستخباراتي... يرجى الانتظار</div>
        </div>

        <div id="resultContainer" class="hidden space-y-8">
            <div class="bg-white p-6 rounded-xl shadow-md border border-gray-100 no-print">
                <h3 class="text-xl font-bold mb-4 text-gray-800 border-b pb-2">ملخص بيانات المتجر الإحصائية</h3>
                <div id="storeDetails" class="grid grid-cols-2 md:grid-cols-4 gap-4 bg-blue-50 p-4 rounded-lg text-sm"></div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 no-print">
                <div class="bg-white p-6 rounded-xl shadow-md border border-gray-100 flex flex-col items-center">
                    <h3 class="text-lg font-bold mb-4 text-gray-800 border-b pb-2 w-full text-center">مخطط الأسعار (أدنى، متوسط، أقصى)</h3>
                    <div class="w-full h-64 flex justify-center items-center">
                        <canvas id="priceChart"></canvas>
                    </div>
                </div>
                <div class="bg-white p-6 rounded-xl shadow-md border border-gray-100 flex flex-col items-center">
                    <h3 class="text-lg font-bold mb-4 text-gray-800 border-b pb-2 w-full text-center">توزيع المنتجات (العروض والخصومات)</h3>
                    <div class="w-full h-64 flex justify-center items-center">
                        <canvas id="discountChart"></canvas>
                    </div>
                </div>
            </div>

            <div id="printableReport" class="bg-white p-6 rounded-xl shadow-md border border-gray-100">
                <div class="flex justify-between items-center border-b pb-2 mb-4">
                    <h3 class="text-xl font-bold text-gray-800">التقرير الاستخباراتي التجاري الشامل (مع مقارنة أسعار المنافسين)</h3>
                    <button onclick="window.print()" class="no-print bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-green-700 transition shadow flex items-center gap-2">
                        🖨️ طباعة أو تصدير التقرير (PDF)
                    </button>
                </div>
                <div id="reportContent" class="whitespace-pre-wrap bg-gray-50 p-6 rounded-lg text-gray-800 text-sm leading-loose border shadow-inner" dir="auto"></div>
            </div>

            <div class="bg-white p-6 rounded-xl shadow-md border border-gray-100 no-print">
                <h3 class="text-xl font-bold mb-4 text-gray-800 border-b pb-2">عينة من منتجات المتجر مع روابط المنافسين وأقل الأسعار بالسوق</h3>
                <div id="productsGrid" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6"></div>
            </div>
        </div>
    </div>

    <script>
        let priceChartInstance = null;
        let discountChartInstance = null;

        async function analyzeStore() {
            const url = document.getElementById('storeUrl').value;
            if (!url) return alert('الرجاء إدخال رابط صالح');
            
            const loading = document.getElementById('loading');
            const resultContainer = document.getElementById('resultContainer');
            const btn = document.getElementById('analyzeBtn');
            
            loading.classList.remove('hidden');
            resultContainer.classList.add('hidden');
            btn.disabled = true;
            
            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                
                const data = await response.json();
                loading.classList.add('hidden');
                btn.disabled = false;
                
                if (response.ok) {
                    const stats = data.statistics;
                    document.getElementById('storeDetails').innerHTML = `
                        <div><strong>اسم المتجر:</strong> ${data.store_info.store_name || 'غير متوفر'}</div>
                        <div><strong>معرف البائع:</strong> ${data.store_info.merchant_id || 'غير متوفر'}</div>
                        <div><strong>المنتجات المجمعة:</strong> ${stats.products_collected}</div>
                        <div><strong>متوسط الأسعار:</strong> ${stats.average_price ? stats.average_price + ' TL' : 'غير متوفر'}</div>
                    `;
                    document.getElementById('reportContent').innerText = data.report;
                    
                    renderCharts(stats);

                    const grid = document.getElementById('productsGrid');
                    grid.innerHTML = '';
                    if (data.products && data.products.length > 0) {
                        data.products.forEach(p => {
                            const imgUrl = (p.images && p.images.length > 0) ? p.images[0] : 'https://via.placeholder.com/150';
                            
                            const comp1Price = p.competitor_1_price ? p.competitor_1_price + ' TL' : 'غير متوفر';
                            const comp1Link = p.competitor_1_url ? `<a href="${p.competitor_1_url}" target="_blank" class="text-blue-600 underline font-semibold">رابط المنافس الأول</a>` : 'غير متوفر';
                            
                            const comp2Price = p.competitor_2_price ? p.competitor_2_price + ' TL' : 'غير متوفر';
                            const comp2Link = p.competitor_2_url ? `<a href="${p.competitor_2_url}" target="_blank" class="text-blue-600 underline font-semibold">رابط المنافس الثاني</a>` : 'غير متوفر';

                            const card = `
                                <div class="border rounded-lg p-3 shadow-sm bg-gray-50 flex flex-col justify-between">
                                    <div>
                                        <img src="${imgUrl}" alt="Product Image" class="w-full h-48 object-cover rounded-md mb-2 bg-white" onerror="this.src='https://via.placeholder.com/150'">
                                        <h4 class="font-semibold text-xs text-gray-800 line-clamp-2 mb-1" title="${p.title || ''}">${p.title || 'منتج بدون عنوان'}</h4>
                                    </div>
                                    <div class="mt-2 pt-2 border-t text-xs space-y-1.5">
                                        <div class="flex justify-between bg-blue-50 p-1 rounded"><span class="font-bold text-blue-900">سعر متجرك:</span> <span class="text-blue-700 font-bold">${p.price ? p.price + ' TL' : 'غير متوفر'}</span></div>
                                        
                                        <div class="flex justify-between items-center text-gray-700">
                                            <span>المنافس 1 (${comp1Price}):</span>
                                            <span>${comp1Link}</span>
                                        </div>
                                        
                                        <div class="flex justify-between items-center text-gray-700">
                                            <span>المنافس 2 (${comp2Price}):</span>
                                            <span>${comp2Link}</span>
                                        </div>

                                        <div class="pt-2 text-center">
                                            <a href="${p.url}" target="_blank" class="block w-full bg-green-600 hover:bg-green-700 text-white py-1.5 px-3 rounded text-center font-medium transition shadow-sm">
                                                🔗 رابط منتجك الأصلي
                                            </a>
                                        </div>
                                    </div>
                                </div>
                            `;
                            grid.innerHTML += card;
                        });
                    } else {
                        grid.innerHTML = '<p class="text-gray-500 col-span-full text-center">لم يتم العثور على منتجات متاحة للعرض.</p>';
                    }

                    resultContainer.classList.remove('hidden');
                } else {
                    alert('خطأ: ' + (data.error || 'حدث خطأ غير متوقع'));
                }
            } catch (err) {
                loading.classList.add('hidden');
                btn.disabled = false;
                alert('حدث خطأ في الاتصال بالسيرفر');
            }
        }

        function renderCharts(stats) {
            if (priceChartInstance) priceChartInstance.destroy();
            if (discountChartInstance) discountChartInstance.destroy();

            const ctxPrice = document.getElementById('priceChart').getContext('2d');
            priceChartInstance = new Chart(ctxPrice, {
                type: 'bar',
                data: {
                    labels: ['أقل سعر', 'متوسط الأسعار', 'أعلى سعر'],
                    datasets: [{
                        label: 'السعر بـ TL',
                        data: [stats.min_price || 0, stats.average_price || 0, stats.max_price || 0],
                        backgroundColor: ['rgba(54, 162, 235, 0.6)', 'rgba(75, 192, 192, 0.6)', 'rgba(255, 99, 132, 0.6)'],
                        borderColor: ['rgba(54, 162, 235, 1)', 'rgba(75, 192, 192, 1)', 'rgba(255, 99, 132, 1)'],
                        borderWidth: 1
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
            });

            const discounted = stats.discounted_products || 0;
            const regular = (stats.products_collected || 0) - discounted;
            const ctxDiscount = document.getElementById('discountChart').getContext('2d');
            discountChartInstance = new Chart(ctxDiscount, {
                type: 'doughnut',
                data: {
                    labels: ['منتجات تخضع لعروض', 'منتجات عادية'],
                    datasets: [{
                        data: [discounted, regular > 0 ? regular : 0],
                        backgroundColor: ['rgba(255, 159, 64, 0.7)', 'rgba(201, 203, 207, 0.7)']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
    </script>
</body>
</html>
"""

def clean_text(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip() or None

def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
    if not m:
        return None
    raw = m.group(1)
    try:
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        return float(raw)
    except Exception:
        return None

def to_int(value):
    if value is None:
        return None
    m = re.search(r"(\d[\d.,]*)", str(value))
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except Exception:
        return None

def resolve_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        r = SESSION.get(url, allow_redirects=True, timeout=15)
        return r.url or url
    except Exception:
        return url

def extract_merchant_id(url, html=""):
    patterns = [
        r"/magaza/[^/?#]+-m-(\d+)",
        r"/magaza/[^/?#]+/.*?m-(\d+)",
        r"[?&]merchantId=(\d+)",
        r'"merchantId"\s*:\s*"?(\d+)"?',
        r'"merchant_id"\s*:\s*"?(\d+)"?',
    ]
    for p in patterns:
        m = re.search(p, url, re.I)
        if m:
            return m.group(1)
    for p in patterns[2:]:
        m = re.search(p, html, re.I)
        if m:
            return m.group(1)
    return None

def parse_jsonld(soup):
    items = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text())
            if isinstance(data, list):
                items.extend(data)
            else:
                items.append(data)
        except Exception:
            continue
    return items

def first_jsonld_product(soup):
    for item in parse_jsonld(soup):
        if isinstance(item, dict):
            t = item.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return item
            if "@graph" in item and isinstance(item["@graph"], list):
                for x in item["@graph"]:
                    if isinstance(x, dict) and x.get("@type") == "Product":
                        return x
    return None

def parse_product_html(url, html):
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "url": url,
        "title": None,
        "brand": None,
        "category": None,
        "price": None,
        "old_price": None,
        "currency": "TRY",
        "rating": None,
        "review_count": None,
        "images": [],
        "description": None,
        "competitor_1_url": None,
        "competitor_1_price": None,
        "competitor_2_url": None,
        "competitor_2_price": None,
    }

    p = first_jsonld_product(soup)
    if p:
        data["title"] = clean_text(p.get("name"))
        data["description"] = clean_text(p.get("description"))
        brand = p.get("brand")
        if isinstance(brand, dict):
            data["brand"] = clean_text(brand.get("name"))
        elif brand:
            data["brand"] = clean_text(brand)

        image = p.get("image")
        if isinstance(image, list):
            data["images"] = [x for x in image if isinstance(x, str)][:10]
        elif isinstance(image, str):
            data["images"] = [image]

        offers = p.get("offers")
        if isinstance(offers, dict):
            data["price"] = to_float(offers.get("price"))
            data["currency"] = offers.get("priceCurrency") or "TRY"
        elif isinstance(offers, list) and offers:
            o = offers[0]
            if isinstance(o, dict):
                data["price"] = to_float(o.get("price"))
                data["currency"] = o.get("priceCurrency") or "TRY"

        agg = p.get("aggregateRating")
        if isinstance(agg, dict):
            data["rating"] = to_float(agg.get("ratingValue"))
            data["review_count"] = to_int(agg.get("reviewCount") or agg.get("ratingCount"))

    if not data["title"]:
        h1 = soup.find("h1")
        data["title"] = clean_text(h1.get_text(" ", strip=True)) if h1 else clean_text(soup.title.get_text()) if soup.title else None

    if not data["images"]:
        for img in soup.select('img[src*="cdn.dsmcdn.com"]'):
            src = img.get("src")
            if src and src not in data["images"]:
                data["images"].append(src)

    if data["price"] is None:
        price_selectors = ['[data-testid*="price"]', '[class*="price"]', '[class*="Price"]']
        for sel in price_selectors:
            node = soup.select_one(sel)
            if node:
                val = to_float(node.get_text(" ", strip=True))
                if val is not None:
                    data["price"] = val
                    break

    return data

def fetch_competitors_via_browser(page, product_title):
    if not product_title:
        return None, None, None, None
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+", product_title)
    q = " ".join(words[:6])
    if len(q) < 6:
        return None, None, None, None
    search_url = "https://www.trendyol.com/sr?q=" + quote_plus(q)
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
        soup = BeautifulSoup(page.content(), "html.parser")
        competitors = []
        for a in soup.find_all("a", href=True):
            href = urljoin(search_url, a["href"])
            if "/p-" not in href:
                continue
            clean_link = href.split("?")[0]
            parent = a.find_parent("div")
            price_val = None
            if parent:
                for node in parent.select('[class*="price"], [data-testid*="price"]'):
                    val = to_float(node.get_text(" ", strip=True))
                    if val and val > 1:
                        price_val = val
                        break
            if price_val and clean_link not in [c["url"] for c in competitors]:
                competitors.append({"url": clean_link, "price": price_val})
            if len(competitors) >= 5:
                break
        
        competitors = sorted(competitors, key=lambda x: x["price"])
        c1_url = competitors[0]["url"] if len(competitors) > 0 else None
        c1_price = competitors[0]["price"] if len(competitors) > 0 else None
        c2_url = competitors[1]["url"] if len(competitors) > 1 else None
        c2_price = competitors[1]["price"] if len(competitors) > 1 else None
        
        return c1_url, c1_price, c2_url, c2_price
    except Exception:
        return None, None, None, None

def collect_store_data(url, max_products=MAX_PRODUCTS):
    if sync_playwright is None:
        raise RuntimeError("Playwright غير مثبت")

    store_html = ""
    product_urls = []
    final_url = url

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page(
            user_agent=SESSION.headers["User-Agent"],
            locale="tr-TR",
            viewport={"width": 1440, "height": 1000},
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            final_url = page.url
            for _ in range(5):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1000)
            store_html = page.content()

            links = page.locator("a").evaluate_all(
                """els => els.map(a => ({href:a.href}))"""
            )
            seen = set()
            for item in links:
                href = item.get("href") if isinstance(item, dict) else None
                if not href or "trendyol.com" not in href:
                    continue
                if re.search(r"[-/]p-\d+", href, re.I):
                    clean = href.split("?")[0]
                    if clean not in seen:
                        seen.add(clean)
                        product_urls.append(clean)
                if len(product_urls) >= max_products:
                    break

            store_info = parse_store_page(final_url, store_html)
            products = []

            for product_url in product_urls[:MAX_PRODUCT_PAGES]:
                try:
                    page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(1000)
                    p_data = parse_product_html(product_url, page.content())
                    if p_data.get("title"):
                        c1_u, c1_p, c2_u, c2_p = fetch_competitors_via_browser(page, p_data["title"])
                        p_data["competitor_1_url"] = c1_u
                        p_data["competitor_1_price"] = c1_p
                        p_data["competitor_2_url"] = c2_u
                        p_data["competitor_2_price"] = c2_p
                    products.append(p_data)
                except Exception:
                    continue

        finally:
            browser.close()

    return store_info, products

def parse_store_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    merchant_id = extract_merchant_id(url, html)
    store_name = None
    for sel in ["h1", "[class*='seller-info-title']", "[class*='sellerInfo']", "[class*='Seller']"]:
        node = soup.select_one(sel)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text and len(text) < 150:
                store_name = text
                break

    if not store_name and soup.title:
        title = clean_text(soup.title.get_text())
        if title:
            store_name = re.split(r"\s*[-|]\s*Trendyol", title, flags=re.I)[0].strip()

    body = soup.get_text(" ", strip=True)
    rating, review_count = None, None

    for pattern in [r"([0-5](?:[.,]\d)?)\s*(?:/5|puan)", r"([0-5](?:[.,]\d)?)"]:
        m = re.search(pattern, body, re.I)
        if m:
            x = to_float(m.group(1))
            if x is not None and 0 <= x <= 5:
                rating = x
                break

    for pattern in [r"(\d[\d.]*)\s*(?:Değerlendirme|Yorum)", r"(\d[\d.]*)\s*reviews?"]:
        m = re.search(pattern, body, re.I)
        if m:
            review_count = to_int(m.group(1))
            break

    return {
        "store_name": store_name,
        "merchant_id": merchant_id,
        "store_url": url,
        "rating": rating,
        "review_count": review_count,
    }

def calculate_stats(products):
    prices = [p["price"] for p in products if p.get("price") is not None]
    ratings = [p["rating"] for p in products if p.get("rating") is not None]
    reviews = [p["review_count"] for p in products if p.get("review_count") is not None]
    discounts = []
    for p in products:
        if p.get("price") and p.get("old_price") and p["old_price"] > p["price"]:
            discounts.append((p["old_price"] - p["price"]) / p["old_price"] * 100)

    return {
        "products_collected": len(products),
        "prices_available": len(prices),
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "average_price": round(statistics.mean(prices), 2) if prices else None,
        "median_price": round(statistics.median(prices), 2) if prices else None,
        "average_product_rating": round(statistics.mean(ratings), 2) if ratings else None,
        "total_product_reviews": sum(reviews) if reviews else None,
        "products_with_reviews": len(reviews),
        "discounted_products": len(discounts),
        "average_discount_pct": round(statistics.mean(discounts), 2) if discounts else None,
    }

def build_local_competitor_candidates(products):
    return []

def make_ai_report(payload):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY غير موجود في ملف .env")

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    system = """
أنت Active Online Intelligence، محلل تجارة إلكترونية محترف متخصص في Trendyol.
مهمتك تحليل البيانات التي جمعها النظام بدقة واحترافية عالية باللغة العربية.
"""

    prompt = f"""
{system}

حلل متجر Trendyol التالي لصالح Active Online بناءً على البيانات الفعلية المستخرجة (بما في ذلك مقارنة الأسعار مع منافسين اثنين لكل منتج):

DATA:
{json.dumps(payload, ensure_ascii=False, indent=2)}

أريد تقريراً عميقاً، احترافياً، ومنظماً بالعربية يغطي الأقسام التالية:
1. Executive Summary (الملخص التنفيذي)
2. Store Health Score (تقييم صحة المتجر من 100 مع التبرير)
3. Store Metrics & Statistics (مقاييس المتجر والإحصائيات)
4. Product Portfolio Analysis (تحليل تشكيلة المنتجات)
5. Price Competitiveness & Top Competitors Benchmarking (تحليل تنافسية الأسعار مقارنة بأرخص منافسين في السوق)
6. Competitor Analysis & Market Gaps (تحليل المنافسين وفجوات السوق)
7. Competitive Attack Plan & 30-Day Action Plan (الخطة الهجومية التنافسية وخطة العمل لـ 30 يوماً)
8. Final Verdict (الحكم النهائي والتوصيات الاستراتيجية)
"""

    payload_body = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    try:
        response = requests.post(gemini_url, json=payload_body, timeout=60)
        if response.status_code == 200:
            res_json = response.json()
            return res_json['candidates'][0]['content']['parts'][0]['text']
        else:
            raise RuntimeError(f"خطأ من خادم جوجل: {response.text}")
    except Exception as exc:
        raise RuntimeError(f"Gemini API error: {exc}")

def analyze(url):
    started = time.time()
    resolved = resolve_url(url)

    store_info, products = collect_store_data(resolved)
    stats = calculate_stats(products)
    competitor_candidates = build_local_competitor_candidates(products)

    payload = {
        "store": store_info,
        "statistics": stats,
        "products": products,
        "competitor_candidates": competitor_candidates,
        "meta": {
            "resolved_url": resolved,
            "collection_time_seconds": round(time.time() - started, 2),
            "product_limit": MAX_PRODUCTS,
            "product_pages_limit": MAX_PRODUCT_PAGES,
        },
    }

    report = make_ai_report(payload)

    return {
        "status": "success",
        "store_info": store_info,
        "statistics": stats,
        "products": products,
        "competitors": competitor_candidates,
        "report": report,
        "meta": payload["meta"],
    }

@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(silent=True) or {}
    url = clean_text(data.get("url"))
    if not url:
        return jsonify({"error": "الرابط مطلوب"}), 400

    if "trendyol.com" not in url and "ty.gl" not in url:
        return jsonify({"error": "أدخل رابط Trendyol أو ty.gl صالح"}), 400

    try:
        result = analyze(url)
        return jsonify(result)
    except Exception as exc:
        return jsonify({
            "error": str(exc),
            "hint": "تأكد من صحة GEMINI_API_KEY في ملف .env."
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)