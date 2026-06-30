import os
import json
import re
import html
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import yfinance as yf
import plotly.graph_objects as go

# ─────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="주식 포트폴리오",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

def html_block(content):
    """들여쓰기를 제거하고 한 줄로 합쳐 st.markdown이 코드블록으로 잘못 인식하지 않도록 함"""
    lines = [line.strip() for line in content.strip().splitlines()]
    st.markdown("".join(lines), unsafe_allow_html=True)

# ─────────────────────────────────────────
# 상수
# ─────────────────────────────────────────
TRADES_FILE = "trades.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": USER_AGENT}

# ─────────────────────────────────────────
# CSS 스타일
# ─────────────────────────────────────────
st.markdown("""
<style>
/* 전체 배경 */
.stApp { background-color: #0e1117; color: #e0e0e0; }

/* 카드 스타일 */
.metric-card {
    background: #1e2130;
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 8px;
    border: 1px solid #2d3250;
}
.metric-label { font-size: 13px; color: #888; margin-bottom: 4px; }
.metric-value { font-size: 24px; font-weight: 700; color: #fff; }
.metric-sub   { font-size: 13px; margin-top: 4px; }

/* 등락 색상 */
.up   { color: #ef5350; }
.down { color: #26a69a; }
.flat { color: #aaa; }

/* 테이블 */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th {
    background: #1a1f35;
    color: #aaa;
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid #2d3250;
    white-space: nowrap;
}
.data-table td {
    padding: 10px 12px;
    border-bottom: 1px solid #1e2130;
    color: #ddd;
    white-space: nowrap;
}
.data-table tr:hover td { background: #1a2040; }

/* 뉴스/공시 카드 */
.news-item {
    background: #1e2130;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
    border-left: 3px solid #3f51b5;
}
.news-title { font-size: 14px; font-weight: 600; color: #e0e0e0; }
.news-meta  { font-size: 12px; color: #888; margin-top: 4px; }

/* 섹션 헤더 */
.section-header {
    font-size: 16px;
    font-weight: 700;
    color: #fff;
    padding: 8px 0;
    border-bottom: 2px solid #3f51b5;
    margin-bottom: 16px;
}

/* 탭 */
div[data-baseweb="tab-list"] { background: #1e2130 !important; border-radius: 8px; }
div[data-baseweb="tab"]      { color: #aaa !important; }
div[aria-selected="true"]    { color: #fff !important; }

/* 버튼 */
.stButton > button {
    background: #3f51b5;
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 13px;
}
.stButton > button:hover { background: #5c6bc0; }

/* 입력 필드 */
.stSelectbox > div, .stTextInput > div > div, .stNumberInput > div > div {
    background: #1e2130 !important;
    border: 1px solid #2d3250 !important;
    color: #e0e0e0 !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# 데이터 헬퍼
# ─────────────────────────────────────────
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

def parse_numeric(v):
    if v is None or v == "" or v == "-":
        return 0.0
    s = str(v).replace(',', '').replace('원', '').replace('%', '').strip().replace(" ", "")
    try:
        return float(s)
    except ValueError:
        nums = re.findall(r'-?\d+\.?\d*', s)
        return float(nums[0]) if nums else 0.0

def fmt_num(n):
    """숫자 천단위 콤마"""
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def fmt_pct(n):
    color = "up" if n > 0 else "down" if n < 0 else "flat"
    sign  = "+" if n > 0 else ""
    return f'<span class="{color}">{sign}{n:.2f}%</span>'

def fmt_pnl(n):
    color = "up" if n > 0 else "down" if n < 0 else "flat"
    sign  = "+" if n > 0 else ""
    return f'<span class="{color}">{sign}{fmt_num(n)}원</span>'


# ─────────────────────────────────────────
# 네이버 현재가 조회
# ─────────────────────────────────────────
@st.cache_data(ttl=60)
def fetch_naver_stock_info(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
        soup = BeautifulSoup(res.content.decode("cp949", "ignore"), "html.parser")

        price_el = soup.find("p", class_="no_today")
        price = 0
        if price_el:
            blind = price_el.find("span", class_="blind")
            if blind:
                price = int(blind.text.strip().replace(",", ""))

        change_el = soup.find("p", class_="no_exday")
        diff, rate, direction = 0, 0.0, "flat"
        if change_el:
            blind_spans = change_el.find_all("span", class_="blind")
            if len(blind_spans) >= 2:
                diff = int(blind_spans[0].text.strip().replace(",", ""))
                ico  = change_el.find("span", class_="ico")
                if ico:
                    t = ico.text.strip()
                    if "상승" in t or "상한" in t:
                        direction = "up"
                    elif "하락" in t or "하한" in t:
                        direction = "down"
                        diff = -diff
                rate = float(blind_spans[1].text.strip().replace("%", "").replace(",", ""))
                if direction == "down":
                    rate = -rate

        return {"current_price": price, "diff": diff, "rate": rate, "direction": direction}
    except Exception:
        return {"current_price": 0, "diff": 0, "rate": 0.0, "direction": "flat"}

# ─────────────────────────────────────────
# 포트폴리오 계산
# ─────────────────────────────────────────
def calc_portfolio(trades):
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
                "total_cost": 0.0,
            }
        s = portfolio[key]
        q, p = t["quantity"], t["price"]

        if t["type"] == "buy":
            new_qty = s["quantity"] + q
            s["avg_price"] = (s["total_cost"] + q * p) / new_qty if new_qty > 0 else 0.0
            s["quantity"] = new_qty
            s["total_cost"] = s["quantity"] * s["avg_price"]
        elif t["type"] == "sell":
            new_qty = s["quantity"] - q
            if new_qty <= 0:
                s["quantity"] = 0; s["avg_price"] = 0.0; s["total_cost"] = 0.0
            else:
                s["quantity"] = new_qty
                s["total_cost"] = s["quantity"] * s["avg_price"]

    active = [h for h in portfolio.values() if h["quantity"] > 0]
    total_inv, total_cur = 0, 0

    for h in active:
        info = fetch_naver_stock_info(h["stock_code"])
        h["current_price"] = info["current_price"]
        h["buy_amount"]    = int(h["total_cost"])
        h["current_amount"]= int(h["quantity"] * h["current_price"])
        h["pnl"]           = h["current_amount"] - h["buy_amount"]
        h["pnl_rate"]      = (h["pnl"] / h["buy_amount"] * 100) if h["buy_amount"] > 0 else 0.0
        h["diff"]          = info["diff"]
        h["rate"]          = info["rate"]
        h["direction"]     = info["direction"]
        total_inv += h["buy_amount"]
        total_cur += h["current_amount"]

    total_pnl    = total_cur - total_inv
    total_return = (total_pnl / total_inv * 100) if total_inv > 0 else 0.0

    for h in active:
        h["weight"] = (h["current_amount"] / total_cur * 100) if total_cur > 0 else 0.0

    active.sort(key=lambda x: x["weight"], reverse=True)
    return active, {"total_invested": total_inv, "total_current": total_cur,
                    "total_pnl": total_pnl, "total_return": total_return}

# ─────────────────────────────────────────
# 차트 데이터
# ─────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_chart(code, tf="daily"):
    start = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    for suffix in [".KS", ".KQ"]:
        try:
            df = yf.download(f"{code}{suffix}", start=start, progress=False, auto_adjust=True)
            if df.empty:
                continue
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
            if tf == "weekly":
                df = df.resample("W").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            elif tf == "monthly":
                df = df.resample("ME").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
            return df
        except Exception:
            continue
    return pd.DataFrame()

# ─────────────────────────────────────────
# 뉴스
# ─────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_news(code):
    try:
        url  = f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=6"
        res  = requests.get(url, headers=DEFAULT_HEADERS, timeout=5)
        data = res.json()
        items = []
        for group in data:
            for item in group.get("items", []):
                oid = item.get("officeId", "")
                aid = item.get("articleId", "")
                items.append({
                    "title":  html.unescape(item.get("title", "")),
                    "link":   f"https://n.news.naver.com/mnews/article/{oid}/{aid}",
                    "source": item.get("officeName", ""),
                    "date":   item.get("dt", ""),
                })
        return items[:6]
    except Exception:
        return []

# ─────────────────────────────────────────
# 공시
# ─────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_disclosure(code):
    disclosures = []
    try:
        url  = f"https://finance.naver.com/item/disclosure.naver?code={code}"
        res  = requests.get(url, headers=DEFAULT_HEADERS, timeout=7)
        soup = BeautifulSoup(res.content.decode("cp949", "ignore"), "html.parser")
        table = (soup.find("table", class_="type5")
                 or soup.find("table", class_="type_1")
                 or soup.find("table", id="tbDisclosure"))
        if table:
            for r in table.find_all("tr"):
                tds = r.find_all("td")
                if len(tds) >= 2:
                    date_val = tds[0].text.strip()
                    title_a  = next((td.find("a") for td in tds if td.find("a")), None)
                    if title_a and date_val:
                        href = title_a.get("href", "")
                        if href.startswith("/"):
                            href = "https://finance.naver.com" + href
                        disclosures.append({
                            "title":  title_a.text.strip(),
                            "link":   href,
                            "source": tds[-1].text.strip() if len(tds) >= 3 else "",
                            "date":   date_val,
                        })
    except Exception:
        pass

    if not disclosures:
        try:
            url2 = f"https://m.stock.naver.com/api/disclosure/stock/{code}?pageSize=6"
            res2 = requests.get(url2, headers=DEFAULT_HEADERS, timeout=7)
            if res2.status_code == 200:
                data2 = res2.json()
                items = data2 if isinstance(data2, list) else data2.get("items", [])
                for item in items[:6]:
                    title = html.unescape(item.get("title", "") or item.get("subject", ""))
                    if title:
                        disclosures.append({
                            "title":  title,
                            "link":   item.get("link", "") or item.get("url", ""),
                            "source": item.get("corpName", "") or item.get("source", ""),
                            "date":   item.get("dt", "") or item.get("date", ""),
                        })
        except Exception:
            pass

    return disclosures[:6]

# ─────────────────────────────────────────
# 분석리포트
# ─────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_reports(code):
    reports = []
    for url in [
        f"https://finance.naver.com/research/company_list.naver?searchType=itemCode&keyword={code}",
        f"https://finance.naver.com/research/company_list.naver?keyword={code}&brokerCode=&searchType=itemCode&page=1",
    ]:
        if reports:
            break
        try:
            res  = requests.get(url, headers=DEFAULT_HEADERS, timeout=7)
            soup = BeautifulSoup(res.content.decode("cp949", "ignore"), "html.parser")
            table = (soup.find("table", class_="type_1")
                     or soup.find("table", class_="type1")
                     or soup.find("table", class_="research_list"))
            if not table:
                for tbl in soup.find_all("table"):
                    if len(tbl.find_all("tr")) > 2:
                        table = tbl; break
            if table:
                for r in table.find_all("tr"):
                    tds = r.find_all("td")
                    if len(tds) >= 3:
                        title_a = tds[0].find("a")
                        if title_a:
                            href = title_a.get("href", "")
                            if href.startswith("/"):
                                href = "https://finance.naver.com" + href
                            elif not href.startswith("http"):
                                href = "https://finance.naver.com/research/" + href
                            reports.append({
                                "title":  title_a.text.strip(),
                                "link":   href,
                                "source": tds[1].text.strip(),
                                "date":   tds[-1].text.strip(),
                            })
        except Exception:
            pass

    if not reports:
        try:
            url2 = f"https://m.stock.naver.com/api/research/stock/{code}?pageSize=6"
            res2 = requests.get(url2, headers=DEFAULT_HEADERS, timeout=7)
            if res2.status_code == 200:
                data2 = res2.json()
                items = data2 if isinstance(data2, list) else data2.get("items", [])
                for item in items[:6]:
                    title = html.unescape(item.get("title", "") or item.get("reportTitle", ""))
                    if title:
                        reports.append({
                            "title":  title,
                            "link":   item.get("link", "") or item.get("url", ""),
                            "source": item.get("officeName", "") or item.get("brokerName", ""),
                            "date":   item.get("dt", "") or item.get("date", ""),
                        })
        except Exception:
            pass

    return reports[:6]

# ─────────────────────────────────────────
# 재무정보
# ─────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_financials(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=7)

        # cp949로 먼저 시도, 실패 시 euc-kr → utf-8 순으로 fallback
        raw_bytes = res.content
        raw_html = None
        for enc in ["cp949", "euc-kr", "utf-8"]:
            try:
                decoded = raw_bytes.decode(enc)
                # 깨진 문자 없이 디코딩 성공했는지 확인
                if "\ufffd" not in decoded:
                    raw_html = decoded
                    break
            except (UnicodeDecodeError, LookupError):
                continue
        if raw_html is None:
            # 어떤 인코딩도 완벽하지 않으면 cp949 errors=ignore 사용
            raw_html = raw_bytes.decode("cp949", "ignore")

        # BeautifulSoup에 from_encoding 지정으로 내부 재인코딩 방지
        soup = BeautifulSoup(raw_bytes, "html.parser", from_encoding="cp949")
        cop  = soup.find("div", class_="cop_analysis")
        if not cop:
            return None
        tbl = cop.find("table")
        if not tbl:
            return None

        def clean(text):
            if not text:
                return ""
            # nbsp, 대체문자, 제어문자 제거 후 공백 정리
            text = text.replace("\xa0", " ").replace("\u3000", " ")
            text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text

        thead, tbody = tbl.find("thead"), tbl.find("tbody")
        headers = []
        if thead:
            trs = thead.find_all("tr")
            tr  = trs[1] if len(trs) > 1 else (trs[0] if trs else None)
            if tr:
                headers = [clean(th.get_text()) for th in tr.find_all("th")]

        rows = []
        if tbody:
            for tr in tbody.find_all("tr"):
                th  = tr.find("th")
                tds = tr.find_all("td")
                if th:
                    row_name = clean(th.get_text())
                    if row_name:
                        rows.append([row_name] + [clean(td.get_text()) for td in tds])

        if headers and rows:
            # 중복 컬럼명 처리: 같은 이름이 있으면 _2, _3 suffix 추가
            all_cols = ["항목"] + headers
            seen = {}
            unique_cols = []
            for col in all_cols:
                if col in seen:
                    seen[col] += 1
                    unique_cols.append(f"{col}_{seen[col]}")
                else:
                    seen[col] = 1
                    unique_cols.append(col)

            # 행 길이가 컬럼 수와 맞지 않으면 맞춰줌
            n_cols = len(unique_cols)
            fixed_rows = []
            for row in rows:
                if len(row) < n_cols:
                    row = row + [""] * (n_cols - len(row))
                elif len(row) > n_cols:
                    row = row[:n_cols]
                fixed_rows.append(row)

            df = pd.DataFrame(fixed_rows, columns=unique_cols)
            return df
    except Exception as e:
        print(f"[Financials] Error: {e}")
    return None

# ─────────────────────────────────────────
# 세션 상태 초기화
# ─────────────────────────────────────────
if "trades" not in st.session_state:
    st.session_state.trades = load_trades()
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None
if "edit_trade_id" not in st.session_state:
    st.session_state.edit_trade_id = None
if "page" not in st.session_state:
    st.session_state.page = "portfolio"

# ─────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 주식 포트폴리오")
    st.markdown("---")
    if st.button("🏠 포트폴리오", use_container_width=True):
        st.session_state.page = "portfolio"
        st.session_state.selected_stock = None
        st.rerun()
    if st.button("📋 거래내역", use_container_width=True):
        st.session_state.page = "trades"
        st.rerun()
    if st.button("➕ 거래 등록", use_container_width=True):
        st.session_state.page = "add_trade"
        st.rerun()

    st.markdown("---")
    st.markdown(f"<small style='color:#666'>최종 업데이트<br>{datetime.now().strftime('%Y-%m-%d %H:%M')}</small>",
                unsafe_allow_html=True)

# ─────────────────────────────────────────
# 종목 상세 페이지
# ─────────────────────────────────────────
def render_stock_detail(stock):
    code = stock["stock_code"]
    name = stock["stock_name"]

    if st.button("← 뒤로"):
        st.session_state.selected_stock = None
        st.rerun()

    st.markdown(f"## {name} ({code})")

    # 현재가 요약
    info = fetch_naver_stock_info(code)
    c1, c2, c3 = st.columns(3)
    with c1:
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">현재가</div>
            <div class="metric-value">{fmt_num(info['current_price'])}원</div>
            <div class="metric-sub {info['direction']}">
                {'▲' if info['direction']=='up' else '▼' if info['direction']=='down' else '▶'}
                {fmt_num(abs(info['diff']))}원 ({'+' if info['rate']>0 else ''}{info['rate']:.2f}%)
            </div>
        </div>""")
    with c2:
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">평균단가 / 보유수량</div>
            <div class="metric-value">{fmt_num(int(stock['avg_price']))}원</div>
            <div class="metric-sub flat">{fmt_num(stock['quantity'])}주</div>
        </div>""")
    with c3:
        pnl_cls = "up" if stock['pnl'] > 0 else "down" if stock['pnl'] < 0 else "flat"
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">평가손익</div>
            <div class="metric-value {pnl_cls}">{'+' if stock['pnl']>0 else ''}{fmt_num(stock['pnl'])}원</div>
            <div class="metric-sub {pnl_cls}">{'+' if stock['pnl_rate']>0 else ''}{stock['pnl_rate']:.2f}%</div>
        </div>""")

    # 차트
    st.markdown("---")
    tf_label = {"일봉": "daily", "주봉": "weekly", "월봉": "monthly"}
    tf_sel   = st.radio("차트 주기", list(tf_label.keys()), horizontal=True)
    tf       = tf_label[tf_sel]

    df = fetch_chart(code, tf)
    if not df.empty:
        fig = go.Figure(data=[go.Candlestick(
            x=df.index,
            open=df["Open"], high=df["High"],
            low=df["Low"],   close=df["Close"],
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
        )])
        fig.update_layout(
            paper_bgcolor="#1e2130", plot_bgcolor="#1e2130",
            font=dict(color="#aaa"),
            xaxis=dict(gridcolor="#2d3250", rangeslider=dict(visible=False)),
            yaxis=dict(gridcolor="#2d3250"),
            height=420, margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("차트 데이터를 불러올 수 없습니다.")

    # 탭: 뉴스 / 공시 / 리포트 / 재무
    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs(["📰 뉴스", "📢 공시정보", "📊 분석리포트", "💹 재무정보"])

    with tab1:
        news = fetch_news(code)
        if news:
            for n in news:
                html_block(f"""
                <div class="news-item">
                    <div class="news-title"><a href="{n['link']}" target="_blank" style="color:#90caf9;text-decoration:none">{n['title']}</a></div>
                    <div class="news-meta">{n['source']} · {n['date']}</div>
                </div>""")
        else:
            st.info("뉴스가 없습니다.")

    with tab2:
        disclosures = fetch_disclosure(code)
        if disclosures:
            for d in disclosures:
                html_block(f"""
                <div class="news-item" style="border-left-color:#ff7043">
                    <div class="news-title"><a href="{d['link']}" target="_blank" style="color:#90caf9;text-decoration:none">{d['title']}</a></div>
                    <div class="news-meta">{d['source']} · {d['date']}</div>
                </div>""")
        else:
            st.info("공시정보가 없습니다.")

    with tab3:
        reports = fetch_reports(code)
        if reports:
            for r in reports:
                html_block(f"""
                <div class="news-item" style="border-left-color:#66bb6a">
                    <div class="news-title"><a href="{r['link']}" target="_blank" style="color:#90caf9;text-decoration:none">{r['title']}</a></div>
                    <div class="news-meta">{r['source']} · {r['date']}</div>
                </div>""")
        else:
            st.info("분석리포트가 없습니다.")

    with tab4:
        df_fin = fetch_financials(code)
        if df_fin is not None:
            st.dataframe(df_fin, use_container_width=True, hide_index=True)
        else:
            st.info("재무정보를 불러올 수 없습니다.")


# ─────────────────────────────────────────
# 포트폴리오 페이지
# ─────────────────────────────────────────
def render_portfolio():
    if st.session_state.selected_stock:
        render_stock_detail(st.session_state.selected_stock)
        return

    st.markdown("## 🏠 포트폴리오 현황")

    trades = st.session_state.trades
    if not trades:
        st.info("등록된 거래가 없습니다. 사이드바에서 거래를 등록해주세요.")
        return

    with st.spinner("현재가 조회 중..."):
        holdings, summary = calc_portfolio(trades)

    # 요약 카드
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">총 매수금액</div>
            <div class="metric-value">{fmt_num(summary['total_invested'])}원</div>
        </div>""")
    with c2:
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">총 평가금액</div>
            <div class="metric-value">{fmt_num(summary['total_current'])}원</div>
        </div>""")
    with c3:
        cls = "up" if summary['total_pnl'] > 0 else "down" if summary['total_pnl'] < 0 else "flat"
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">총 평가손익</div>
            <div class="metric-value {cls}">{'+' if summary['total_pnl']>0 else ''}{fmt_num(summary['total_pnl'])}원</div>
        </div>""")
    with c4:
        cls = "up" if summary['total_return'] > 0 else "down" if summary['total_return'] < 0 else "flat"
        html_block(f"""
        <div class="metric-card">
            <div class="metric-label">수익률</div>
            <div class="metric-value {cls}">{'+' if summary['total_return']>0 else ''}{summary['total_return']:.2f}%</div>
        </div>""")

    st.markdown("---")
    st.markdown('<div class="section-header">보유 종목</div>', unsafe_allow_html=True)

    # 종목 테이블 (한 줄 HTML로 생성 — 멀티라인 문자열은 마크다운이 코드블록으로 잘못 인식할 수 있음)
    table_rows = ""
    for h in holdings:
        d_cls  = h["direction"]
        d_icon = "▲" if d_cls == "up" else "▼" if d_cls == "down" else "▶"
        pnl_cls = "up" if h['pnl_rate'] > 0 else "down" if h['pnl_rate'] < 0 else "flat"
        table_rows += (
            "<tr>"
            f"<td>{h['broker']}</td>"
            f"<td><b>{h['stock_name']}</b><br><small style='color:#666'>{h['stock_code']}</small></td>"
            f"<td>{fmt_num(h['current_price'])}</td>"
            f"<td class='{d_cls}'>{d_icon} {fmt_num(abs(h['diff']))} ({'+' if h['rate']>0 else ''}{h['rate']:.2f}%)</td>"
            f"<td>{fmt_num(int(h['avg_price']))}</td>"
            f"<td>{fmt_num(h['quantity'])}</td>"
            f"<td>{fmt_num(h['buy_amount'])}</td>"
            f"<td>{fmt_num(h['current_amount'])}</td>"
            f"<td>{'+' if h['pnl']>0 else ''}{fmt_num(h['pnl'])}</td>"
            f"<td class='{pnl_cls}'>{'+' if h['pnl_rate']>0 else ''}{h['pnl_rate']:.2f}%</td>"
            f"<td>{h['weight']:.1f}%</td>"
            "</tr>"
        )

    table_html = (
        "<table class='data-table'><thead><tr>"
        "<th>증권사</th><th>종목명</th><th>현재가</th><th>등락</th>"
        "<th>평균단가</th><th>수량</th><th>매수금액</th><th>평가금액</th>"
        "<th>평가손익</th><th>수익률</th><th>비중</th>"
        "</tr></thead><tbody>" + table_rows + "</tbody></table>"
    )

    st.markdown(table_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**종목을 클릭하면 상세 정보를 볼 수 있습니다.**", unsafe_allow_html=True)

    # 종목 선택 버튼
    cols = st.columns(min(len(holdings), 5))
    for i, h in enumerate(holdings):
        with cols[i % 5]:
            if st.button(f"📈 {h['stock_name']}", key=f"stock_{h['stock_code']}_{h['broker']}"):
                st.session_state.selected_stock = h
                st.rerun()

# ─────────────────────────────────────────
# 거래 내역 페이지
# ─────────────────────────────────────────
def render_trades():
    st.markdown("## 📋 거래내역")

    trades = st.session_state.trades
    if not trades:
        st.info("등록된 거래가 없습니다.")
        return

    # 수정 모달 (edit_trade_id 세팅된 경우)
    if st.session_state.edit_trade_id:
        trade = next((t for t in trades if t["id"] == st.session_state.edit_trade_id), None)
        if trade:
            st.markdown("### ✏️ 거래 수정")
            with st.form("edit_form"):
                c1, c2 = st.columns(2)
                with c1:
                    broker     = st.text_input("증권사",    value=trade["broker"])
                    trade_type = st.selectbox("구분", ["buy","sell"],
                                              index=0 if trade["type"]=="buy" else 1,
                                              format_func=lambda x: "매수" if x=="buy" else "매도")
                    stock_name = st.text_input("종목명",    value=trade["stock_name"])
                with c2:
                    stock_code = st.text_input("종목코드",  value=trade["stock_code"])
                    price      = st.number_input("거래가격", value=int(trade["price"]), min_value=0, step=100)
                    quantity   = st.number_input("수량",    value=int(trade["quantity"]), min_value=1, step=1)
                date = st.date_input("거래일자",
                                     value=datetime.strptime(trade["date"], "%Y-%m-%d").date())

                col_save, col_cancel = st.columns(2)
                with col_save:
                    if st.form_submit_button("💾 저장", use_container_width=True):
                        idx = next((i for i,t in enumerate(trades) if t["id"] == trade["id"]), None)
                        if idx is not None:
                            trades[idx] = {
                                "id":         trade["id"],
                                "broker":     broker,
                                "type":       trade_type,
                                "stock_name": stock_name,
                                "stock_code": stock_code,
                                "price":      int(price),
                                "quantity":   int(quantity),
                                "date":       date.strftime("%Y-%m-%d"),
                            }
                            save_trades(trades)
                            st.session_state.trades = trades
                            st.session_state.edit_trade_id = None
                            st.success("수정되었습니다.")
                            st.rerun()
                with col_cancel:
                    if st.form_submit_button("✕ 취소", use_container_width=True):
                        st.session_state.edit_trade_id = None
                        st.rerun()
            st.markdown("---")

    # 거래 목록
    sorted_trades = sorted(trades, key=lambda x: x["date"], reverse=True)
    for t in sorted_trades:
        type_label = "🔴 매수" if t["type"] == "buy" else "🔵 매도"
        amount     = fmt_num(t["price"] * t["quantity"])
        with st.container():
            c1, c2, c3 = st.columns([6, 1, 1])
            with c1:
                html_block(f"""
                <div class="news-item" style="border-left-color:{'#ef5350' if t['type']=='buy' else '#26a69a'}">
                    <div class="news-title">{type_label} &nbsp; <b>{t['stock_name']}</b> ({t['stock_code']}) &nbsp; [{t['broker']}]</div>
                    <div class="news-meta">
                        {t['date']} &nbsp;|&nbsp;
                        {fmt_num(t['price'])}원 × {fmt_num(t['quantity'])}주 &nbsp;=&nbsp; {amount}원
                    </div>
                </div>""")
            with c2:
                if st.button("✏️", key=f"edit_{t['id']}", help="수정"):
                    st.session_state.edit_trade_id = t["id"]
                    st.rerun()
            with c3:
                if st.button("🗑️", key=f"del_{t['id']}", help="삭제"):
                    st.session_state.trades = [x for x in trades if x["id"] != t["id"]]
                    save_trades(st.session_state.trades)
                    st.success("삭제되었습니다.")
                    st.rerun()

# ─────────────────────────────────────────
# 거래 등록 페이지
# ─────────────────────────────────────────
def render_add_trade():
    st.markdown("## ➕ 거래 등록")

    with st.form("add_trade_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            broker     = st.text_input("증권사 *",   placeholder="예: 키움, 미래에셋")
            trade_type = st.selectbox("구분 *", ["buy", "sell"],
                                      format_func=lambda x: "매수" if x == "buy" else "매도")
            stock_name = st.text_input("종목명 *",   placeholder="예: 삼성전자")
        with c2:
            stock_code = st.text_input("종목코드 *", placeholder="예: 005930")
            price      = st.number_input("거래가격 *", min_value=0, step=100, value=0)
            quantity   = st.number_input("수량 *",    min_value=1, step=1,   value=1)
        date = st.date_input("거래일자 *", value=datetime.today())

        submitted = st.form_submit_button("등록", use_container_width=True)
        if submitted:
            if not all([broker, stock_name, stock_code, price > 0]):
                st.error("모든 항목을 입력해주세요.")
            else:
                new_trade = {
                    "id":         datetime.now().strftime("%Y%m%d%H%M%S%f"),
                    "broker":     broker,
                    "type":       trade_type,
                    "stock_name": stock_name,
                    "stock_code": stock_code,
                    "price":      int(price),
                    "quantity":   int(quantity),
                    "date":       date.strftime("%Y-%m-%d"),
                }
                st.session_state.trades.append(new_trade)
                save_trades(st.session_state.trades)
                st.success(f"✅ {stock_name} {('매수' if trade_type=='buy' else '매도')} 거래가 등록되었습니다.")
                st.session_state.page = "trades"
                st.rerun()

# ─────────────────────────────────────────
# 라우팅
# ─────────────────────────────────────────
page = st.session_state.page

if page == "portfolio":
    render_portfolio()
elif page == "trades":
    render_trades()
elif page == "add_trade":
    render_add_trade()
