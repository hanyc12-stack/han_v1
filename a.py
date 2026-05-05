import streamlit as st
import pandas as pd
import numpy as np
import requests
import html
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import FinanceDataReader as fdr
from bs4 import BeautifulSoup
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================================================
# 상수 정의
# ============================================================
PAGE_TITLE = "Hstock Smart Dashboard"
PAGE_ICON = "🔍"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": USER_AGENT}
REQUEST_TIMEOUT = 5

NAVER_FINANCE_BASE = "https://finance.naver.com"
ITEM_MAIN_URL = f"{NAVER_FINANCE_BASE}/item/main.naver?code={{code}}"

# 모바일 API (뉴스용 — PC 스크래핑 차단 대응)
NAVER_NEWS_API = "https://m.stock.naver.com/api/news/stock/{code}?pageSize={count}"

TOP_N = 200          # 시가총액 상위 N 종목
TOP_RESULT = 10      # 최종 표시할 저평가 종목 수
MAX_NEWS = 5         # 뉴스 최대 표시 수
THREAD_WORKERS = 25  # 병렬 요청 수
CHART_DAYS = 120     # 차트 표시 기간 (일)

CACHE_TTL = 3600     # 캐시 유효 시간 (초)


# ============================================================
# 1. 페이지 설정 및 커스텀 스타일
# ============================================================
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;600;700&display=swap');

    * { font-family: 'Pretendard', sans-serif; }
    .stApp { background-color: #f2f2f7; }

    /* 메인 컨테이너 패딩 조절 */
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }

    /* 카드 컨테이너 */
    .card {
        background: white;
        padding: 24px;
        border-radius: 20px;
        box-shadow: 0 8px 30px rgba(0,0,0,0.04);
        margin-bottom: 24px;
        border: 1px solid rgba(0,0,0,0.05);
    }

    /* 섹션 타이틀 */
    .search-title {
        font-size: 22px;
        font-weight: 700;
        color: #1c1c1e;
        margin-bottom: 18px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    /* 뉴스 아이템 */
    .news-item {
        padding: 12px 0;
        border-bottom: 1px solid #f2f2f7;
    }
    .news-link {
        text-decoration: none;
        color: #007aff !important;
        font-weight: 600;
        font-size: 15px;
        line-height: 1.5;
    }
    .news-meta {
        font-size: 12px;
        color: #8a8a8e;
        margin-top: 4px;
        display: block;
    }

    /* 지표 박스 */
    .metric-box {
        background: #f9f9fb;
        padding: 16px;
        border-radius: 16px;
        text-align: center;
        border: 1px solid #efeff4;
        transition: transform 0.2s;
    }
    .metric-box:hover { transform: translateY(-2px); }
    .metric-label {
        font-size: 12px;
        color: #8a8a8e;
        margin-bottom: 6px;
        font-weight: 500;
    }
    .metric-value {
        font-size: 18px;
        font-weight: 700;
        color: #1c1c1e;
    }

    /* 버튼 스타일 커스텀 */
    .stButton>button {
        border-radius: 12px;
        font-weight: 600;
        border: none;
        transition: all 0.2s;
    }

    /* 모바일 대응 (600px 이하) */
    @media (max-width: 600px) {
        .card { padding: 16px; border-radius: 16px; }
        .search-title { font-size: 18px; }
        .metric-value { font-size: 15px; }
        .metric-box { padding: 10px; }
        .news-link { font-size: 13px; }
        [data-testid="stHorizontalBlock"] { gap: 8px !important; }
        .stMarkdown div p { font-size: 13px; }
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ============================================================
# 2. 데이터 수집 함수
# ============================================================

@st.cache_data(ttl=CACHE_TTL)
def load_stocks() -> pd.DataFrame:
    """KOSPI + KOSDAQ 전체 종목 리스트를 로드하고 캐시합니다."""
    df = pd.concat([
        fdr.StockListing("KOSPI"),
        fdr.StockListing("KOSDAQ"),
    ])
    df["Name"] = df["Name"].astype(str)
    df["Code"] = df["Code"].astype(str)
    return df


def _parse_page(url: str) -> BeautifulSoup:
    """네이버 금융 페이지를 요청하고 BeautifulSoup 객체로 반환합니다."""
    res = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    return BeautifulSoup(res.content.decode("cp949", "ignore"), "html.parser")


def _fetch_metrics(code: str) -> dict | None:
    """종목 코드로 현재가·PER·PBR·배당률을 수집합니다."""
    soup = _parse_page(ITEM_MAIN_URL.format(code=code))

    # 현재가
    price_el = soup.find("p", class_="no_today")
    price = (
        price_el.find("span", class_="blind").text
        if price_el
        else "0"
    )

    # 투자 지표
    aside = soup.find("div", class_="aside_invest_info")
    if aside:
        per = _safe_text(aside, "_per")
        pbr = _safe_text(aside, "_pbr")
        div_rate = _safe_text(aside, "_dvr", default="0%")
    else:
        per, pbr, div_rate = "N/A", "N/A", "0%"

    return {"price": price, "per": per, "pbr": pbr, "div": div_rate}


def _fetch_news(code: str, max_count: int = MAX_NEWS) -> list[dict]:
    """네이버 모바일 API를 사용하여 최신 뉴스를 수집합니다."""
    try:
        url = NAVER_NEWS_API.format(code=code, count=max_count)
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        if res.status_code != 200:
            return []

        data = res.json()
        news_list = []
        for group in data:
            for item in group.get("items", []):
                title = html.unescape(item.get("title", ""))
                office = item.get("officeName", "")
                office_id = item.get("officeId", "")
                article_id = item.get("articleId", "")
                link = f"https://n.news.naver.com/mnews/article/{office_id}/{article_id}"
                news_list.append({
                    "title": title,
                    "link": link,
                    "source": office,
                })
        return news_list[:max_count]
    except Exception:
        return []


def _fetch_investor_data(code: str) -> pd.DataFrame:
    """네이버 금융에서 외국인·기관 순매수 데이터를 수집합니다."""
    try:
        url = f"{NAVER_FINANCE_BASE}/item/frgn.naver?code={code}"
        soup = _parse_page(url)
        tables = soup.find_all("table")
        if len(tables) < 4:
            return pd.DataFrame()

        rows = tables[3].find_all("tr")
        records = []
        for row in rows[2:]:  # 첫 2행은 헤더
            tds = row.find_all("td")
            if len(tds) < 9:
                continue
            try:
                date_str = tds[0].text.strip()
                close = int(tds[1].text.strip().replace(",", ""))
                volume = int(tds[4].text.strip().replace(",", ""))
                inst_net = int(tds[5].text.strip().replace(",", "").replace("+", ""))
                frgn_net = int(tds[6].text.strip().replace(",", "").replace("+", ""))
                records.append({
                    "Date": date_str,
                    "Close": close,
                    "Volume": volume,
                    "기관순매수": inst_net,
                    "외국인순매수": frgn_net,
                })
            except (ValueError, IndexError):
                continue

        df = pd.DataFrame(records)
        if not df.empty:
            df["Date"] = pd.to_datetime(df["Date"], format="%Y.%m.%d")
            df = df.sort_values("Date").reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL)
def _fetch_ohlcv(code: str, days: int = CHART_DAYS) -> pd.DataFrame:
    """FinanceDataReader로 OHLCV 데이터를 가져옵니다."""
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = fdr.DataReader(code, start)
    return df


def get_details(code: str) -> tuple[dict | None, list[dict]]:
    """종목 코드로 지표와 뉴스를 한번에 수집합니다.

    Returns:
        (metrics_dict, news_list)  –  실패 시 (None, [])
    """
    try:
        metrics = _fetch_metrics(code)
        news = _fetch_news(code)
        return metrics, news
    except Exception:
        return None, []


def _safe_text(parent, elem_id: str, default: str = "N/A") -> str:
    """parent 내에서 id 로 요소를 찾아 텍스트를 반환합니다."""
    el = parent.find("em", id=elem_id)
    return el.text if el else default


# ============================================================
# 3. 기술 지표 계산
# ============================================================

def _calc_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    """MACD, Signal, Histogram 을 계산합니다."""
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["Histogram"] = df["MACD"] - df["Signal"]
    return df


def _calc_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    """RSI (Relative Strength Index) 를 계산합니다."""
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


# ============================================================
# 4. 차트 생성 (Plotly)
# ============================================================

CHART_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Pretendard, sans-serif", size=11),
    margin=dict(l=10, r=10, t=35, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
)


# ============================================================
# 4. 통합 차트 생성 (Plotly Subplots)
# ============================================================

def _create_integrated_chart(df: pd.DataFrame, inv_df: pd.DataFrame = None) -> go.Figure:
    """주가(캔들), 이동평균선, 거래량, MACD, RSI, 수급 데이터를 하나의 차트로 생성합니다."""
    # 데이터 준비
    df = df.copy()
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['MA120'] = df['Close'].rolling(window=120).mean()
    df = _calc_macd(df)
    df = _calc_rsi(df)

    # 서브플롯 설정 (행 수 결정)
    rows = 4
    row_heights = [0.4, 0.15, 0.15, 0.15]
    titles = ["주가 및 이동평균선", "거래량", "MACD", "RSI"]
    
    if inv_df is not None and not inv_df.empty:
        rows = 5
        row_heights = [0.35, 0.12, 0.12, 0.12, 0.15]
        titles.append("외국인·기관 순매수")

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=titles,
        row_heights=row_heights
    )

    # 1. 주가 캔들스틱 및 이평선
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="주가", increasing_line_color='#ef4444', decreasing_line_color='#3b82f6'
    ), row=1, col=1)
    
    for ma, color in zip(['MA5', 'MA20', 'MA60', 'MA120'], ['#f59e0b', '#10b981', '#3b82f6', '#8b5cf6']):
        fig.add_trace(go.Scatter(x=df.index, y=df[ma], name=ma, line=dict(width=1, color=color)), row=1, col=1)

    # 2. 거래량
    vol_colors = ['#ef4444' if c >= 0 else '#3b82f6' for c in df['Close'].diff().fillna(0)]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name="거래량", marker_color=vol_colors, opacity=0.7), row=2, col=1)

    # 3. MACD
    macd_colors = ["#ef4444" if v >= 0 else "#3b82f6" for v in df["Histogram"]]
    fig.add_trace(go.Bar(x=df.index, y=df["Histogram"], name="MACD Hist", marker_color=macd_colors, opacity=0.5), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD", line=dict(color="#3b82f6", width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["Signal"], name="Signal", line=dict(color="#f97316", width=1.5)), row=3, col=1)

    # 4. RSI
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="#8b5cf6", width=1.5), fill="tozeroy", fillcolor="rgba(139,92,246,0.05)"), row=4, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", opacity=0.3, row=4, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#22c55e", opacity=0.3, row=4, col=1)

    # 5. 수급 (있을 경우)
    if rows == 5:
        inv_df = inv_df.set_index('Date').reindex(df.index).fillna(0)
        fig.add_trace(go.Bar(x=inv_df.index, y=inv_df["외국인순매수"], name="외국인", marker_color="rgba(59,130,246,0.7)"), row=5, col=1)
        fig.add_trace(go.Bar(x=inv_df.index, y=inv_df["기관순매수"], name="기관", marker_color="rgba(249,115,22,0.7)"), row=5, col=1)

    # 레이아웃 설정
    fig.update_layout(
        template="plotly_white",
        height=850, # PC/모바일 적정 높이로 조절
        showlegend=False,
        margin=dict(l=5, r=5, t=40, b=5),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        font=dict(size=10) # 전체 폰트 크기 축소
    )
    fig.update_xaxes(showgrid=False, tickfont=dict(size=9))
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=9))
    
    return fig


