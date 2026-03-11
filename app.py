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
        # キャッシュを介さず最新を取得
        data = ws_list.get_all_records()
    except Exception:
        data = []
    
    if not data:
        df = pd.DataFrame(columns=SHEET_COLUMNS)
        df["No"] = range(1, 101); df["カテゴリー"] = "U12"; df["日時"] = date.today().isoformat(); df["競技分類"] = "サッカー"
        df = df.fillna("")
    else:
        df = pd.DataFrame(data)
        # ズレ補正
        if "対戦相手" in df.columns:
            bug_mask = df["対戦相手"].isin(["サッカー", "フットサル"])
            if bug_mask.any():
                cols_to_fix = ["対戦相手", "試合場所", "試合分類", "備考"]
                for i in range(len(cols_to_fix) - 1):
                    df.loc[bug_mask, cols_to_fix[i]] = df.loc[bug_mask, cols_to_fix[i+1]]
                df.loc[bug_mask, "備考"] = ""
        if "競技分類" not in df.columns:
            df.insert(3, "競技分類", "サッカー")
        df["競技分類"] = df["競技分類"].replace("", "サッカー")
    
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    if '日時' in df.columns: df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    df['詳細'] = False; df['写真(画像)'] = False
    display_order = ['詳細', 'No', 'カテゴリー', '日時', '競技分類', '対戦相手', '試合場所', '試合分類', '備考', '写真(画像)']
    return df[[c for c in display_order if c in df.columns]]

def update_row(actual_index, updated_row_series):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        row_values = []
        for col in SHEET_COLUMNS:
            val = updated_row_series.get(col, "")
            if col == "日時" and hasattr(val, 'isoformat'): val = val.isoformat()
            elif isinstance(val, (np.integer, np.floating)): val = val.item()
            elif pd.isna(val): val = ""
            row_values.append(val)
        ws.update(f"A{actual_index + 2}", [row_values])
    except Exception as e: st.error(f"保存エラー: {e}")

# --- 3. ログイン・セッション管理 ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'df_list' not in st.session_state: st.session_state.df_list = load_data()
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None

# ログイン処理
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u, p = st.text_input("ID"), st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.rerun()
        else: st.error("IDまたはパスワードが違います")
    st.stop()

def on_data_change():
    changes = st.session_state["editor"]
    for row_idx, edit_values in changes["edited_rows"].items():
        actual_index = st.session_state.current_display_df.index[row_idx]
        if edit_values.get("詳細") is True:
            st.session_state.selected_no = int(st.session_state.df_list.at[actual_index, "No"]); return
        if edit_values.get("写真(画像)") is True:
            st.session_state.media_no = int(st.session_state.df_list.at[actual_index, "No"]); return
        for col, val in edit_values.items():
            if col not in ["詳細", "写真(画像)"]: st.session_state.df_list.at[actual_index, col] = val
        update_row(actual_index, st.session_state.df_list.iloc[actual_index])

# --- 4. メイン画面制御 ---
if st.session_state.media_no is not None:
    no = st.session_state.media_no
    st.title(f"🖼️ 写真管理 (No.{no})")
    if st.button("← 一覧に戻る"): st.session_state.media_no = None; st.rerun()
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_media = sh.worksheet("media_storage")
    except:
        ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3")
        ws_media.append_row(["match_no", "filename", "base64_data"])
    uploaded_file = st.file_uploader("スマホ写真を選択", type=["png", "jpg", "jpeg"])
    if uploaded_file and st.button("アップロード実行"):
        with st.spinner("処理中..."):
            try:
                img = Image.open(uploaded_file); img = ImageOps.exif_transpose(img).convert("RGB")
                buf = BytesIO(); img.thumbnail((800, 800)); img.save(buf, format="JPEG", quality=70)
                encoded = base64.b64encode(buf.getvalue()).decode()
                ws_media.append_row([str(no), uploaded_file.name, encoded])
                st.success("保存しました")
            except Exception as e: st.error(f"エラー: {e}")
    match_photos = [r for r in ws_media.get_all_records() if str(r['match_no']) == str(no)]
    if match_photos:
        cols = st.columns(3)
        for idx, item in enumerate(match_photos):
            with cols[idx % 3]:
                st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                if st.button("削除", key=f"del_{idx}"):
                    cell = ws_media.find(item['base64_data']); ws_media.delete_rows(cell.row); st.rerun()

elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"): st.session_state.selected_no = None; st.rerun()
    
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except:
        ws_res = sh.add_worksheet(title="results", rows="100", cols="2")
        ws_res.append_row(["key", "data"])
    
    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        sd = all_results.get(rk, {"score": " - ", "scorers": [""] * 10, "result": ""})
        parts = sd["score"].split("-")
        s_left = parts[0].strip() if len(parts) > 0 else ""
        s_right = parts[1].strip() if len(parts) > 1 else ""
        display_score = f"{s_left}-{s_right}" if (s_left or s_right) else "未入力"
        result_label = f" 【{sd.get('result', '')}】" if sd.get('result') else ""
        
        with st.expander(f"第 {i} 試合　　{display_score}{result_label}"):
            # st.formを撤廃：リロードを防ぎ画面位置を固定
            res_options = ["勝ち", "負け", "引き分け"]
            cur_res = sd.get("result", "")
            def_idx = res_options.index(cur_res) if cur_res in res_options else 0
            res_val = st.radio("結果", res_options, index=def_idx, horizontal=True, key=f"radio_{rk}")
            
            st.write("スコア入力")
            sc_col1, sc_col2, sc_col3 = st.columns([2, 1, 2])
            with sc_col1: new_left = st.text_input("自", value=s_left, label_visibility="collapsed", key=f"left_{rk}")
            with sc_col2: st.markdown("<h3 style='text-align: center; margin: 0;'>-</h3>", unsafe_allow_html=True)
            with sc_col3: new_right = st.text_input("相手", value=s_right, label_visibility="collapsed", key=f"right_{rk}")
            sc_input = st.text_area("得点者 (カンマ区切り)", value=", ".join([s for s in sd["scorers"] if s]), key=f"text_{rk}")
            
            if st.button("保存", key=f"btn_{rk}"):
                # 1. 保存用データの作成
                combined_score = f"{new_left}-{new_right}"
                new_s_list = [s.strip() for s in sc_input.split(",") if s.strip()] + [""] * 10
                all_results[rk] = {"score": combined_score, "scorers": new_s_list[:10], "result": res_val}
                
                # 2. スプレッドシートへ即時保存
                ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                
                # 3. 画面をリロードせずに成功を表示（st.rerun()を呼ばない）
                st.toast(f"第 {i} 試合を保存しました")
                st.success("保存完了。このまま次を入力できます。")

else:
    st.title("⚽ KSC試合管理一覧")
    c1, c2 = st.columns([2, 1])
    with c1: search_query = st.text_input("🔍 検索")
    with c2: cat_filter = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])
    
    df = st.session_state.df_list.copy()
    if cat_filter != "すべて": df = df[df["カテゴリー"] == cat_filter]
    if search_query: df = df[df.apply(lambda r: search_query.lower() in r.astype(str).str.lower().values, axis=1)]
    
    st.session_state.current_display_df = df
    st.data_editor(df, hide_index=True, column_config={
        "詳細": st.column_config.CheckboxColumn("結果入力", width="small"),
        "写真(画像)": st.column_config.CheckboxColumn("写真管理", width="small"),
        "No": st.column_config.NumberColumn(disabled=True, width="small"),
        "競技分類": st.column_config.SelectboxColumn("競技分類", options=["サッカー", "フットサル"], required=True),
        "カテゴリー": st.column_config.SelectboxColumn("カテゴリー", options=["U8", "U9", "U10", "U11", "U12"]),
        "日時": st.column_config.DateColumn("日時")
    }, use_container_width=True, key="editor", on_change=on_data_change)
