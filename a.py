import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# ==========================================
# 1. Page Configuration & Custom CSS (Premium)
# ==========================================
st.set_page_config(
    page_title="OPPD Bank 자산 대시보드",
    page_icon="⭐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Light Look
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #F8F9FA;
    }
    /* Metric Card Styling */
    [data-testid="stMetricValue"] {
        font-size: 2.5rem !important;
        font-weight: 800 !important;
        color: #2C3E50; /* Deep blue-gray for text */
    }
    [data-testid="stMetricLabel"] {
        font-size: 1.1rem !important;
        color: #7F8C8D;
        font-weight: 600;
    }
    /* Custom Card Style for charts */
    .chart-card {
        background-color: #FFFFFF;
        border: 1px solid #E0E0E0;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #E0E0E0;
    }
    /* Headers */
    h1, h2, h3 {
        color: #2C3E50;
        font-weight: 700;
        border-bottom: 2px solid #E0E0E0;
        padding-bottom: 8px;
    }
    /* Dataframe Styling */
    .stDataFrame {
        border-radius: 10px;
    }
    /* st.table Styling for text alignment */
    [data-testid="stTable"] th {
        text-align: center !important;
    }
    [data-testid="stTable"] td {
        text-align: right !important;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 2. Data Loading & Cleaning
# ==========================================
SHEET_ID = "1ZA1IxkQQtNHi7Lv1lAX2tcj6zeQKBI8Toh04gzWoYmg"
GID_STOCK_HISTORY = "666381890"  # 📊주식내역 (History)
GID_STOCK_STATUS = "1737697913"  # 📈주식현황상세 (Current Status/Valuation)
GID_DIV = "1236517325"          # 배당

import re

def clean_money(x):
    """Clean '₩ 1,234,567' or '16,610원' strings into floats using regex."""
    if pd.isna(x): return 0.0
    s = str(x).strip()
    if s in ['-', '--', 'None', 'nan', '']: return 0.0
    # Extract only numbers and decimal points
    nums = re.findall(r'[-+]?\d*\.?\d+', s.replace(',', ''))
    if nums:
        try: return float(nums[0])
        except: return 0.0
    return 0.0

@st.cache_data(ttl=600)
def load_data():
    try:
        # 1. Load Current Stock Status (for valuation)
        url_status = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID_STOCK_STATUS}"
        df_status = pd.read_csv(url_status, header=1)
        df_status.columns = [str(c).strip() for c in df_status.columns]
        
        # Robust Column Mapping
        def find_col_in(possible_names, columns):
            for c in columns:
                if any(name == c or name in c for name in possible_names):
                    return c
            return None

        # Using exact column indices to match User request (I=8, P=15, T=19, Y=24, Z=25)
        # Note: pandas uses 0-based indexing. A=0... I=8, P=15...
        try:
            col_buy = df_status.columns[8] # I열
            col_val = df_status.columns[15] # P열 
            col_profit = df_status.columns[19] # T열
            col_day_change_1_share = df_status.columns[24] # Y열
            col_day_change_total = df_status.columns[25] # Z열
        except IndexError:
            # Fallback if columns are shorter
            col_buy = find_col_in(['매수금액'], df_status.columns)
            col_val = find_col_in(['평가총액(원)'], df_status.columns)
            col_profit = None
            col_day_change_1_share = None
            col_day_change_total = find_col_in(['전일대비총액'], df_status.columns)

        col_price = find_col_in(['현재가'], df_status.columns)
        col_name = find_col_in(['종목명'], df_status.columns)
        col_qty = find_col_in(['보유량', '수량'], df_status.columns)
        col_sector = find_col_in(['섹터'], df_status.columns)

        if not col_val or not col_name:
            # Fallback attempts
            if not col_val:
                for c in df_status.columns:
                    if '평가' in c and '(원)' in c: col_val = c; break
            if not col_name:
                for c in df_status.columns:
                    if '종목' in c: col_name = c; break

        if not col_val:
            raise KeyError("시트에서 '평가총액(원)'(P열) 컬럼을 찾을 수 없습니다.")

        df_status['평가총액_원'] = df_status[col_val].apply(clean_money)
        if col_price: 
            # In the sheet, L is '현재가', but actually column index 11 is the data
            df_status['현재가'] = df_status.iloc[:, 11].apply(clean_money) if len(df_status.columns) > 11 else 0.0
        else:
            df_status['현재가'] = 0.0
            
        # Add 1-day change metrics
        if col_day_change_1_share:
            df_status['전일대비_1주'] = df_status[col_day_change_1_share].apply(clean_money)
        else:
            df_status['전일대비_1주'] = 0.0
            
        if col_day_change_total:
            df_status['전일대비_총액'] = df_status[col_day_change_total].apply(clean_money)
        else:
            df_status['전일대비_총액'] = 0.0
            
        if col_profit:
            df_status['수익현황'] = df_status[col_profit].apply(clean_money)
        else:
            df_status['수익현황'] = 0.0

        if col_buy:
            df_status['매수총액'] = df_status[col_buy].apply(clean_money)
        else:
            df_status['매수총액'] = 0.0
            
        # Rename/Alias for consistency in UI
        if col_name: df_status['종목명'] = df_status[col_name]
        if col_qty: df_status['보유량'] = df_status[col_qty].apply(clean_money)
        if col_sector: df_status['섹터'] = df_status[col_sector]

        # Calculate current price manually if column exists but failed to parse (valuation / qty)
        mask = (df_status['현재가'] == 0) & (df_status['보유량'] > 0) & (df_status['평가총액_원'] > 0)
        df_status.loc[mask, '현재가'] = df_status['평가총액_원'] / df_status['보유량']

        # Filter out empty stocks or zero valuation
        df_status = df_status[df_status['평가총액_원'] > 0].copy()
        
        # 2. Load Dividend Data
        url_div = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID_DIV}"
        df_div = pd.read_csv(url_div)
        df_div.columns = [str(c).strip() for c in df_div.columns]
        
        col_div_date = find_col_in(['입금일'], df_div.columns)
        col_div_amt = find_col_in(['입금액_KRW', '실수령액'], df_div.columns)
        
        if col_div_date:
            df_div['입금일'] = pd.to_datetime(df_div[col_div_date], errors='coerce')
        if col_div_amt:
            df_div['입금액_KRW'] = df_div[col_div_amt].apply(clean_money)
            
        df_div = df_div.dropna(subset=['입금일'])
        
        return df_status, df_div
    except Exception as e:
        st.error(f"데이터 로딩 중 상세 오류 발생: {e}")
        return pd.DataFrame(), pd.DataFrame()

    except Exception as e:
        st.error(f"데이터 로딩 중 상세 오류 발생: {e}")
        return pd.DataFrame(), pd.DataFrame()