# ============================================================
# 5. 시총 200위 종합 가치 분석
# ============================================================

# cop_analysis tbody 행 인덱스 → 지표 매핑
_COP_ROW = {
    "revenue": 0,      # 매출액
    "op_profit": 1,    # 영업이익
    "op_margin": 3,    # 영업이익률
    "roe": 5,          # ROE(지배주주)
    "debt": 6,         # 부채비율
    "retention": 8,    # 유보율
}


def _parse_cop_row(tbody_rows, row_idx: int, td_idx: int = 2) -> float:
    """cop_analysis tbody 에서 특정 행·열의 숫자를 추출합니다."""
    try:
        tds = tbody_rows[row_idx].find_all("td")
        if len(tds) <= td_idx:
            return 0.0
        txt = tds[td_idx].text.strip().replace(",", "").replace("%", "")
        return float(txt) if txt else 0.0
    except (IndexError, ValueError):
        return 0.0


def _fetch_single_stock_metrics(ticker: str) -> dict | None:
    """단일 종목의 PER·PBR·배당률·ROE·부채비율·유보율을 수집합니다."""
    try:
        url = ITEM_MAIN_URL.format(code=ticker)
        res = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        aside = soup.find("div", class_="aside_invest_info")
        if not aside:
            return None

        per = _safe_float(aside, "_per")
        pbr = _safe_float(aside, "_pbr")
        div_rate = _safe_float(aside, "_dvr")

        # cop_analysis 테이블에서 ROE·부채비율·유보율·영업이익률 추출
        roe = debt = retention = op_margin = 0.0
        cop = soup.find("div", class_="cop_analysis")
        if cop:
            tbl = cop.find("table")
            tbody = tbl.find("tbody") if tbl else None
            if tbody:
                rows = tbody.find_all("tr")
                roe = _parse_cop_row(rows, _COP_ROW["roe"])
                debt = _parse_cop_row(rows, _COP_ROW["debt"])
                retention = _parse_cop_row(rows, _COP_ROW["retention"])
                op_margin = _parse_cop_row(rows, _COP_ROW["op_margin"])

        return {
            "Code": ticker, "PER": per, "PBR": pbr, "Div": div_rate,
            "ROE": roe, "Debt": debt, "Retention": retention,
            "OPMargin": op_margin,
        }
    except Exception:
        return None


