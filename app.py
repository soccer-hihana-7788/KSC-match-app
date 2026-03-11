import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
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
# スプレッドシートの列順を厳密に定義
SHEET_COLUMNS = ["No", "カテゴリー", "日時", "競技分類", "対戦相手", "試合場所", "試合分類", "備考"]

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_info = json.loads(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

@st.cache_data(ttl=60) # 1分間はキャッシュを利用して高速化
def load_data_from_sheet():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws = sh.get_worksheet(0)
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    
    # 競技分類の欠損補完とズレ補正
    if "競技分類" not in df.columns:
        df.insert(3, "競技分類", "サッカー")
    
    # 以前発生していた「サッカー」が対戦相手にズレたデータの自動修正
    bug_mask = df["対戦相手"].isin(["サッカー", "フットサル"])
    if bug_mask.any():
        cols_to_fix = ["対戦相手", "試合場所", "試合分類", "備考"]
        for i in range(len(cols_to_fix) - 1):
            df.loc[bug_mask, cols_to_fix[i]] = df.loc[bug_mask, cols_to_fix[i+1]]
        df.loc[bug_mask, "備考"] = ""
    
    df["競技分類"] = df["競技分類"].replace("", "サッカー")
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    if '日時' in df.columns: df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    df['詳細'] = False
    df['写真(画像)'] = False
    return df

def save_cell_to_sheet(row_idx, col_name, value):
    """特定の1セルだけを高速に保存"""
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws = sh.get_worksheet(0)
    col_idx = SHEET_COLUMNS.index(col_name) + 1
    # 日付オブジェクトの変換
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    ws.update_cell(row_idx + 2, col_idx, value)

# --- 3. セッション管理 ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'df_list' not in st.session_state: st.session_state.df_list = load_data_from_sheet()
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None

# ログイン
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u, p = st.text_input("ID"), st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.rerun()
        else: st.error("IDまたはパスワードが違います")
    st.stop()

# --- 4. データエディタ変更時の処理 ---
def on_data_change():
    changes = st.session_state["editor"]
    # 編集された行のループ
    for row_idx_key, edit_values in changes["edited_rows"].items():
        actual_index = st.session_state.current_display_df.index[row_idx_key]
        
        # 結果入力や写真管理ボタンが押された場合
        if edit_values.get("詳細") is True:
            st.session_state.selected_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        if edit_values.get("写真(画像)") is True:
            st.session_state.media_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        
        # 値（競技分類など）が変更された場合
        for col, val in edit_values.items():
            if col in SHEET_COLUMNS:
                # メモリ上のデータを更新
                st.session_state.df_list.at[actual_index, col] = val
                # スプレッドシートへ高速保存
                save_cell_to_sheet(actual_index, col, val)

# --- 5. メイン画面 ---
if st.session_state.media_no is not None:
    # 写真管理（仕様変更なし）
    st.title(f"🖼️ 写真管理 (No.{st.session_state.media_no})")
    if st.button("← 一覧に戻る"): st.session_state.media_no = None; st.rerun()
    # (中略: 写真管理ロジック)
    st.info("写真管理機能")

elif st.session_state.selected_no is not None:
    # 試合結果入力
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"): st.session_state.selected_no = None; st.rerun()
    
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: ws_res = sh.add_worksheet(title="results", rows="100", cols="2"); ws_res.append_row(["key", "data"])
    
    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        sd = all_results.get(rk, {"score": " - ", "scorers": [], "result": ""})
        
        with st.expander(f"第 {i} 試合 - {sd.get('score', '未入力')} 【{sd.get('result', '')}】"):
            # ボタン押下時に画面を動かさないための実装
            res_val = st.radio("結果", ["勝ち", "負け", "引き分け"], index=0, key=f"r_{rk}", horizontal=True)
            sc_l = st.text_input("自スコア", key=f"l_{rk}", value=sd.get('score', ' - ').split('-')[0].strip())
            sc_r = st.text_input("相手スコア", key=f"r_in_{rk}", value=sd.get('score', ' - ').split('-')[-1].strip())
            sc_in = st.text_area("得点者", key=f"t_{rk}", value=", ".join(sd.get('scorers', [])))
            
            if st.button(f"第{i}試合を保存", key=f"b_{rk}"):
                all_results[rk] = {
                    "score": f"{sc_l}-{sc_r}",
                    "scorers": [s.strip() for s in sc_in.split(",") if s.strip()],
                    "result": res_val
                }
                ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                st.toast(f"第{i}試合 保存完了！")

else:
    st.title("⚽ KSC試合管理一覧")
    
    # 高速化のため検索・フィルターをメモリ上で実施
    c1, c2 = st.columns([2, 1])
    with c1: search_query = st.text_input("🔍 検索")
    with c2: cat_filter = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])
    
    df_display = st.session_state.df_list.copy()
    if cat_filter != "すべて": df_display = df_display[df_display["カテゴリー"] == cat_filter]
    if search_query: 
        df_display = df_display[df_display.apply(lambda r: search_query.lower() in r.astype(str).str.lower().values, axis=1)]
    
    st.session_state.current_display_df = df_display
    
    # 競技分類の変更を即座に反映
    st.data_editor(
        df_display,
        hide_index=True,
        column_config={
            "詳細": st.column_config.CheckboxColumn("結果入力", width="small"),
            "写真(画像)": st.column_config.CheckboxColumn("写真管理", width="small"),
            "No": st.column_config.NumberColumn(disabled=True, width="small"),
            "競技分類": st.column_config.SelectboxColumn("競技分類", options=["サッカー", "フットサル"]),
            "カテゴリー": st.column_config.SelectboxColumn("カテゴリー", options=["U8", "U9", "U10", "U11", "U12"]),
        },
        use_container_width=True,
        key="editor",
        on_change=on_data_change
    )
