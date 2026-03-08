import streamlit as st
import pandas as pd
from datetime import date
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 1. ページ設定 ---
st.set_page_config(page_title="KSC試合管理ツール", layout="wide")

# --- 2. スプレッドシート設定 ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QmQ5uw5HI3tHmYTC29uR8jh1IeSnu4Afn7a4en7yvLc/edit#gid=0"

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Secretsから文字列としてJSONを取得し、辞書に変換
        creds_json = st.secrets["GCP_SERVICE_ACCOUNT"]
        creds_info = json.loads(creds_json)
        
        # 秘密鍵の中にあるエスケープされた改行コードを正しく処理
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

# --- 以降、添付された app.py と同じロジック ---
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

# セッション状態の初期化
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# ログインチェック
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

# メイン処理
if 'df_list' not in st.session_state:
    st.session_state.df_list = load_data()

st.title("⚽ KSC試合管理一覧")
st.write("以前動いていた設定に戻しました。")
st.data_editor(st.session_state.df_list, use_container_width=True, hide_index=True)