def _safe_float(parent, elem_id: str) -> float:
    """parent 내에서 id 로 요소를 찾아 float 로 변환합니다."""
    el = parent.find("em", id=elem_id)
    if el is None:
        return 0.0
    return float(el.text.replace(",", "").replace("%", ""))


@st.cache_data(ttl=CACHE_TTL)
def run_top_analysis() -> pd.DataFrame:
    """시총 상위 200 종목 중 저평가 우량 종목 10개를 선별합니다.

    ── 평가 프로세스 ──
    1차 필터: PER > 0, PBR > 0, ROE > 0 (적자·비정상 제외)
    2차 필터: 부채비율 < 200% (재무 안전성 확보)
    종합 점수: 가중 랭크 합산 (낮을수록 우수)
        - PER  ×1.0  (저PER 선호)
        - PBR  ×1.5  (저PBR 강조 — 자산 대비 저평가 핵심)
        - ROE  ×1.5  (고ROE 강조 — 수익성 검증)
        - 배당률 ×1.0 (고배당 선호 — 하방 경직성)
        - 영업이익률 ×0.5 (고마진 선호)
        - 부채비율 ×0.5 (저부채 선호)
    """
    all_stocks = load_stocks()
    top_n = all_stocks.nlargest(TOP_N, "Marcap")
    marcap_map = dict(zip(top_n["Code"], top_n["Marcap"]))

    # 병렬로 지표 수집
    with ThreadPoolExecutor(max_workers=THREAD_WORKERS) as pool:
        results = [
            r for r in pool.map(_fetch_single_stock_metrics, top_n["Code"].tolist())
            if r is not None
        ]

    df = pd.DataFrame(results)
    code_to_name = dict(zip(top_n["Code"], top_n["Name"]))
    df["Name"] = df["Code"].map(code_to_name)
    df["Marcap"] = df["Code"].map(marcap_map)

    # ── 1차 필터: 기본 유효성 ──
    df = df[(df["PER"] > 0) & (df["PBR"] > 0) & (df["ROE"] > 0)]

    # ── 2차 필터: 재무 안전성 (부채비율 200% 이하) ──
    df = df[df["Debt"].between(0.01, 200)]

    if df.empty:
        return df

    # ── 종합 점수 (가중 랭크) ──
    df["Score"] = (
        df["PER"].rank()                    * 1.0   # 저PER
        + df["PBR"].rank()                  * 1.5   # 저PBR (강조)
        + df["ROE"].rank(ascending=False)   * 1.5   # 고ROE (강조)
        + df["Div"].rank(ascending=False)   * 1.0   # 고배당
        + df["OPMargin"].rank(ascending=False) * 0.5 # 고마진
        + df["Debt"].rank()                 * 0.5   # 저부채
    )

    return df.nsmallest(TOP_RESULT, "Score")


