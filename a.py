import os
import json
import re
import html
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from bs4 import BeautifulSoup
import yfinance as yf

app = Flask(__name__)

# Constants
TRADES_FILE = "trades.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": USER_AGENT}

# Helper to load and save trades
def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_trades(trades):
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)

# Helper to parse numeric values safely
def parse_numeric(v):
    if v is None or v == "" or v == "-":
        return 0.0
    s = str(v).replace(',', '').replace('원', '').replace('%', '').strip()
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        nums = re.findall(r'-?\d+\.?\d*', s)
        return float(nums[0]) if nums else 0.0

# Fetch Naver Stock current price and info
def fetch_naver_stock_info(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
        soup = BeautifulSoup(res.content.decode("cp949", "ignore"), "html.parser")
        
        # Today's price
        price_el = soup.find("p", class_="no_today")
        price = 0
        if price_el:
            price_str = price_el.find("span", class_="blind").text.strip().replace(",", "")
            price = int(price_str)
            
        # Change (price diff & rate)
        change_el = soup.find("p", class_="no_exday")
        diff = 0
        rate = 0.0
        direction = "flat"
        if change_el:
            blind_spans = change_el.find_all("span", class_="blind")
            if len(blind_spans) >= 2:
                diff_str = blind_spans[0].text.strip().replace(",", "")
                diff = int(diff_str)
                
                # Check sign from ico (상승/하락/보합)
                ico_span = change_el.find("span", class_="ico")
                if ico_span:
                    ico_text = ico_span.text.strip()
                    if "상승" in ico_text or "상한" in ico_text:
                        direction = "up"
                    elif "하락" in ico_text or "하한" in ico_text:
                        direction = "down"
                        diff = -diff
                        
                rate_str = blind_spans[1].text.strip().replace("%", "").replace(",", "")
                rate = float(rate_str)
                if direction == "down":
                    rate = -rate
                    
        return {
            "current_price": price,
            "diff": diff,
            "rate": rate,
            "direction": direction
        }
    except Exception as e:
        print(f"Error fetching naver stock info for {code}: {e}")
        return {
            "current_price": 0,
            "diff": 0,
            "rate": 0.0,
            "direction": "flat"
        }

# Web Server Routes
@app.route('/')
def index():
    return render_template('dashboard.html')

# API: Get all trades
@app.route('/api/trades', methods=['GET'])
def get_trades_api():
    trades = load_trades()
    return jsonify(trades)

# API: Add a trade
@app.route('/api/trades', methods=['POST'])
def add_trade_api():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    required_fields = ["broker", "type", "stock_name", "stock_code", "price", "quantity", "date"]
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({"error": f"Missing required field: {field}"}), 400
            
    trades = load_trades()
    
    # Create new trade record
    new_trade = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "broker": data["broker"],
        "type": data["type"],  # 'buy' or 'sell'
        "stock_name": data["stock_name"],
        "stock_code": data["stock_code"],
        "price": int(parse_numeric(data["price"])),
        "quantity": int(data["quantity"]),
        "date": data["date"]
    }
    
    trades.append(new_trade)
    save_trades(trades)
    return jsonify({"success": True, "trade": new_trade})

# API: Delete a trade
@app.route('/api/trades/<trade_id>', methods=['DELETE'])
def delete_trade_api(trade_id):
    trades = load_trades()
    filtered_trades = [t for t in trades if t["id"] != trade_id]
    if len(trades) == len(filtered_trades):
        return jsonify({"error": "Trade not found"}), 404
        
    save_trades(filtered_trades)
    return jsonify({"success": True})

# API: Update a trade
@app.route('/api/trades/<trade_id>', methods=['PUT'])
def update_trade_api(trade_id):
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    required_fields = ["broker", "type", "stock_name", "stock_code", "price", "quantity", "date"]
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    trades = load_trades()
    trade_index = next((i for i, t in enumerate(trades) if t["id"] == trade_id), None)
    if trade_index is None:
        return jsonify({"error": "Trade not found"}), 404

    updated_trade = {
        "id": trade_id,
        "broker": data["broker"],
        "type": data["type"],
        "stock_name": data["stock_name"],
        "stock_code": data["stock_code"],
        "price": int(parse_numeric(data["price"])),
        "quantity": int(data["quantity"]),
        "date": data["date"]
    }

    trades[trade_index] = updated_trade
    save_trades(trades)
    return jsonify({"success": True, "trade": updated_trade})