def find_col_in(possible_names, columns):
    for c in columns:
        if any(name in c for name in possible_names):
            return c
    return None


df_stock, df_div = load_data()

# ==========================================
# 3. Sidebar & Static Inputs
# ==========================================
st.sidebar.title("⭐ 대시보드 설정")

# Hardcoded fixed values (Removed manual input from sidebar)
manual_cash = 119144673
manual_savings = 20393645
manual_insurance = 91594400
page = st.sidebar.radio("페이지 이동", ["🏠 자산 개요", "📊 주식 포트폴리오", "💰 배당 히스토리"])

st.sidebar.markdown("---")
st.sidebar.info("마지막 업데이트 (실시간 시세 기반): " + datetime.now().strftime("%Y-%m-%d %H:%M"))


# ==========================================
# 4. Tab Implementation Functions
# ==========================================

def render_overview():
    st.title("🏠 종합 자산 개요")
    
    stock_sum = df_stock['평가총액_원'].sum()
    total_assets = stock_sum + manual_cash + manual_savings + manual_insurance
    
    # --- Top Banner for Total Assets (Light Mode) ---
    st.markdown(f"""
    <div style="background-color: #FFFFFF; padding: 25px; border-radius: 15px; border: 1px solid #E0E0E0; box-shadow: 0 4px 12px rgba(0,0,0,0.05); margin-bottom: 25px; text-align: center;">
        <p style="margin: 0; font-size: 1.1rem; color: #7F8C8D;">총 합산 순자산 (실시간 시세)</p>
        <h1 style="margin: 0; font-size: 3.5rem; color: #2C3E50; border: none;">₩{total_assets:,.0f}</h1>
    </div>
    """, unsafe_allow_html=True)

    # --- Summary Metrics Row ---
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("📈 주식 평가금", f"₩{stock_sum:,.0f}")
    with c2: st.metric("💵 현금 잔액", f"₩{manual_cash:,.0f}")
    with c3: st.metric("🏦 예적금", f"₩{manual_savings:,.0f}")
    with c4: st.metric("🛡️ 보호 금융 (보험)", f"₩{manual_insurance:,.0f}")
    
    st.write("---")
    
    # --- Charts Row ---
    col1, col2 = st.columns([1.8, 1])
    
    # Data preparation
    data = pd.DataFrame({
        '구분': ['주식', '현금', '예적금', '보험'],
        '금액': [stock_sum, manual_cash, manual_savings, manual_insurance]
    })
    data['비중'] = (data['금액'] / total_assets * 100).round(1).astype(str) + "%"
    
    with col1:
        st.subheader("🥧 자산 배분 비중 (실시간 시세)")
        
        # Base chart for layering
        base = alt.Chart(data).encode(
            theta=alt.Theta(field="금액", type="quantitative", stack=True),
            color=alt.Color(field="구분", type="nominal", 
                           scale=alt.Scale(range=['#27AE60', '#8E44AD', '#2980B9', '#C0392B']),
                           legend=alt.Legend(orient='bottom', title=None)),
            tooltip=['구분', '금액', '비중']
        )
        
        # Donut slices
        pie = base.mark_arc(innerRadius=90, outerRadius=150, stroke='#FFFFFF')
        
        # Percentage labels (Dark text for Light Mode)
        text = base.mark_text(radius=180, size=15, fontWeight='bold', color='#2C3E50').encode(
            text=alt.Text('비중:N')
        )
        
        # Layering
        donut_with_labels = (pie + text).properties(height=450).configure_view(strokeWidth=0)
        
        st.altair_chart(donut_with_labels, use_container_width=True)

    with col2:
        st.subheader("📐 자산 상세 비중")
        # Custom display table
        table_data = data.copy()
        table_data['금액 (₩)'] = table_data['금액'].apply(lambda x: f"{x:,.0f}")
        display_df = table_data[['구분', '비중', '금액 (₩)']].sort_values(by='비중', ascending=False)
        display_df.set_index('구분', inplace=True)
        
        styled_df = display_df.style.set_properties(**{'text-align': 'right', 'font-weight': 'bold'})
        styled_df = styled_df.set_table_styles([dict(selector='th', props=[('text-align', 'center')])])
        
        st.table(styled_df)



