import streamlit as st
import pandas as pd
from datetime import date
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- ページ設定 ---
st.set_page_config(page_title="KSC試合管理ツール", layout="wide")

# --- スプレッドシート設定 ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QmQ5uw5HI3tHmYTC29uR8jh1IeSnu4Afn7a4en7yvLc/edit#gid=0"

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Secretsから直接読み込み（以前ログインできていた方法）
        creds_info = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(creds_info), scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

def load_data():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws = sh.get_worksheet(0)
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame(columns=["No", "カテゴリー", "日時", "対戦相手", "試合場所", "試合分類", "備考"])
    df = pd.DataFrame(data)
    if '日時' in df.columns:
        df['日時'] = pd.to_datetime(df['日時']).dt.date
    return df

# --- ログイン処理 ---
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

# --- メイン一覧表示 ---
st.title("⚽ KSC試合管理一覧")
if 'df' not in st.session_state:
    st.session_state.df = load_data()

edited_df = st.data_editor(
    st.session_state.df,
    use_container_width=True,
    hide_index=True,
    key="data_editor"
)

if st.button("スプレッドシートに保存"):
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws = sh.get_worksheet(0)
    # 保存用に日付を文字列に戻す
    df_to_save = edited_df.copy()
    if '日時' in df_to_save.columns:
        df_to_save['日時'] = df_to_save['日時'].astype(str)
    ws.clear()
    ws.update([df_to_save.columns.values.tolist()] + df_to_save.values.tolist())
    st.success("保存しました！")
    st.session_state.df = edited_df
