import os
import glob
import gdown
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="產業輪動分析系統", layout="wide")

st.markdown("""
    <style>
    .block-container { padding: 1rem 1rem 2rem 1rem; }
    @media (max-width: 768px) {
        .stDataFrame, .plotly-graph-div { width: 100% !important; }
    }
    </style>
""", unsafe_allow_html=True)

st.title("📊 產業輪動與週期博弈系統")

GDRIVE_FOLDER_ID = "1N9JjGDdbjjqQMYQaDZFv73Tag24_uHMW"

def clean_industry_name(name):
    if pd.isna(name):
        return ""
    name = str(name).strip()
    return name[:-1] if name.endswith("業") else name

# 1. 自動從 Google Drive 資料夾同步檔案
@st.cache_data(ttl=300)
def sync_gdrive_folder(folder_id):
    os.makedirs("data", exist_ok=True)
    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
    gdown.download_folder(url=folder_url, output="data", quiet=True, use_cookies=False)
    files = glob.glob("data/*.xlsx")
    return sorted(files, reverse=True)

# 2. 讀取 Excel 資料
@st.cache_data
def load_data(file_path):
    xls = pd.ExcelFile(file_path)
    df_flow = pd.read_excel(xls, sheet_name="類股成交資金流動")
    df_flow['交易日期'] = pd.to_datetime(df_flow['交易日期'])
    df_flow['產業類別_標準'] = df_flow['產業類別'].apply(clean_industry_name)
    df_flow['成交金額比率(%)'] = pd.to_numeric(df_flow['成交金額比率(%)'], errors='coerce').fillna(0)

    df_breadth = pd.read_excel(xls, sheet_name="漲幅前百大產業分佈")
    df_breadth['交易日期'] = pd.to_datetime(df_breadth['交易日期'])
    df_breadth['產業類別_標準'] = df_breadth['產業類別'].apply(clean_industry_name)
    df_breadth['前100名成交市值佔比(%)'] = pd.to_numeric(df_breadth['前100名成交市值佔比(%)'], errors='coerce').fillna(0)
    df_breadth['進榜檔數'] = pd.to_numeric(df_breadth['進榜檔數'], errors='coerce').fillna(0)
    return df_flow, df_breadth

st.sidebar.header("⚙️ 盤面控制")

files = sync_gdrive_folder(GDRIVE_FOLDER_ID)
if not files:
    st.error("雲端資料夾同步失敗或未發現 .xlsx 檔案，請確認資料夾共用設定為「知道連結的任何人」。")
    st.stop()

file_map = {os.path.basename(f): f for f in files}
sel_file_name = st.sidebar.selectbox("📂 選擇資料檔案", list(file_map.keys()), index=0)
sel_file_path = file_map[sel_file_name]

# 載入選定檔案
df_flow, df_breadth = load_data(sel_file_path)

sel_market = st.sidebar.selectbox("市場別", df_flow['市場別'].unique().tolist(), index=0)
m_dates = sorted(df_flow[df_flow['市場別'] == sel_market]['交易日期'].unique())

sel_date = st.sidebar.select_slider(
    "基準交易日",
    options=m_dates,
    value=m_dates[-1],
    format_func=lambda x: x.strftime('%Y-%m-%d')
)
sel_trail = st.sidebar.slider("軌跡天數", min_value=3, max_value=20, value=7)

# 計算 RRG
m_flow = df_flow[df_flow['市場別'] == sel_market]
piv = m_flow.pivot_table(index='交易日期', columns='產業類別_標準', values='成交金額比率(%)', aggfunc='sum').fillna(0)
ma_rs = piv.rolling(window=10, min_periods=1).mean()
rs_ratio = (piv / ma_rs.replace(0, np.nan)).fillna(1.0) * 100

prev_rs = rs_ratio.shift(5)
rs_mom = (rs_ratio / prev_rs.where(prev_rs > 5, np.nan)).fillna(1.0) * 100

