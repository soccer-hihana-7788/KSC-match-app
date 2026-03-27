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

# --- 1. ページ設定 ---
st.set_page_config(page_title="KSC試合管理ツール", layout="wide")

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
        data = ws_list.get_all_records()
    except Exception:
        data = []
    
    df = pd.DataFrame(data) if data else pd.DataFrame(columns=SHEET_COLUMNS)
    
    if "競技分類" not in df.columns: df.insert(3, "競技分類", "サッカー")
    df["競技分類"] = df["競技分類"].replace("", "サッカー")
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    if '日時' in df.columns: df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    # 制御用列の追加
    df.insert(0, '選択', False) # 削除用の選択列を一番左に
    df['結果入力'] = False
    df['写真管理'] = False
    
    if "試合場所" in df.columns:
        df = df.rename(columns={"試合場所": "対戦場所"})
    return df

def add_new_row_at_top(new_data_dict):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        
        # 新しいNoの採番
        existing_nos = ws.col_values(1)[1:]
        new_no = max([int(n) for n in existing_nos if n.isdigit()] + [0]) + 1
        
        row_values = []
        for col in SHEET_COLUMNS:
            if col == "No": val = new_no
            elif col == "試合場所": val = new_data_dict.get("対戦場所", "")
            else: val = new_data_dict.get(col, "")
            if isinstance(val, date): val = val.isoformat()
            row_values.append(str(val))
            
        # 空白行の上部（データ行の先頭 2行目）に挿入
        ws.insert_row(row_values, 2)
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def delete_selected_rows(nos_to_delete):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        all_data = ws.get_all_records()
        
        # 行番号を特定して逆順に削除（行ズレ防止）
        for no in sorted(nos_to_delete, reverse=True):
            # No列(1列目)を検索して行削除
            cell = ws.find(str(no), in_col=1)
            if cell:
                ws.delete_rows(cell.row)
        return True
    except Exception as e:
        st.error(f"削除エラー: {e}")
        return False

# --- 3. 認証・状態管理 ---
if 'df_list' not in st.session_state: st.session_state.df_list = load_data()
if 'page' not in st.session_state: st.session_state.page = "list"
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None

is_authenticated = st.query_params.get("auth") == "true"

if not is_authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID")
    p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.query_params["auth"] = "true"
            st.rerun()
    st.stop()

# --- 4. 画面遷移 ---

# A. 写真管理
if st.session_state.media_no is not None:
    no = st.session_state.media_no
    st.title(f"🖼️ 写真管理 (No.{no})")
    if st.button("← 一覧に戻る"): st.session_state.media_no = None; st.rerun()
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_media = sh.worksheet("media_storage")
    except: ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3"); ws_media.append_row(["match_no", "filename", "base64_data"])
    uploaded_file = st.file_uploader("写真を選択", type=["png", "jpg", "jpeg"])
    if uploaded_file and st.button("アップロード"):
        img = Image.open(uploaded_file); img = ImageOps.exif_transpose(img).convert("RGB")
        buf = BytesIO(); img.thumbnail((350, 350)); img.save(buf, format="JPEG", quality=35)
        encoded = base64.b64encode(buf.getvalue()).decode()
        ws_media.append_row([str(no), uploaded_file.name, encoded]); st.success("保存完了"); st.rerun()
    match_photos = [r for r in ws_media.get_all_records() if str(r.get('match_no')) == str(no)]
    if match_photos:
        cols = st.columns(3)
        for idx, item in enumerate(match_photos):
            with cols[idx % 3]: 
                st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                if st.button("削除", key=f"del_{idx}"): cell = ws_media.find(item['base64_data']); ws_media.delete_rows(cell.row); st.rerun()

# B. 試合結果
elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"): st.session_state.selected_no = None; st.rerun()
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: ws_res = sh.add_worksheet(title="results", rows="100", cols="2"); ws_res.append_row(["key", "data"])
    res_raw = ws_res.acell("A2").value; all_results = json.loads(res_raw) if res_raw else {}
    for i in range(1, 11):
        rk = f"res_{no}_{i}"; sd = all_results.get(rk, {"score": " - ", "scorers": [""], "result": ""})
        with st.expander(f"第 {i} 試合"):
            res_val = st.radio("結果", ["勝ち", "負け", "引き分け"], index=0, key=f"rad_{rk}")
            new_l = st.text_input("自", key=f"l_{rk}"); new_r = st.text_input("相手", key=f"r_{rk}")
            sc_input = st.text_area("得点者", key=f"txt_{rk}")
            if st.button("保存", key=f"btn_{rk}"):
                all_results[rk] = {"score": f"{new_l}-{new_r}", "scorers": [s.strip() for s in sc_input.split(",") if s.strip()], "result": res_val}
                ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False)); st.success("保存完了"); st.rerun()

# C. 新規作成
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
        if st.form_submit_button("登録して一覧の最上部へ保存"):
            new_data = {"カテゴリー": c_cat, "日時": c_date, "競技分類": c_type, "対戦相手": c_opp, "対戦場所": c_loc, "試合分類": c_class, "備考": c_memo}
            if add_new_row_at_top(new_data):
                st.session_state.df_list = load_data(); st.session_state.page = "list"; st.rerun()

# D. 一覧
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
    
    # 表示列の定義
    display_cols = ['選択', '結果入力', '対戦相手', '対戦場所', '日時', 'カテゴリー', '試合分類', '競技分類', '写真管理']
    current_df = df[display_cols]
    
    # 削除ボタンの表示判定
    selected_indices = []
    
    edited_df = st.data_editor(
        current_df, hide_index=True, 
        column_config={
            "選択": st.column_config.CheckboxColumn("選択", width="small"),
            "結果入力": st.column_config.CheckboxColumn("結果入力", width="small"),
            "写真管理": st.column_config.CheckboxColumn("写真管理", width="small"),
            "日時": st.column_config.DateColumn("日時", format="YYYY-MM-DD")
        }, 
        use_container_width=True, key="main_editor"
    )

    # 選択チェックボックスの監視
    nos_to_delete = []
    for idx, row in edited_df.iterrows():
        if row["選択"]:
            nos_to_delete.append(df.iloc[idx]["No"])
        if row["結果入力"]:
            st.session_state.selected_no = int(df.iloc[idx]["No"]); st.rerun()
        if row["写真管理"]:
            st.session_state.media_no = int(df.iloc[idx]["No"]); st.rerun()

    # 削除ボタンの出現
    if nos_to_delete:
        st.warning(f"{len(nos_to_delete)}件のデータが選択されています。")
        if st.button("🗑️ 選択した行を削除する", type="primary"):
            if delete_selected_rows(nos_to_delete):
                st.success("削除しました"); st.session_state.df_list = load_data(); st.rerun()

    st.markdown("---")
    if st.button("🖨️ 一覧を印刷用表示"):
        print_df = current_df.drop(columns=['選択', '結果入力', '写真管理'])
        html_table = print_df.to_html(index=False, classes='print-table')
        components.html(f"<html><head><style>.print-table {{ border-collapse: collapse; width: 100%; }} .print-table th, .print-table td {{ border: 1px solid black; padding: 8px; }}</style></head><body>{html_table}<script>setTimeout(()=>{{window.print()}},500)</script></body></html>", height=0)
