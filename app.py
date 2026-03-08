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
        # Streamlit Secretsをそのまま利用（加工しない）
        creds_info = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

def load_data():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws_list = sh.get_worksheet(0)
    data = ws_list.get_all_records()
    
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
    return df

def save_list(df):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        df_save = df.copy()
        if '日時' in df_save.columns:
            df_save['日時'] = df_save['日時'].apply(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))
        df_save = df_save.drop(columns=["詳細", "写真(画像)"], errors='ignore')
        ws.clear()
        ws.update([df_save.columns.values.tolist()] + df_save.values.tolist())
    except Exception as e:
        st.error(f"保存エラー: {e}")

# --- 3. 認証処理 ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID")
    p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("IDまたはパスワードが違います")
    st.stop()

# --- 4. メイン ---
if 'df_list' not in st.session_state: 
    st.session_state.df_list = load_data()

st.title("⚽ KSC試合管理一覧")

# データエディタを表示
edited_df = st.data_editor(
    st.session_state.df_list,
    hide_index=True,
    column_config={
        "詳細": st.column_config.CheckboxColumn("結果"),
        "写真(画像)": st.column_config.CheckboxColumn("写真"),
        "No": st.column_config.NumberColumn(disabled=True)
    },
    use_container_width=True
)

if st.button("変更をスプレッドシートに保存"):
    save_list(edited_df)
    st.session_state.df_list = edited_df
    st.success("保存しました")
