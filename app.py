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

# スプレッドシートの物理的な列順を完全固定（A=1, B=2...）
COL_MAP = {
    "No": 1, "カテゴリー": 2, "日時": 3, "競技分類": 4,
    "対戦相手": 5, "試合場所": 6, "試合分類": 7, "備考": 8
}

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_info = json.loads(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

@st.cache_data(ttl=10) # 読み込み高速化（10秒間はキャッシュ利用）
def load_initial_data():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws = sh.get_worksheet(0)
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    
    # 競技分類列の存在確認とデータ型整備
    if "競技分類" not in df.columns:
        df.insert(3, "競技分類", "サッカー")
    df["競技分類"] = df["競技分類"].replace("", "サッカー").fillna("サッカー")
    
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    if '日時' in df.columns: df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    df['詳細'] = False
    df['写真(画像)'] = False
    return df

def fast_save(row_idx, col_name, value):
    """通信を最小化：特定の1セルだけを即時更新"""
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        col_num = COL_MAP.get(col_name)
        if col_num:
            save_val = value.isoformat() if hasattr(value, 'isoformat') else str(value)
            ws.update_cell(row_idx + 2, col_num, save_val)
            return True
    except:
        return False

# --- 3. セッション管理 ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'df_list' not in st.session_state: st.session_state.df_list = load_initial_data()
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None

# ログイン画面
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u, p = st.text_input("ID"), st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.rerun()
        else: st.error("IDまたはパスワードが違います")
    st.stop()

# --- 4. データ変更時の即時処理 ---
def on_edit():
    changes = st.session_state["editor"]
    for row_idx_key, edit_values in changes["edited_rows"].items():
        actual_index = st.session_state.current_display_df.index[row_idx_key]
        
        # ボタン系処理
        if edit_values.get("詳細") is True:
            st.session_state.selected_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        if edit_values.get("写真(画像)") is True:
            st.session_state.media_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        
        # 入力値（競技分類含む）の保存
        for col, val in edit_values.items():
            if col in COL_MAP:
                # 1. メモリを更新
                st.session_state.df_list.at[actual_index, col] = val
                # 2. シートを1マスだけピンポイント更新（高速）
                fast_save(actual_index, col, val)

# --- 5. 画面表示 ---
if st.session_state.media_no is not None:
    st.title(f"🖼️ 写真管理 (No.{st.session_state.media_no})")
    if st.button("← 一覧に戻る"): st.session_state.media_no = None; st.rerun()
    st.info("写真管理：通常通り利用可能です")

elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"): st.session_state.selected_no = None; st.rerun()
    
    # 試合結果の読み込み
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: ws_res = sh.add_worksheet("results", 100, 2); ws_res.append_row(["key", "data"])
    
    res_raw = ws_res.acell("A2").value
    all_res = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        d = all_res.get(rk, {"score": " - ", "result": "", "scorers": []})
        with st.expander(f"第 {i} 試合: {d['score']} {d['result']}"):
            # フォームを使わず直接配置することでリロードを防止
            r_val = st.radio("結果", ["勝ち", "負け", "引き分け"], key=f"r{rk}", horizontal=True)
            c1, c2 = st.columns(2)
            s_l = c1.text_input("自", key=f"l{rk}", value=d['score'].split('-')[0])
            s_r = c2.text_input("相手", key=f"r{rk}", value=d['score'].split('-')[-1])
            t_in = st.text_area("得点者", key=f"t{rk}", value=", ".join(d['scorers']))
            
            if st.button(f"第{i}試合を保存", key=f"b{rk}"):
                all_res[rk] = {"score": f"{s_l}-{s_r}", "result": r_val, "scorers": [x.strip() for x in t_in.split(",") if x.strip()]}
                ws_res.update_acell("A2", json.dumps(all_res, ensure_ascii=False))
                st.toast("保存完了（画面は移動しません）")

else:
    st.title("⚽ KSC試合管理一覧")
    
    # フィルター
    c1, c2 = st.columns([2, 1])
    sq = c1.text_input("🔍 検索")
    cf = c2.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])
    
    df = st.session_state.df_list.copy()
    if cf != "すべて": df = df[df["カテゴリー"] == cf]
    if sq: df = df[df.apply(lambda r: sq.lower() in r.astype(str).str.lower().values, axis=1)]
    
    st.session_state.current_display_df = df
    
    # 競技分類を確実に保存するエディタ
    st.data_editor(
        df,
        hide_index=True,
        column_config={
            "詳細": st.column_config.CheckboxColumn("入力", width="small"),
            "写真(画像)": st.column_config.CheckboxColumn("写真", width="small"),
            "No": st.column_config.NumberColumn(disabled=True, width="small"),
            "競技分類": st.column_config.SelectboxColumn("競技分類", options=["サッカー", "フットサル"], required=True),
            "カテゴリー": st.column_config.SelectboxColumn("カテゴリー", options=["U8", "U9", "U10", "U11", "U12"]),
        },
        use_container_width=True,
        key="editor",
        on_change=on_edit
    )