# API: Get aggregated portfolio data
@app.route('/api/portfolio', methods=['GET'])
def get_portfolio_api():
    trades = load_trades()
    
    # Sort trades by date to calculate running average cost correctly
    sorted_trades = sorted(trades, key=lambda x: (x["date"], x.get("id", "")))
    
    portfolio = {}
    
    for t in sorted_trades:
        key = (t["broker"], t["stock_code"])
        if key not in portfolio:
            portfolio[key] = {
                "broker": t["broker"],
                "stock_code": t["stock_code"],
                "stock_name": t["stock_name"],
                "quantity": 0,
                "avg_price": 0.0,
                "total_cost": 0.0
            }
            
        stock = portfolio[key]
        q = t["quantity"]
        p = t["price"]
        
        if t["type"] == "buy":
            new_qty = stock["quantity"] + q
            if new_qty > 0:
                stock["avg_price"] = (stock["total_cost"] + (q * p)) / new_qty
            else:
                stock["avg_price"] = 0.0
            stock["quantity"] = new_qty
            stock["total_cost"] = stock["quantity"] * stock["avg_price"]
        elif t["type"] == "sell":
            new_qty = stock["quantity"] - q
            if new_qty <= 0:
                stock["quantity"] = 0
                stock["avg_price"] = 0.0
                stock["total_cost"] = 0.0
            else:
                stock["quantity"] = new_qty
                stock["total_cost"] = stock["quantity"] * stock["avg_price"]

    # Filter out empty positions
    active_holdings = [h for h in portfolio.values() if h["quantity"] > 0]
    
    # Fetch real-time quotes for active holdings
    total_invested = 0
    total_current = 0
    
    for h in active_holdings:
        code = h["stock_code"]
        info = fetch_naver_stock_info(code)
        
        h["current_price"] = info["current_price"]
        h["buy_amount"] = int(h["total_cost"])
        h["current_amount"] = int(h["quantity"] * h["current_price"])
        h["pnl"] = h["current_amount"] - h["buy_amount"]
        h["pnl_rate"] = ((h["pnl"] / h["buy_amount"]) * 100) if h["buy_amount"] > 0 else 0.0
        h["diff"] = info["diff"]
        h["rate"] = info["rate"]
        h["direction"] = info["direction"]
        
        total_invested += h["buy_amount"]
        total_current += h["current_amount"]
        
    total_pnl = total_current - total_invested
    total_return = ((total_pnl / total_invested) * 100) if total_invested > 0 else 0.0
    
    # Calculate weights
    for h in active_holdings:
        h["weight"] = ((h["current_amount"] / total_current) * 100) if total_current > 0 else 0.0
        
    # Sort by weight desc
    active_holdings = sorted(active_holdings, key=lambda x: x["weight"], reverse=True)
    
    return jsonify({
        "holdings": active_holdings,
        "summary": {
            "total_invested": total_invested,
            "total_current": total_current,
            "total_pnl": total_pnl,
            "total_return": total_return
        }
    })

# API: Get chart data for lightweight-charts
@app.route('/api/stock/<code_val>/chart', methods=['GET'])
def get_stock_chart_api(code_val):
    tf = request.args.get("tf", "daily")  # daily, weekly, monthly

    # yfinance ticker: 한국 주식은 종목코드 + ".KS" (코스피) 또는 ".KQ" (코스닥)
    # 먼저 .KS 시도, 데이터 없으면 .KQ 시도
    start_date = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")

    def fetch_yf(ticker_suffix):
        ticker = f"{code_val}{ticker_suffix}"
        df = yf.download(ticker, start=start_date, progress=False, auto_adjust=True)
        return df

    try:
        df = fetch_yf(".KS")
        if df.empty:
            df = fetch_yf(".KQ")
        if df.empty:
            return jsonify([])

        # yfinance 컬럼이 MultiIndex일 수 있으므로 평탄화
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)

        # Resample based on timeframe
        if tf == "weekly":
            df = df.resample('W').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
        elif tf == "monthly":
            df = df.resample('ME').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

        chart_data = []
        for idx, row in df.iterrows():
            chart_data.append({
                "time": idx.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "value": float(row["Close"])
            })
        return jsonify(chart_data)
    except Exception as e:
        print(f"Error fetching chart for {code_val}: {e}")
        return jsonify([])