# ============================================================
# 6. HTML 렌더링 헬퍼
# ============================================================

def _render_metric_box(label: str, value: str) -> str:
    """지표 카드 HTML 을 생성합니다."""
    return (
        f'<div class="metric-box">'
        f'  <div class="metric-label">{label}</div>'
        f'  <div class="metric-value">{value}</div>'
        f'</div>'
    )


def _render_news_item(title: str, link: str, source: str) -> str:
    """뉴스 항목 HTML 을 생성합니다."""
    return (
        f'<div class="news-item">'
        f'  <a href="{link}" target="_blank" class="news-link">● {title}</a>'
        f'  <span class="news-meta">{source}</span>'
        f'</div>'
    )


def _render_centered(text: str, padding_top: str = "8px") -> str:
    """가운데 정렬 텍스트 HTML 을 생성합니다."""
    return f'<div style="text-align:center; padding-top:{padding_top};">{text}</div>'


# ============================================================
# 7. 콜백 함수
# ============================================================

def _on_stock_click(name: str) -> None:
    """분석 테이블에서 종목명 클릭 시 검색어를 업데이트합니다."""
    st.session_state.main_search = name


# ============================================================
# 8. 메인 UI
# ============================================================

def main():
    st.title("🚀 Hstock Smart Dashboard")

    # 세션 상태 초기화
    if "top10_data" not in st.session_state:
        st.session_state.top10_data = None

    _render_search_section()
    _render_analysis_section()