def render_stocks():
    st.title("📊 주식 포트폴리오 분석 (실시간)")
    
    if df_stock.empty:
        st.warning("주식 데이터를 찾을 수 없습니다.")
        return

    # Metrics
    total_val = df_stock['평가총액_원'].sum()
    total_buy = df_stock['매수총액'].sum() if '매수총액' in df_stock.columns else 0.0
    total_profit = df_stock['수익현황'].sum() if '수익현황' in df_stock.columns else 0.0
    total_day_change = df_stock['전일대비_총액'].sum() if '전일대비_총액' in df_stock.columns else 0.0
    
    # Calculate %
    profit_pct = (total_profit / total_buy * 100) if total_buy > 0 else 0.0
    total_val_yesterday = total_val - total_day_change
    day_change_pct = (total_day_change / total_val_yesterday * 100) if total_val_yesterday > 0 else 0.0
    
    def get_color(val):
        if val > 0: return "#D32F2F"
        if val < 0: return "#1976D2"
        return "#2C3E50"

    p_color = get_color(total_profit)
    d_color = get_color(total_day_change)

    st.markdown(f"""
    <div style="display: flex; gap: 15px; margin-bottom: 25px;">
        <div style="flex: 1; padding: 15px 20px; border-radius: 12px; border: 1px solid #E0E0E0; background-color: #FFFFFF; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
            <div style="color: #7F8C8D; font-size: 1.1rem; font-weight: 600;">주식 평가 합계 (P열)</div>
            <div style="font-size: 2.2rem; font-weight: 800; color: #2C3E50; margin-top: 5px;">₩{total_val:,.0f}</div>
        </div>
        <div style="flex: 1; padding: 15px 20px; border-radius: 12px; border: 1px solid #E0E0E0; background-color: #FFFFFF; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
            <div style="color: #7F8C8D; font-size: 1.1rem; font-weight: 600;">매수총액 (I열)</div>
            <div style="font-size: 2.2rem; font-weight: 800; color: #2C3E50; margin-top: 5px;">₩{total_buy:,.0f}</div>
        </div>
        <div style="flex: 1; padding: 15px 20px; border-radius: 12px; border: 1px solid #E0E0E0; background-color: #FFFFFF; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
            <div style="color: #7F8C8D; font-size: 1.1rem; font-weight: 600;">수익현황 합계 (T열)</div>
            <div style="font-size: 2.2rem; font-weight: 800; color: {p_color}; margin-top: 5px;">₩{total_profit:,.0f} <span style="font-size: 1.2rem;">({profit_pct:+.2f}%)</span></div>
        </div>
        <div style="flex: 1; padding: 15px 20px; border-radius: 12px; border: 1px solid #E0E0E0; background-color: #FFFFFF; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
            <div style="color: #7F8C8D; font-size: 1.1rem; font-weight: 600;">전일대비 (Z열)</div>
            <div style="font-size: 2.2rem; font-weight: 800; color: {d_color}; margin-top: 5px;">₩{total_day_change:,.0f} <span style="font-size: 1.2rem;">({day_change_pct:+.2f}%)</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Stock Chart
    st.subheader("🏷️ 종목명별 포트폴리오 (평가 금액 기준)")
    chart_data = df_stock.groupby('종목명')['평가총액_원'].sum().reset_index()
    total_val = chart_data['평가총액_원'].sum()
    chart_data['비중'] = chart_data['평가총액_원'] / total_val if total_val > 0 else 0
    
    chart_data['레이블'] = chart_data.apply(lambda x: f"{x['종목명']} ({x['비중']:.1%})", axis=1)
    
    base = alt.Chart(chart_data).encode(
        theta=alt.Theta(field="평가총액_원", type="quantitative", stack=True),
        color=alt.Color(field="종목명", type="nominal",
                       sort=alt.EncodingSortField(field="평가총액_원", op="sum", order="descending"),
                       scale=alt.Scale(scheme='tableau20'),
                       legend=alt.Legend(orient='right', title='종목명')),
        tooltip=[alt.Tooltip('종목명'), alt.Tooltip('평가총액_원', format=',.0f'), alt.Tooltip('비중:Q', format='.2%', title='비중')]
    )
    
    donut = base.mark_arc(innerRadius=100, outerRadius=160, stroke='#FFFFFF', strokeWidth=1.5)
    
    text = base.mark_text(radius=195, size=12, fontWeight='bold', color='#2C3E50').encode(
        text=alt.condition(alt.datum.비중 >= 0.02, alt.Text('레이블:N'), alt.value(''))
    )
    
    stock_chart = (donut + text).properties(height=450).configure_view(strokeWidth=0)
    st.altair_chart(stock_chart, use_container_width=True)

    # Table
    st.subheader("📋 보유 종목 상세 (실시간)")
    cols = ['종목명', '보유량', '현재가', '전일대비_1주', '전일대비_총액', '수익현황', '평가총액_원']
    
    # Ensure columns exist before filtering to prevent KeyError
    existing_cols = [c for c in cols + ['매수총액'] if c in df_stock.columns]
    
    display_df = df_stock[existing_cols].sort_values(by='평가총액_원', ascending=False).copy()
    display_df.set_index('종목명', inplace=True)
    
    if '전일대비_1주' in display_df.columns and '현재가' in display_df.columns:
        def format_1day(row):
            val = row['전일대비_1주']
            curr = row['현재가']
            yday = curr - val
            pct = (val / yday * 100) if yday > 0 else 0.0
            return f"{val:,.0f} ({pct:+.2f}%)"
        display_df['전일대비_1주'] = display_df.apply(format_1day, axis=1)

    if '수익현황' in display_df.columns and '매수총액' in display_df.columns and '평가총액_원' in display_df.columns:
        def format_profit(row):
            val = row['수익현황']
            buy = row['매수총액']
            val_eval = row['평가총액_원']
            pct = ((val_eval / buy) - 1) * 100 if buy > 0 else 0.0
            return f"{val:,.0f} ({pct:+.2f}%)"
        display_df['수익현황'] = display_df.apply(format_profit, axis=1)
        
    if '매수총액' in display_df.columns and '매수총액' not in cols:
        display_df.drop(columns=['매수총액'], inplace=True)

    # Dynamic style formatting based on existing columns
    format_dict = {'평가총액_원': '{:,.0f}', '현재가': '{:,.0f}', '보유량': '{:,.2f}'}
    if '전일대비_총액' in display_df.columns: format_dict['전일대비_총액'] = '{:,.0f}'
        
    def color_change(val):
        if pd.isna(val): return ''
        base_style = 'text-align: right !important;'
        if isinstance(val, (int, float)):
            if val > 0: return base_style + ' color: #D32F2F;' # Red for positive
            if val < 0: return base_style + ' color: #1976D2;' # Blue for negative
        elif isinstance(val, str):
            if '(+' in val: return base_style + ' color: #D32F2F;'
            if '(-' in val: return base_style + ' color: #1976D2;'
        return base_style

    subset_colors = [c for c in ['전일대비_1주', '전일대비_총액', '수익현황'] if c in display_df.columns]
    styled_df = display_df.style.format(format_dict)
    
    if subset_colors:
        try:
            styled_df = styled_df.map(color_change, subset=subset_colors)
        except AttributeError:
            styled_df = styled_df.applymap(color_change, subset=subset_colors)

    styled_df = styled_df.set_properties(**{'text-align': 'right', 'font-weight': 'bold'})
    styled_df = styled_df.set_table_styles([dict(selector='th', props=[('text-align', 'center')])])
            
    st.table(styled_df)


def render_dividends():
    st.title("💰 배당 수령 히스토리")
    
    if df_div.empty:
        st.warning("배당 데이터를 찾을 수 없습니다.")
        return

    # Cleaning: Aggregating by year and stock
    df_div['Year'] = df_div['입금일'].dt.strftime('%Y')
    
    yearly_total = df_div.groupby('Year')['입금액_KRW'].sum().reset_index()
    
    if '종목명' in df_div.columns:
        yearly_trend = df_div.groupby(['Year', '종목명'])['입금액_KRW'].sum().reset_index()
        color_eval = alt.Color('종목명:N', scale=alt.Scale(scheme='tableau20'), legend=alt.Legend(orient='bottom', title=None))
        t_tip = [alt.Tooltip('Year', title='연도'), alt.Tooltip('종목명', title='종목'), alt.Tooltip('입금액_KRW', title='실수령액', format=',.0f')]
    else:
        yearly_trend = yearly_total.copy()
        color_eval = alt.value('#27AE60')
        t_tip = [alt.Tooltip('Year', title='연도'), alt.Tooltip('입금액_KRW', title='배당 총액', format=',.0f')]

    st.subheader("📈 연도별 배당 추이 (종목/합계)")
    
    base = alt.Chart(yearly_trend).encode(
        x=alt.X('Year:O', title='연도'),
        y=alt.Y('입금액_KRW:Q', title='연간 총 실수령액 (₩)', stack='zero')
    )
    
    if '종목명' in df_div.columns:
        bars = base.mark_bar(size=45).encode(
            color=color_eval,
            order=alt.Order('종목명:N', sort='ascending'),
            tooltip=t_tip
        )
        
        segment_text = base.mark_text(
            baseline='top', 
            dy=6, 
            color='#000000',
            fontSize=12,
            fontWeight='bold'
        ).encode(
            order=alt.Order('종목명:N', sort='ascending'),
            detail='종목명:N',
            text=alt.condition(alt.datum.입금액_KRW > 0, alt.Text('입금액_KRW:Q', format=',.0f'), alt.value(''))
        )
    else:
        bars = base.mark_bar(size=45, color='#27AE60').encode(tooltip=t_tip)
        segment_text = base.mark_text(
            baseline='top', 
            dy=6, 
            color='#000000',
            fontSize=12,
            fontWeight='bold'
        ).encode(
            text=alt.condition(alt.datum.입금액_KRW > 0, alt.Text('입금액_KRW:Q', format=',.0f'), alt.value(''))
        )
    
    
    text = alt.Chart(yearly_total).mark_text(
        align='center',
        baseline='bottom',
        dy=-5,
        color='#2C3E50',
        fontWeight='bold',
        fontSize=13
    ).encode(
        x=alt.X('Year:O'),
        y=alt.Y('입금액_KRW:Q'),
        text=alt.Text('입금액_KRW:Q', format=',.0f')
    )
    
    trend_chart = (bars + segment_text + text).properties(height=500)
    st.altair_chart(trend_chart, use_container_width=True)

    st.subheader("📋 종목별 연간 배당 합계")
    if '종목명' in df_div.columns:
        pivot_df = df_div.pivot_table(index='종목명', columns='Year', values='입금액_KRW', aggfunc='sum', fill_value=0)
        # Add grand total column
        pivot_df['총 누적액'] = pivot_df.sum(axis=1)
        pivot_df = pivot_df.sort_values(by='총 누적액', ascending=False)
        
        # Add a grand total row at the bottom
        total_row = pivot_df.sum(axis=0)
        total_row.name = '💡 연간 총합계'
        pivot_df = pd.concat([pivot_df, pd.DataFrame([total_row])])
        
        # Determine formatting dynamically for all money columns
        format_dict = {col: '{:,.0f}' for col in pivot_df.columns}
        
        styled_df = pivot_df.style.format(format_dict).set_properties(
            **{'text-align': 'right', 'font-weight': 'bold'}
        )
        styled_df = styled_df.set_table_styles([dict(selector='th', props=[('text-align', 'center')])])
        
        st.table(styled_df)
    else:
        # Fallback table if '종목명' isn't available
        yearly_table = yearly_trend.copy().sort_values(by='Year', ascending=False)
        yearly_table.set_index('연도', inplace=True)
        
        styled_df = yearly_table.style.format({'배당 합산액(₩)': '{:,.0f}'}).set_properties(
            **{'text-align': 'right', 'font-weight': 'bold'}
        ).set_table_styles([dict(selector='th', props=[('text-align', 'center')])])
        
        st.table(styled_df)

# ==========================================
# 5. 메인 실행 로직
# ==========================================
if page == "🏠 자산 개요":
    render_overview()
elif page == "📊 주식 포트폴리오":
    render_stocks()
elif page == "💰 배당 히스토리":
    render_dividends()