# API: Get news for a stock
@app.route('/api/stock/<code_val>/news', methods=['GET'])
def get_stock_news_api(code_val):
    try:
        url = f"https://m.stock.naver.com/api/news/stock/{code_val}?pageSize=6"
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
        if res.status_code != 200:
            return jsonify([])
            
        data = res.json()
        news_list = []
        for group in data:
            for item in group.get("items", []):
                title = html.unescape(item.get("title", ""))
                office = item.get("officeName", "")
                office_id = item.get("officeId", "")
                article_id = item.get("articleId", "")
                dt_str = item.get("dt", "")
                link = f"https://n.news.naver.com/mnews/article/{office_id}/{article_id}"
                news_list.append({
                    "title": title,
                    "link": link,
                    "source": office,
                    "date": dt_str
                })
        return jsonify(news_list[:6])
    except Exception as e:
        print(f"Error fetching news for {code_val}: {e}")
        return jsonify([])

# API: Get disclosures for a stock
@app.route('/api/stock/<code_val>/disclosure', methods=['GET'])
def get_stock_disclosure_api(code_val):
    disclosures = []

    # 1차 시도: 네이버 공시 페이지 (여러 테이블 클래스 시도)
    try:
        url = f"https://finance.naver.com/item/disclosure.naver?code={code_val}"
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=7)
        html_text = res.content.decode("cp949", "ignore")
        soup = BeautifulSoup(html_text, "html.parser")
        table = (
            soup.find("table", class_="type5")
            or soup.find("table", class_="type_1")
            or soup.find("table", id="tbDisclosure")
        )
        if table:
            rows = table.find_all("tr")
            for r in rows:
                tds = r.find_all("td")
                if len(tds) >= 2:
                    date_val = tds[0].text.strip()
                    title_a = None
                    for td in tds:
                        title_a = td.find("a")
                        if title_a:
                            break
                    if title_a:
                        title = title_a.text.strip()
                        href = title_a.get("href", "")
                        if href.startswith("/"):
                            href = "https://finance.naver.com" + href
                        source = tds[-1].text.strip() if len(tds) >= 3 else ""
                        if title and date_val:
                            disclosures.append({
                                "title": title,
                                "link": href,
                                "source": source,
                                "date": date_val
                            })
    except Exception as e:
        print(f"[Disclosure] Naver parse error for {code_val}: {e}")

    # 2차 시도: 네이버 모바일 공시 API
    if not disclosures:
        try:
            url2 = f"https://m.stock.naver.com/api/disclosure/stock/{code_val}?pageSize=6"
            res2 = requests.get(url2, headers=DEFAULT_HEADERS, timeout=7)
            if res2.status_code == 200:
                data2 = res2.json()
                items = data2 if isinstance(data2, list) else data2.get("items", [])
                for item in items[:6]:
                    title = html.unescape(item.get("title", "") or item.get("subject", ""))
                    link = item.get("link", "") or item.get("url", "")
                    source = item.get("corpName", "") or item.get("source", "")
                    date_val = item.get("dt", "") or item.get("date", "")
                    if title:
                        disclosures.append({
                            "title": title,
                            "link": link,
                            "source": source,
                            "date": date_val
                        })
        except Exception as e:
            print(f"[Disclosure] Mobile API error for {code_val}: {e}")

    return jsonify(disclosures[:6])