# --- 8-1. 기업 정보 검색 섹션 ---

def _render_search_section():
    """종목명/코드 검색 → 기업 정보 + 차트 + 뉴스 표시"""
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="search-title">🏢 기업 정보 및 뉴스 검색</div>',
        unsafe_allow_html=True,
    )

    query = st.text_input(
        "종목명(삼성전자) 또는 코드(005930) 입력",
        key="main_search",
    )

    if query:
        all_stocks = load_stocks()
        matches = all_stocks[
            all_stocks["Name"].str.contains(query, case=False)
            | (all_stocks["Code"] == query)
        ]

        if matches.empty:
            st.warning("일치하는 종목이 없습니다.")
        else:
            target = matches.iloc[0]
            code, name = target["Code"], target["Name"]

            with st.spinner(f"{name} 정보를 가져오는 중..."):
                metrics, news = get_details(code)
                ohlcv = _fetch_ohlcv(code)
                investor = _fetch_investor_data(code)

            if metrics:
                _display_stock_info(code, name, metrics, news, ohlcv, investor)
            else:
                st.error("데이터 로드에 실패했습니다.")

    st.markdown("</div>", unsafe_allow_html=True)


def _display_stock_info(code, name, metrics, news, ohlcv, investor):
    """검색된 종목의 지표·차트·뉴스를 렌더링합니다."""
    # ── 종목 헤더 ──
    st.markdown(
        f"### {name} "
        f"<span style='font-size:16px; color:#8a8a8e;'>{code}</span>",
        unsafe_allow_html=True,
    )

    # ── 지표 카드 4열 ──
    col_price, col_per, col_pbr, col_div = st.columns(4)
    col_price.markdown(_render_metric_box("현재가", f'{metrics["price"]}원'), unsafe_allow_html=True)
    col_per.markdown(_render_metric_box("PER", metrics["per"]), unsafe_allow_html=True)
    col_pbr.markdown(_render_metric_box("PBR", metrics["pbr"]), unsafe_allow_html=True)
    col_div.markdown(_render_metric_box("배당률", metrics["div"]), unsafe_allow_html=True)

    # ── 통합 분석 차트 ──
    if not ohlcv.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            '<div class="search-title">📈 통합 기술 분석 차트</div>',
            unsafe_allow_html=True,
        )
        
        # 통합 차트 렌더링
        fig = _create_integrated_chart(ohlcv, investor)
        st.plotly_chart(fig, use_container_width=True)

    # ── 관련 뉴스 ──
    st.markdown("<br><b>📰 관련 뉴스</b>", unsafe_allow_html=True)
    if news:
        for item in news:
            st.markdown(
                _render_news_item(item["title"], item["link"], item["source"]),
                unsafe_allow_html=True,
            )
    else:
        st.info("관련 뉴스를 가져올 수 없습니다.")


