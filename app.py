import streamlit as st
import pandas as pd
from datetime import date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import base64
from io import BytesIO
from PIL import Image, ImageOps

# --- 1. ページ設定 ---
st.set_page_config(page_title="KSC試合管理ツール", layout="wide")

# --- 2. スプレッドシート設定 ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QmQ5uw5HI3tHmYTC29uR8jh1IeSnu4Afn7a4en7yvLc/edit#gid=0"

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Secretsから辞書として取得（json.loadsは不要）
        creds_info = dict(st.secrets["gcp_service_account"])
        # 鍵の中の改行記号を処理
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

def load_data():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws_list = sh.get_worksheet(0)
    
    try:
        data = ws_list.get_all_records()
    except Exception:
        data = []
    
    if not data:
        df = pd.DataFrame({
            "No": range(1, 101), "カテゴリー": ["U12"] * 100,
            "日時": [date.today().isoformat()] * 100, "対戦相手": [""] * 100,
            "試合場所": [""] * 100, "試合分類": [""] * 100, "備考": [""] * 100
        })
    else:
        df = pd.DataFrame(data)
    
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No'])
    if '日時' in df.columns: 
        df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    df['詳細'] = False
    df['写真(画像)'] = False
    
    target_order = ['詳細', 'No', 'カテゴリー', '日時', '対戦相手', '試合場所', '試合分類', '備考', '写真(画像)']
    return df[[c for c in target_order if c in df.columns]]

# --- 3. 認証処理 ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u, p = st.text_input("ID"), st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.rerun()
        else: st.error("IDまたはパスワードが違います")
    st.stop()

# --- 4. メイン画面 ---
if 'df_list' not in st.session_state: 
    st.session_state.df_list = load_data()

st.title("⚽ KSC試合管理一覧")

# 以前のコードの「検索」「絞り込み」機能
c1, c2 = st.columns([2, 1])
with c1: search_query = st.text_input("🔍 検索")
with c2: cat_filter = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])

df = st.session_state.df_list.copy()
if cat_filter != "すべて": df = df[df["カテゴリー"] == cat_filter]
if search_query: 
    df = df[df.apply(lambda r: search_query.lower() in r.astype(str).str.lower().values, axis=1)]

st.data_editor(
    df, 
    hide_index=True, 
    column_config={
        "詳細": st.column_config.CheckboxColumn("結果入力", width="small"),
        "写真(画像)": st.column_config.CheckboxColumn("写真管理", width="small"),
        "No": st.column_config.NumberColumn(disabled=True, width="small"),
    }, 
    use_container_width=True
)