# API: Get analyst reports for a stock
@app.route('/api/stock/<code_val>/reports', methods=['GET'])
def get_stock_reports_api(code_val):
    reports = []

    # 1차 시도: 네이버 리서치 (URL 패턴 2가지 시도)
    urls_to_try = [
        f"https://finance.naver.com/research/company_list.naver?searchType=itemCode&keyword={code_val}",
        f"https://finance.naver.com/research/company_list.naver?keyword={code_val}&brokerCode=&searchType=itemCode&page=1",
    ]
    for url in urls_to_try:
        if reports:
            break
        try:
            res = requests.get(url, headers=DEFAULT_HEADERS, timeout=7)
            html_text = res.content.decode("cp949", "ignore")
            soup = BeautifulSoup(html_text, "html.parser")

            # 여러 테이블 클래스명 시도
            table = (
                soup.find("table", class_="type_1")
                or soup.find("table", class_="type1")
                or soup.find("table", class_="research_list")
            )
            if not table:
                # 모든 테이블에서 리포트 행 탐색
                for tbl in soup.find_all("table"):
                    rows = tbl.find_all("tr")
                    if len(rows) > 2:
                        table = tbl
                        break

            if table:
                rows = table.find_all("tr")
                for r in rows:
                    tds = r.find_all("td")
                    if len(tds) >= 3:
                        title_a = tds[0].find("a")
                        if title_a:
                            title = title_a.text.strip()
                            href = title_a.get("href", "")
                            if href.startswith("/"):
                                href = "https://finance.naver.com" + href
                            elif not href.startswith("http"):
                                href = "https://finance.naver.com/research/" + href
                            source = tds[1].text.strip()
                            # 날짜는 마지막 또는 4번째 td
                            date_val = tds[-1].text.strip()
                            if title:
                                reports.append({
                                    "title": title,
                                    "link": href,
                                    "source": source,
                                    "date": date_val
                                })
        except Exception as e:
            print(f"[Reports] Naver parse error for {code_val}: {e}")

    # 2차 시도: 네이버 모바일 리포트 API
    if not reports:
        try:
            url2 = f"https://m.stock.naver.com/api/research/stock/{code_val}?pageSize=6"
            res2 = requests.get(url2, headers=DEFAULT_HEADERS, timeout=7)
            if res2.status_code == 200:
                data2 = res2.json()
                items = data2 if isinstance(data2, list) else data2.get("items", [])
                for item in items[:6]:
                    title = html.unescape(item.get("title", "") or item.get("reportTitle", ""))
                    link = item.get("link", "") or item.get("url", "")
                    source = item.get("officeName", "") or item.get("brokerName", "")
                    date_val = item.get("dt", "") or item.get("date", "")
                    if title:
                        reports.append({
                            "title": title,
                            "link": link,
                            "source": source,
                            "date": date_val
                        })
        except Exception as e:
            print(f"[Reports] Mobile API error for {code_val}: {e}")

    return jsonify(reports[:6])

# API: Get financials
@app.route('/api/stock/<code_val>/financials', methods=['GET'])
def get_stock_financials_api(code_val):
    url = f"https://finance.naver.com/item/main.naver?code={code_val}"
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=7)

        # cp949 디코딩 후 유니코드 정규화로 깨짐 방지
        raw_html = res.content.decode("cp949", "replace")

        soup = BeautifulSoup(raw_html, "html.parser")

        cop = soup.find("div", class_="cop_analysis")
        if not cop:
            return jsonify({"error": "No financials found"}), 404

        tbl = cop.find("table")
        if not tbl:
            return jsonify({"error": "No table found"}), 404

        thead = tbl.find("thead")
        tbody = tbl.find("tbody")

        def clean_text(text):
            """깨진 문자 및 불필요한 공백/특수문자 제거"""
            if not text:
                return ""
            # 대체 문자(?) 제거, 연속 공백 정리
            text = text.replace("\xa0", " ").replace("\ufffd", "").strip()
            text = re.sub(r'\s+', ' ', text)
            return text

        headers = []
        if thead:
            trs = thead.find_all("tr")
            tr = trs[1] if len(trs) > 1 else trs[0] if trs else None
            if tr:
                for th in tr.find_all("th"):
                    headers.append(clean_text(th.get_text()))

        rows = []
        if tbody:
            for tr in tbody.find_all("tr"):
                th = tr.find("th")
                tds = tr.find_all("td")
                if th:
                    row_name = clean_text(th.get_text())
                    row_vals = [clean_text(td.get_text()) for td in tds]
                    if row_name:
                        rows.append({
                            "metric": row_name,
                            "values": row_vals
                        })

        return jsonify({
            "headers": headers,
            "rows": rows
        })
    except Exception as e:
        print(f"Error fetching financials for {code_val}: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    load_trades()
    app.run(debug=True, port=5000)