# --- 8-2. 시총 200위 종합 가치 분석 섹션 ---

def _render_analysis_section():
    """시총 200위 종목 분석 버튼 + 결과 테이블"""
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="search-title">💎 실시간 시총 200위 종합 가치 분석</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "분석 기준: 저PER · 저PBR · 고ROE · 고배당 · 고영업이익률 · 저부채비율 "
        "| 부채비율 200% 이하 필터 적용"
    )

    if st.button("실시간 분석 실행"):
        with st.spinner("시총 200개 종목을 정밀 분석 중입니다..."):
            st.session_state.top10_data = run_top_analysis()

    if st.session_state.top10_data is not None:
        _display_top10_table(st.session_state.top10_data)

    st.markdown("</div>", unsafe_allow_html=True)


def _display_top10_table(df: pd.DataFrame):
    """저평가 종목 Top10 테이블을 렌더링합니다."""
    if df.empty:
        st.warning("조건에 맞는 종목이 없습니다.")
        return

    COLUMN_RATIO = [2.5, 1, 1, 1, 1, 1, 1]
    HEADERS = ["종목명", "PER", "PBR", "ROE(%)", "배당(%)", "영업이익률", "부채비율"]

    # 헤더 행
    header_cols = st.columns(COLUMN_RATIO)
    for col, label in zip(header_cols, HEADERS):
        col.markdown(
            _render_centered(
                f"<span style='color:#8a8a8e; font-size:12px; font-weight:600;'>"
                f"{label}</span>",
                padding_top="0",
            ),
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div style="border-bottom:1px solid #f2f2f7; margin:5px 0;"></div>',
        unsafe_allow_html=True,
    )

    # 데이터 행
    for _, row in df.iterrows():
        cols = st.columns(COLUMN_RATIO)

        cols[0].button(
            row["Name"],
            key=f"btn_{row['Code']}",
            use_container_width=True,
            on_click=_on_stock_click,
            args=(row["Name"],),
        )
        cols[1].markdown(_render_centered(f"{row['PER']:.1f}"), unsafe_allow_html=True)
        cols[2].markdown(_render_centered(f"{row['PBR']:.2f}"), unsafe_allow_html=True)
        cols[3].markdown(_render_centered(f"{row['ROE']:.1f}"), unsafe_allow_html=True)
        cols[4].markdown(_render_centered(f"{row['Div']:.1f}"), unsafe_allow_html=True)
        cols[5].markdown(_render_centered(f"{row['OPMargin']:.1f}%"), unsafe_allow_html=True)
        cols[6].markdown(_render_centered(f"{row['Debt']:.0f}%"), unsafe_allow_html=True)


# ============================================================
# 엔트리 포인트
# ============================================================
main()
