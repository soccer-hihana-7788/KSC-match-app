import streamlit as st
import pandas as pd
import numpy as np
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
        creds_info = json.loads(st.secrets["gcp_service_account"])
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
        df = pd.DataFrame(columns=["No", "カテゴリー", "日時", "競技分類", "対戦相手", "試合場所", "試合分類", "備考"])
    else:
        df = pd.DataFrame(data)
        
        # --- データずれの自動補正ロジック ---
        # 「対戦相手」列に競技分類が混じっている場合、1列左にずらす
        if "対戦相手" in df.columns:
            bug_mask = df["対戦相手"].isin(["サッカー", "フットサル"])
            if bug_mask.any():
                # ずれている列のリスト
                cols_to_fix = ["対戦相手", "試合場所", "試合分類", "備考"]
                # 1列ずつ左の内容を右の内容で上書き
                for i in range(len(cols_to_fix) - 1):
                    df.loc[bug_mask, cols_to_fix[i]] = df.loc[bug_mask, cols_to_fix[i+1]]
                # 一番右（備考）は空にする
                df.loc[bug_mask, "備考"] = ""
        
        # 競技分類列がそもそも無い場合の対策
        if "競技分類" not in df.columns:
            df.insert(3, "競技分類", "サッカー")
        df["競技分類"] = df["競技分類"].replace("", "サッカー")

    # 型の整理
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    if '日時' in df.columns: 
        df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    # UI用制御列
    df['詳細'] = False
    df['写真(画像)'] = False
    
    # 指示通りの順序（詳細をNoの左に）
    target_order = ['詳細', 'No', 'カテゴリー', '日時', '競技分類', '対戦相手', '試合場所', '試合分類', '備考', '写真(画像)']
    return df[[c for c in target_order if c in df.columns]]

def save_list(df):
    """スプレッドシートへの保存（型エラー対策済み）"""
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        
        df_save = df.copy()
        if '日時' in df_save.columns:
            df_save['日時'] = df_save['日時'].apply(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))
        
        drop_cols = ["詳細", "写真(画像)"]
        df_save = df_save.drop(columns=[c for c in drop_cols if c in df_save.columns])
        
        # JSONシリアライズエラー(int64等)対策：すべての値を標準Python型に変換
        ws.clear()
        data_to_save = [df_save.columns.values.tolist()] + df_save.astype(object).where(pd.notnull(df_save), "").values.tolist()
        ws.update(data_to_save)
    except Exception as e:
        st.error(f"保存エラー: {e}")

# --- 3. 認証処理 (TypeError回避のためCookie不使用) ---
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

# --- 4. セッション管理 ---
if 'df_list' not in st.session_state: 
    st.session_state.df_list = load_data()
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None

def on_data_change():
    changes = st.session_state["editor"]
    for row_idx, edit_values in changes["edited_rows"].items():
        actual_index = st.session_state.current_display_df.index[row_idx]
        actual_no = st.session_state.df_list.at[actual_index, "No"]
        
        if edit_values.get("詳細") is True:
            st.session_state.selected_no = int(actual_no)
            return
        if edit_values.get("写真(画像)") is True:
            st.session_state.media_no = int(actual_no)
            return
            
        for col, val in edit_values.items():
            if col not in ["詳細", "写真(画像)"]:
                st.session_state.df_list.at[actual_index, col] = val
    
    save_list(st.session_state.df_list)

# --- 5. メイン画面制御 ---
if st.session_state.media_no is not None:
    # 写真管理画面（仕様変更なし）
    no = st.session_state.media_no
    st.title(f"🖼️ 写真管理 (No.{no})")
    if st.button("← 一覧に戻る"):
        st.session_state.media_no = None
        st.rerun()
    # ... (既存の写真管理ロジック)

elif st.session_state.selected_no is not None:
    # 試合結果入力画面（仕様変更なし）
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"):
        st.session_state.selected_no = None
        st.rerun()
    # ... (既存の結果入力ロジック)

else:
    # 一覧画面
    st.title("⚽ KSC試合管理一覧")
    c1, c2 = st.columns([2, 1])
    with c1: search_query = st.text_input("🔍 検索")
    with c2: cat_filter = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])
    
    df = st.session_state.df_list.copy()
    if cat_filter != "すべて": df = df[df["カテゴリー"] == cat_filter]
    if search_query: 
        df = df[df.apply(lambda r: search_query.lower() in r.astype(str).str.lower().values, axis=1)]
    
    st.session_state.current_display_df = df
    
    st.data_editor(
        df, 
        hide_index=True, 
        column_config={
            "詳細": st.column_config.CheckboxColumn("結果入力", width="small"),
            "写真(画像)": st.column_config.CheckboxColumn("写真管理", width="small"),
            "No": st.column_config.NumberColumn(disabled=True, width="small"),
            "競技分類": st.column_config.SelectboxColumn("競技分類", options=["サッカー", "フットサル"]),
            "カテゴリー": st.column_config.SelectboxColumn("カテゴリー", options=["U8", "U9", "U10", "U11", "U12"]),
            "日時": st.column_config.DateColumn("日時")
        }, 
        use_container_width=True, 
        key="editor", 
        on_change=on_data_change
    )
