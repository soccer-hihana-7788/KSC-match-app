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
import streamlit.components.v1 as components
import time

# --- 1. ページ設定 ---
st.set_page_config(page_title="KSC試合管理ツール", layout="wide")

# ボタンの色（濃いオレンジ）を維持
st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #d35400;
        color: white;
        border-radius: 5px;
        font-weight: bold;
        border: none;
    }
    div.stButton > button:hover {
        background-color: #a04000;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. スプレッドシート設定 ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QmQ5uw5HI3tHmYTC29uR8jh1IeSnu4Afn7a4en7yvLc/edit#gid=0"
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

def load_data():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws_list = sh.get_worksheet(0)
    try:
        all_values = ws_list.get_all_values()
        if not all_values or len(all_values) < 2:
            return pd.DataFrame(columns=['選択', '結果入力'] + SHEET_COLUMNS + ['写真管理'])
        header = all_values[0]
        valid_rows = [r for r in all_values[1:] if len(r) > 4 and r[4].strip() != ""]
        df = pd.DataFrame(valid_rows, columns=header)
    except Exception:
        df = pd.DataFrame(columns=SHEET_COLUMNS)
    
    if not df.empty:
        if 'No' in df.columns:
            df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
        if '日時' in df.columns:
            df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
        if "試合場所" in df.columns:
            df = df.rename(columns={"試合場所": "対戦場所"})
        elif "対戦場所" not in df.columns:
            df["対戦場所"] = ""
        df.insert(0, '選択', False)
        df['結果入力'] = False
        df['写真管理'] = False
    else:
        cols = ['選択', '結果入力', 'No', 'カテゴリー', '日時', '競技分類', '対戦相手', '対戦場所', '試合分類', '備考', '写真管理']
        df = pd.DataFrame(columns=cols)
    return df

def add_new_row_strictly_at_blank_top(new_data_dict):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        no_column_values = ws.col_values(1)
        last_data_idx = 0
        for i, val in enumerate(no_column_values):
            if val.strip() != "":
                last_data_idx = i + 1
        existing_nos = [int(v) for v in no_column_values[1:] if v.strip().isdigit()]
        new_no = max(existing_nos + [0]) + 1
        row_values = []
        for col in SHEET_COLUMNS:
            if col == "No": val = new_no
            elif col == "試合場所": val = new_data_dict.get("対戦場所", "")
            else: val = new_data_dict.get(col, "")
            if isinstance(val, (date, datetime)): val = val.isoformat()
            row_values.append(str(val))
        target_row = last_data_idx + 1
        ws.update(f"A{target_row}", [row_values])
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

# --- 3. 状態管理（6時間維持） ---
AUTH_TIMEOUT_HOURS = 6

if 'df_list' not in st.session_state:
    st.session_state.df_list = load_data()
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "auth_time" not in st.session_state:
    st.session_state.auth_time = None

current_time = datetime.now()
if st.session_state.auth_time:
    elapsed = current_time - st.session_state.auth_time
    if elapsed > timedelta(hours=AUTH_TIMEOUT_HOURS):
        st.session_state.authenticated = False
        st.session_state.auth_time = None

if 'page' not in st.session_state:
    st.session_state.page = "list"
if 'selected_no' not in st.session_state:
    st.session_state.selected_no = None
if 'media_no' not in st.session_state:
    st.session_state.media_no = None

# ログイン画面
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID")
    p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.session_state.auth_time = datetime.now()
            st.rerun()
    st.stop()

# --- 4. 画面遷移 ---
# 写真管理
if st.session_state.media_no is not None:
    no = st.session_state.media_no
    st.title(f"🖼️ 写真管理 (No.{no})")
    if st.button("← 一覧に戻る"):
        st.session_state.media_no = None
        st.rerun()
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_media = sh.worksheet("media_storage")
    except:
        ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3")
        ws_media.append_row(["match_no", "filename", "base64_data"])
    uploaded_file = st.file_uploader("写真を選択", type=["png", "jpg", "jpeg"])
    if uploaded_file and st.button("アップロード"):
        with st.spinner("アップロード中..."):
            img = Image.open(uploaded_file); img = ImageOps.exif_transpose(img).convert("RGB")
            buf = BytesIO(); img.thumbnail((800, 800)); img.save(buf, format="JPEG", quality=50)
            encoded = base64.b64encode(buf.getvalue()).decode()
            ws_media.append_row([str(no), uploaded_file.name, encoded]); st.success("完了"); time.sleep(1); st.rerun()
    match_photos = [r for r in ws_media.get_all_records() if str(r.get('match_no')) == str(no)]
    if match_photos:
        cols = st.columns(3)
        for idx, item in enumerate(match_photos):
            with cols[idx % 3]: 
                st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                if st.button("削除", key=f"del_{idx}"):
                    cell = ws_media.find(item['base64_data'])
                    if cell: ws_media.delete_rows(cell.row); st.rerun()

# 【修正】結果入力（保存の確実化と見出しへの結果表示）
elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"):
        st.session_state.selected_no = None
        st.rerun()
    
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: ws_res = sh.add_worksheet(title="results", rows="100", cols="2"); ws_res.append_row(["key", "data"])
    
    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}

    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        current_data = all_results.get(rk, {"score": " - ", "scorers": [], "result": ""})
        
        # 【修正】見出しに結果とスコアを表示
        header_text = f"第 {i} 試合"
        if current_data["result"]:
            header_text += f" （{current_data['result']} {current_data['score']}）"
            
        with st.expander(header_text):
            # 前回の値を初期値としてセット
            res_idx = ["勝ち", "負け", "引き分け"].index(current_data["result"]) if current_data["result"] in ["勝ち", "負け", "引き分け"] else 0
            res_val = st.radio("結果", ["勝ち", "負け", "引き分け"], index=res_idx, key=f"rad_{rk}")
            
            s_parts = current_data["score"].split("-")
            old_l = s_parts[0].strip() if len(s_parts) > 0 else ""
            old_r = s_parts[1].strip() if len(s_parts) > 1 else ""
            
            c_l, c_r = st.columns(2)
            with c_l: new_l = st.text_input("自スコア", value=old_l, key=f"l_{rk}")
            with c_r: new_r = st.text_input("相手スコア", value=old_r, key=f"r_{rk}")
            
            old_sc = ", ".join(current_data.get("scorers", []))
            sc_input = st.text_area("得点者 (カンマ区切り)", value=old_sc, key=f"txt_{rk}")
            
            if st.button("この試合を保存", key=f"btn_{rk}"):
                with st.spinner("保存中..."):
                    # データを辞書にまとめてJSON更新
                    all_results[rk] = {
                        "score": f"{new_l}-{new_r}",
                        "scorers": [s.strip() for s in sc_input.split(",") if s.strip()],
                        "result": res_val
                    }
                    ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                    st.success("保存しました")
                    time.sleep(0.5)
                    st.rerun()

