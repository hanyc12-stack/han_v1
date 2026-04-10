import streamlit as st
import pandas as pd
import requests
import io
import re

# 1. 페이지 설정
st.set_page_config(
    page_title="Hstock V1.1 Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. 데이터 엔진 함수
def parse_numeric(v):
    if pd.isna(v) or v == "" or v == "-": return 0.0
    s = str(v).replace(',', '').replace('원', '').replace('%', '').strip()
    s = s.replace(" ", "")
    try:
        return float(s)
    except:
        nums = re.findall(r'-?\d+\.?\d*', s)
        return float(nums[0]) if nums else 0.0

def format_price(v):
    try:
        val = parse_numeric(v)
        if val == 0 and (pd.isna(v) or str(v).strip() in ["-", ""]):
            return "-"
        return f"{int(val):,}"
    except:
        return "-"

# 대시보드 시트 GID (1550923272)
SHEET_ID = "1WqEb6mn8eFH41mCj3BrrH_pSZMRECFR4qCHI1PmjeBg"
GID = "1550923272" 
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&range=A:Z&gid={GID}"

@st.cache_data(ttl=10)
def fetch_data():
    try:
        resp = requests.get(CSV_URL)
        resp.encoding = 'utf-8'
        raw_df = pd.read_csv(io.StringIO(resp.text), header=None)
        return raw_df.reindex(columns=range(max(25, raw_df.shape[1])))
    except:
        return None

df = fetch_data()

if df is not None:
    # 헬퍼 함수
    def get_summary_val(label, col_target=22):
        try:
            row = df[df[21].astype(str).str.contains(label, na=False)]
            if not row.empty:
                val = row.iloc[0, col_target]
                return val if pd.notna(val) else "0"
            return "0"
        except:
            return "0"

    cols = [0, 1, 2, 3, 4, 7, 8, 9, 5, 6, 11]
    exclude_keywords = ["비중", "유형", "항목", "증권사", "Total", "합계", "계", "total", "합", "종목", "Name"]
    
    raw_stocks = df.iloc[1:60, cols].copy()
    raw_stocks.columns = ['Name', 'Weight', 'Qty', 'CurAmt', 'BuyAmt', 'Profit', 'AvgPrice', 'CurPrice', 'Diff', 'TotalDiff', 'Rate']
    
    stocks = raw_stocks[
        raw_stocks['Name'].notna() & 
        (raw_stocks['Name'].str.strip() != "") & 
        (~raw_stocks['Name'].str.contains('|'.join(exclude_keywords), case=False)) &
        (raw_stocks['Weight'].str.strip() != "비중")
    ].drop_duplicates(subset=['Name']).copy()

    sm = {
        "eval":   parse_numeric(get_summary_val("주식 평가금액", 22)),
        "buy":    parse_numeric(get_summary_val("매수금액", 22)),
        "profit": parse_numeric(get_summary_val("누적 수익금", 22)),
        "rate":   str(get_summary_val("누적 수익금", 23)),
        "daily":  parse_numeric(get_summary_val("금일 변동액", 22)),
        "daily_rate": str(get_summary_val("금일 변동액", 23)),
        "cash":   parse_numeric(get_summary_val("현금 보유량", 22)),
    }

    total_asset_q6 = parse_numeric(df.iloc[5, 16]) 
    real_total = total_asset_q6 if total_asset_q6 > 0 else (sm["eval"] + sm["cash"])
    invest_start = str(df.iloc[11, 15])           # P12
    invest_days = str(df.iloc[17, 17])            # R18 (정확한 908일 등 데이터)

    def get_color_class(val):
        nums = parse_numeric(val)
        return 'up' if nums > 0 else 'down' if nums < 0 else 'flat'

    # --- UI & 모바일 최적화 CSS ---
    st.markdown(f"""
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body, [data-testid="stAppViewContainer"] {{
            font-family: 'Noto Sans KR', sans-serif;
            background: #f5f5f3; color: #1a1a18;
        }}
        @media (prefers-color-scheme: dark) {{
            [data-testid="stAppViewContainer"] {{ background: #1a1a18; color: #e8e6df; }}
            .card {{ background: #242422 !important; border-color: rgba(255,255,255,0.1) !important; }}
            .metric-card {{ background: #2c2c2a !important; }}
            .stock-table th {{ color: #888780 !important; border-color: rgba(255,255,255,0.1) !important; }}
            .stock-table td {{ border-color: rgba(255,255,255,0.07) !important; }}
            .card-title, .metric-label {{ color: #888780 !important; }}
            .stock-table th:first-child, .stock-table td:first-child {{ background: #242422 !important; }}
        }}
        .dash {{ max-width: 1300px; margin: 0 auto; padding: 12px 24px; }}
        .header {{ margin-bottom: 24px; }}
        .total {{ font-size: 32px; font-weight: 700; color: #1a1a18; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 28px; }}
        .metric-card {{ background: #fff; border: 1px solid rgba(0,0,0,0.05); border-radius: 16px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.02); }}
        .metric-label {{ font-size: 13px; color: #888780; margin-bottom: 8px; font-weight: 500; }}
        .metric-value {{ font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }}
        .up {{ color: #D85A30 !important; }}
        .down {{ color: #3266AD !important; }}
        .flat {{ color: #888780 !important; }}
        .card {{ background: #fff; border: 1px solid rgba(0,0,0,0.08); border-radius: 20px; padding: 24px; box-shadow: 0 4px 15px rgba(0,0,0,0.04); margin-bottom: 24px; }}
        .card-title {{ font-size: 17px; font-weight: 700; margin-bottom: 20px; }}
        .table-wrapper {{ overflow-x: auto; width: 100%; -webkit-overflow-scrolling: touch; }}
        .stock-table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; min-width: 800px; }}
        .stock-table th {{ color: #888780; font-weight: 600; padding: 10px 6px; text-align: right; border-bottom: 1.5px solid rgba(0,0,0,0.08); position: sticky; top: 0; background: #fff; z-index: 1; font-size: 12px; }}
        .stock-table td {{ padding: 12px 6px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.04); }}

        /* 첫 번째 열 고정 (Sticky Column) */
        .stock-table th:first-child, 
        .stock-table td:first-child {{
            position: sticky;
            left: 0;
            z-index: 2;
            background: #fff;
            text-align: left;
            border-right: 1px solid rgba(0,0,0,0.05);
            min-width: 50px;
            max-width: 70px;
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .stock-table th:first-child {{ z-index: 3; }}

        .badge {{ display: inline-block; font-size: 10.5px; padding: 3px 8px; border-radius: 6px; font-weight: 700; }}
        .badge.up {{ background: #FAECE7; color: #D85A30; }}
        .badge.down {{ background: #E7F0FA; color: #3266AD; }}

        /* 모바일 최적화 */
        @media (max-width: 600px) {{
            .dash {{ padding: 10px 12px; }}
            .total {{ font-size: 24px; }}
            .metric-grid {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
            .metric-card {{ padding: 12px; }}
            .metric-value {{ font-size: 16px; }}
            .card {{ padding: 12px; border-radius: 12px; }}
            .stock-table {{ font-size: 11.5px; }}
            .stock-table th, .stock-table td {{ padding: 8px 4px; }}
            .badge {{ font-size: 10px; padding: 2px 6px; }}
        }}
    </style>
    
    <div class="dash">
      <div class="header">
        <div style="font-size:13px; color:#888780; margin-bottom:4px;">총 자산 (Hstock V1.1)</div>
        <div class="total">{int(real_total):,}원</div>
      </div>

      <div class="metric-grid">
        <div class="metric-card"><div class="metric-label">주식 평가금액</div><div class="metric-value">{int(sm['eval']):,}원</div></div>
        <div class="metric-card"><div class="metric-label">매수금액</div><div class="metric-value">{int(sm['buy']):,}원</div></div>
        <div class="metric-card"><div class="metric-label">누적 수익금</div><div class="metric-value {get_color_class(sm['profit'])}">{int(sm['profit']):+,}원 ({sm['rate']})</div></div>
        <div class="metric-card"><div class="metric-label">금일 변동액</div><div class="metric-value {get_color_class(sm['daily'])}">{int(sm['daily']):+,}원 ({sm['daily_rate']})</div></div>
        <div class="metric-card"><div class="metric-label">현금 보유량</div><div class="metric-value">{int(sm['cash']):,}원</div></div>
      </div>

      <div class="card">
        <div class="card-title">📦 보유 종목 현황</div>
        <div class="table-wrapper">
          <table class="stock-table">
            <thead><tr><th style="text-align:left;">종목명</th><th>비중</th><th>현재가</th><th>평단가</th><th>주당전일비</th><th>금액전일비</th><th>수익금(수익률)</th></tr></thead>
            <tbody>
              {''.join([f"<tr><td>{r['Name']}</td><td>{r['Weight']}</td><td>{format_price(r['CurPrice'])}</td><td>{format_price(r['AvgPrice'])}</td><td class='{get_color_class(r['Diff'])}'>{format_price(r['Diff'])}</td><td class='{get_color_class(r['TotalDiff'])}'>{format_price(r['TotalDiff'])}</td><td><span class='badge {get_color_class(r['Profit'])}'>{format_price(r['Profit'])} ({r['Rate']})</span></td></tr>" for _, r in stocks.iterrows()])}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # --- 시각화 섹션 (Charts) ---
    import streamlit.components.v1 as components
    import json

    s_names, s_weights = stocks['Name'].tolist(), [parse_numeric(w) for w in stocks['Weight']]
    s_profits = [parse_numeric(p) for p in stocks['Profit']]

    chart_html = f"""
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
    <style>
        body {{ font-family: sans-serif; background: transparent; margin: 0; padding: 0; overflow-x: hidden; }}
        .visual-container {{ display: flex; flex-direction: column; gap: 24px; padding: 10px; }}
        .card {{ background: #fff; border-radius: 20px; padding: 24px; border: 1px solid rgba(0,0,0,0.08); box-shadow: 0 4px 15px rgba(0,0,0,0.04); }}
        .card-title {{ font-size: 17px; font-weight: 700; margin-bottom: 20px; }}
        @media (prefers-color-scheme: dark) {{ .card {{ background: #242422; border-color: rgba(255,255,255,0.1); }} .card-title {{ color: #e8e6df; }} }}
        @media (max-width: 600px) {{ .card {{ padding: 15px; border-radius: 16px; }} }}
    </style>
    <div class="visual-container">
        <div class="card"><div class="card-title">📊 종목별 비중</div><div style="height:320px;"><canvas id="weightChart"></canvas></div></div>
        <div class="card"><div class="card-title">💵 종목별 수익금 비교</div><div style="height:400px;"><canvas id="profitChart"></canvas></div></div>
    </div>
    <script>
        Chart.register(ChartDataLabels);
        const palette = ['#E57373', '#64B5F6', '#81C784', '#FFF176', '#FFB74D', '#BA68C8', '#A1887F', '#90A4AE', '#4DB6AC', '#AED581'];
        
        new Chart(document.getElementById('weightChart'), {{
            type: 'doughnut',
            data: {{ labels: {json.dumps(s_names)}, datasets: [{{ data: {json.dumps(s_weights)}, backgroundColor: palette, borderWidth: 0 }}] }},
            options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }} }} }}, 
            datalabels: {{ color: '#fff', font: {{ weight: 'bold', size: 10 }}, formatter: (val) => val > 2 ? val.toFixed(1) + '%' : '' }} }} }}
        }});

        const pData = {json.dumps(s_profits)};
        new Chart(document.getElementById('profitChart'), {{
            type: 'bar',
            data: {{ labels: {json.dumps(s_names)}, datasets: [{{ label: '수익금', data: pData, backgroundColor: pData.map(v => v >= 0 ? '#D85A30' : '#3266AD'), borderRadius: 6 }}] }},
            options: {{ responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                plugins: {{ legend: {{ display: false }}, datalabels: {{ anchor: 'end', align: 'end', color: (ctx) => ctx.dataset.data[ctx.dataIndex] >= 0 ? '#D85A30' : '#3266AD', 
                font: {{ weight: 'bold', size: 11 }}, formatter: (val) => Math.abs(val) >= 1000 ? (val/10000).toFixed(1) + '만' : val }} }}
            }}
        }});
    </script>
    """
    components.html(chart_html, height=850)
else:
    st.error("데이터 로딩 실패")