rs_ratio_c = rs_ratio.clip(lower=40, upper=160)
rs_mom_c = rs_mom.clip(lower=40, upper=160)

hist = [d for d in m_dates if d <= sel_date][-sel_trail:]
top_inds = m_flow[m_flow['交易日期'] == sel_date].groupby('產業類別_標準')['成交金額比率(%)'].sum().nlargest(8).index.tolist()

# 繪製 RRG
fig = go.Figure()
fig.add_shape(type="rect", x0=100, x1=200, y0=100, y1=200, fillcolor="rgba(0, 200, 0, 0.08)", layer="below", line_width=0)
fig.add_shape(type="rect", x0=100, x1=200, y0=0, y1=100, fillcolor="rgba(255, 215, 0, 0.08)", layer="below", line_width=0)
fig.add_shape(type="rect", x0=0, x1=100, y0=0, y1=100, fillcolor="rgba(200, 0, 0, 0.08)", layer="below", line_width=0)
fig.add_shape(type="rect", x0=0, x1=100, y0=100, y1=200, fillcolor="rgba(0, 100, 255, 0.08)", layer="below", line_width=0)

for ind in top_inds:
    if ind in rs_ratio_c.columns:
        valid_hist = [d for d in hist if d in rs_ratio_c.index]
        if valid_hist:
            x_vals = rs_ratio_c.loc[valid_hist, ind].values
            y_vals = rs_mom_c.loc[valid_hist, ind].values
            fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode='lines+markers', name=ind, line=dict(width=2)))
            fig.add_trace(go.Scatter(x=[x_vals[-1]], y=[y_vals[-1]], mode='markers+text', text=[ind], textposition="top center", marker=dict(size=10), showlegend=False))

fig.add_vline(x=100, line_dash="dash", line_color="gray")
fig.add_hline(y=100, line_dash="dash", line_color="gray")
fig.update_layout(
    title=f"RRG 產業輪動象限圖 ({sel_date.strftime('%Y-%m-%d')})",
    xaxis=dict(title="相對強度 (RS-Ratio)", range=[60, 140]),
    yaxis=dict(title="相對動能 (RS-Momentum)", range=[60, 140]),
    dragmode="pan",
    height=520,
    margin=dict(l=10, r=10, t=40, b=20)
)

st.plotly_chart(fig, use_container_width=True)

# 顯示警報清單
alerts = []
r_ratio = rs_ratio.loc[sel_date]
r_mom = rs_mom.loc[sel_date]
for ind in r_ratio.index:
    rv, mv = r_ratio[ind], r_mom[ind]
    if rv < 100 and mv > 105:
        alerts.append({"產業": ind, "訊號": "🚀 潛力轉強 (低檔資金切入)", "強度 (RS)": round(rv, 2), "動能 (Mom)": round(mv, 2)})
    elif rv > 115 and mv < 95:
        alerts.append({"產業": ind, "訊號": "⚠️ 高檔鈍化 (動能退潮背離)", "強度 (RS)": round(rv, 2), "動能 (Mom)": round(mv, 2)})
    elif rv > 110 and mv > 105:
        alerts.append({"產業": ind, "訊號": "🔥 主流攻堅 (強勢推升段)", "強度 (RS)": round(rv, 2), "動能 (Mom)": round(mv, 2)})

st.subheader("📌 族群動能與轉折警報")
if alerts:
    st.dataframe(pd.DataFrame(alerts).sort_values(by="動能 (Mom)", ascending=False).reset_index(drop=True), use_container_width=True)
else:
    st.info("當日無顯著異常訊號。")

st.subheader(f"💰 {sel_date.strftime('%Y-%m-%d')} 當日成交金額佔比前 5 大產業")
day_flow = m_flow[m_flow['交易日期'] == sel_date].sort_values(by='成交金額比率(%)', ascending=False)
st.dataframe(
    day_flow[['比率排名', '產業類別_標準', '成交金額比率(%)', '成交第1名個股', '成交第2名個股', '成交第3名個股']].head(5).reset_index(drop=True),
    use_container_width=True
)