# 新規登録
elif st.session_state.page == "create":
    st.title("➕ 新規試合登録")
    if st.button("← 戻る"): st.session_state.page = "list"; st.rerun()
    with st.form("create_form"):
        c_cat = st.selectbox("カテゴリー", ["U8", "U9", "U10", "U11", "U12"])
        c_date = st.date_input("日時", value=date.today())
        c_type = st.selectbox("競技分類", ["サッカー", "フットサル"])
        c_opp = st.text_input("対戦相手")
        c_loc = st.text_input("対戦場所")
        c_class = st.text_input("試合分類")
        c_memo = st.text_area("備考")
        if st.form_submit_button("試合管理一覧へ登録"):
            new_data = {"カテゴリー": c_cat, "日時": c_date, "競技分類": c_type, "対戦相手": c_opp, "対戦場所": c_loc, "試合分類": c_class, "備考": c_memo}
            if add_new_row_strictly_at_blank_top(new_data):
                st.session_state.df_list = load_data(); st.session_state.page = "list"; st.rerun()

# 一覧画面
else:
    st.title("⚽ KSC試合管理一覧")
    if st.button("➕ 新規試合登録", use_container_width=True):
        st.session_state.page = "create"; st.rerun()
    
    c1, c2 = st.columns([2, 1])
    with c1: search_query = st.text_input("🔍 検索")
    with c2: cat_filter = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])
    
    df = st.session_state.df_list.copy()
    if cat_filter != "すべて": df = df[df["カテゴリー"] == cat_filter]
    if search_query: df = df[df.apply(lambda r: search_query.lower() in r.astype(str).str.lower().values, axis=1)]
    
    if not df.empty:
        display_cols = ['選択', '結果入力', '対戦相手', '対戦場所', '日時', 'カテゴリー', '試合分類', '競技分類', '写真管理', 'No']
        display_cols = [c for c in display_cols if c in df.columns]
        current_df = df[display_cols].reset_index(drop=True)
        
        edited_df = st.data_editor(
            current_df, hide_index=True, 
            column_config={
                "選択": st.column_config.CheckboxColumn("選択", width="small"),
                "結果入力": st.column_config.CheckboxColumn("結果入力", width="small"),
                "写真管理": st.column_config.CheckboxColumn("写真管理", width="small"),
                "日時": st.column_config.DateColumn("日時", format="YYYY-MM-DD"),
                "No": None
            }, use_container_width=True, key="main_editor"
        )

        for i in range(len(edited_df)):
            edit_row = edited_df.iloc[i]
            if "No" in current_df.columns:
                original_no = int(current_df.iloc[i]["No"])
                if edit_row.get("結果入力"): st.session_state.selected_no = original_no; st.rerun()
                if edit_row.get("写真管理"): st.session_state.media_no = original_no; st.rerun()
    else:
        st.info("登録済みの試合はありません。")

    st.markdown("---")
    if st.button("🖨️ 一覧を印刷用表示"):
        if not df.empty:
            print_cols = [c for c in display_cols if c not in ['選択', '結果入力', '写真管理', 'No']]
            print_df = current_df[print_cols]
            html_table = print_df.to_html(index=False)
            components.html(f"<html><body>{html_table}<script>setTimeout(()=>{{window.print()}},500)</script></body></html>", height=0)
