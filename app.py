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
    
    if not data:
        df = pd.DataFrame(columns=SHEET_COLUMNS)
    else:
        df = pd.DataFrame(data)
        if "競技分類" not in df.columns:
            df.insert(3, "競技分類", "サッカー")
        df["競技分類"] = df["競技分類"].replace("", "サッカー")

    if 'No' in df.columns: 
        df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    if '日時' in df.columns: 
        df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    df['結果入力'] = False
    df['写真管理'] = False
    
    if "試合場所" in df.columns:
        df = df.rename(columns={"試合場所": "対戦場所"})
    
    return df

def update_row(actual_index, updated_row_series):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        row_values = []
        save_data = updated_row_series.copy()
        if "対戦場所" in save_data:
            save_data["試合場所"] = save_data["対戦場所"]

        for col in SHEET_COLUMNS:
            val = save_data.get(col, "")
            if col == "日時" and hasattr(val, 'isoformat'): val = val.isoformat()
            elif isinstance(val, (np.integer, np.int64)): val = int(val)
            elif pd.isna(val): val = ""
            row_values.append(str(val))
        ws.update(f"A{actual_index + 2}", [row_values])
    except Exception as e:
        st.error(f"保存エラー: {e}")

# --- 3. 抜本的スクロール固定 & 6時間ログイン維持 ---
# 強力なスクロールガード
st.markdown("""
    <style>
    html { 
        scroll-behavior: auto !important;
        overscroll-behavior: none;
    }
    </style>
""", unsafe_allow_html=True)

persistence_js = """
<script>
    const AUTH_KEY = 'ksc_auth_expiry';
    const SCROLL_KEY = 'ksc_scroll_pos_v5';
    
    function applyScroll() {
        const savedPos = window.localStorage.getItem(SCROLL_KEY);
        if (savedPos) {
            const y = parseInt(savedPos);
            const p = window.parent;
            // セレクトボックス変更時の長時間リセットに対抗するため、多重に実行
            p.scrollTo(0, y);
            setTimeout(() => p.scrollTo(0, y), 10);
            setTimeout(() => p.scrollTo(0, y), 50);
            setTimeout(() => p.scrollTo(0, y), 200);
            setTimeout(() => p.scrollTo(0, y), 500);
            setTimeout(() => p.scrollTo(0, y), 1000);
        }
    }

    // スクロール位置の常時記録
    window.parent.addEventListener('scroll', () => {
        const currentY = window.parent.scrollY;
        if (currentY > 0) {
            window.localStorage.setItem(SCROLL_KEY, currentY);
        }
    }, { passive: true });

    // 描画サイクルに合わせて実行
    if (document.readyState === 'complete') {
        applyScroll();
    } else {
        window.addEventListener('load', applyScroll);
    }

    // 認証チェック (6時間維持)
    function checkAuth() {
        const expiry = window.localStorage.getItem(AUTH_KEY);
        const now = Date.now() / 1000;
        const url = new URL(window.parent.location.href);
        const hasAuthParam = url.searchParams.get('auth') === 'true';

        if (expiry && Number(expiry) < now) {
            window.localStorage.removeItem(AUTH_KEY);
            if (hasAuthParam) {
                url.searchParams.delete('auth');
                window.parent.location.href = url.href;
            }
            return;
        }
        if (expiry && Number(expiry) > now && !hasAuthParam) {
            url.searchParams.set('auth', 'true');
            window.parent.location.href = url.href;
        }
    }
    checkAuth();
</script>
"""
components.html(persistence_js, height=0)

is_authenticated = st.query_params.get("auth") == "true"

if not is_authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID")
    p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            expiry = (datetime.now() + timedelta(hours=6)).timestamp()
            st.query_params["auth"] = "true"
            components.html(f"""
                <script>
                    window.localStorage.setItem('ksc_auth_expiry', '{expiry}');
                    window.parent.location.reload();
                </script>
            """, height=0)
            st.stop()
        else:
            st.error("IDまたはパスワードが違います")
    st.stop()

# --- 4. セッション管理 ---
if 'df_list' not in st.session_state: st.session_state.df_list = load_data()
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None

def on_data_change():
    changes = st.session_state["editor"]
    # 編集が行われた際、即座に現在の位置を保存するよう指示（JS側と連携）
    for row_idx, edit_values in changes["edited_rows"].items():
        actual_index = st.session_state.current_display_df.index[row_idx]
        if edit_values.get("結果入力") is True:
            st.session_state.selected_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        if edit_values.get("写真管理") is True:
            st.session_state.media_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        for col, val in edit_values.items():
            if col not in ["結果入力", "写真管理"]:
                st.session_state.df_list.at[actual_index, col] = val
        update_row(actual_index, st.session_state.df_list.iloc[actual_index])

# --- 5. 画面制御 ---
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
    
    uploaded_file = st.file_uploader("スマホ写真を選択", type=["png", "jpg", "jpeg"])
    if uploaded_file and st.button("アップロード実行"):
        with st.spinner("画像を圧縮中..."):
            try:
                img = Image.open(uploaded_file); img = ImageOps.exif_transpose(img).convert("RGB")
                buf = BytesIO(); img.thumbnail((350, 350)); img.save(buf, format="JPEG", quality=35, optimize=True)
                encoded = base64.b64encode(buf.getvalue()).decode()
                if len(encoded) > 50000: st.error("サイズ制限エラー")
                else: ws_media.append_row([str(no), uploaded_file.name, encoded]); st.success("保存完了"); st.rerun()
            except Exception as e: st.error(f"失敗: {e}")

    match_photos = [r for r in ws_media.get_all_records() if str(r.get('match_no')) == str(no)]
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
    if st.button("← 一覧に戻る"):
        st.session_state.selected_no = None
        st.rerun()

    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except:
        ws_res = sh.add_worksheet(title="results", rows="100", cols="2")
        ws_res.append_row(["key", "data"])

    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        sd = all_results.get(rk, {"score": " - ", "scorers": [""], "result": ""})
        cur_score = sd.get("score", " - ")
        parts = cur_score.split("-")
        s_left = parts[0].strip() if len(parts) > 0 else ""
        s_right = parts[1].strip() if len(parts) > 1 else ""
        
        with st.expander(f"第 {i} 試合: {cur_score} {sd.get('result', '')}"):
            res_options = ["勝ち", "負け", "引き分け"]
            current_result = sd.get("result", "")
            def_idx = res_options.index(current_result) if current_result in res_options else 0
            res_val = st.radio("結果", res_options, index=def_idx, horizontal=True, key=f"rad_btn_{rk}")
            sc_col1, sc_col2 = st.columns(2)
            new_l = sc_col1.text_input("自", value=s_left, key=f"score_l_{rk}")
            new_r = sc_col2.text_input("相手", value=s_right, key=f"score_r_{rk}")
            scorers_val = ", ".join([str(s) for s in sd.get("scorers", []) if s])
            sc_input = st.text_area("得点者", value=scorers_val, key=f"txt_area_{rk}")
            if st.button("保存", key=f"btn_save_{rk}"):
                all_results[rk] = {"score": f"{new_l}-{new_r}", "scorers": [s.strip() for s in sc_input.split(",") if s.strip()], "result": res_val}
                ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                st.success("保存完了"); st.rerun()

else:
    st.title("⚽ KSC試合管理一覧")
    
    c1, c2 = st.columns([2, 1])
    with c1: search_query = st.text_input("🔍 検索")
    with c2: cat_filter = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])
    
    df = st.session_state.df_list.copy()
    if cat_filter != "すべて": df = df[df["カテゴリー"] == cat_filter]
    if search_query: 
        df = df[df.apply(lambda r: search_query.lower() in r.astype(str).str.lower().values, axis=1)]
    
    display_cols = ['結果入力', '対戦相手', '対戦場所', '日時', 'カテゴリー', '試合分類', '競技分類', '写真管理']
    st.session_state.current_display_df = df[[c for c in display_cols if c in df.columns]]
    
    st.data_editor(
        st.session_state.current_display_df, hide_index=True, 
        column_config={
            "結果入力": st.column_config.CheckboxColumn("結果入力", width="small"),
            "写真管理": st.column_config.CheckboxColumn("写真管理", width="small"),
            "競技分類": st.column_config.SelectboxColumn("競技分類", options=["サッカー", "フットサル"]),
            "カテゴリー": st.column_config.SelectboxColumn("カテゴリー", options=["U8", "U9", "U10", "U11", "U12"]),
            "日時": st.column_config.DateColumn("日時", format="YYYY-MM-DD")
        }, 
        use_container_width=True, key="editor", on_change=on_data_change
    )

    st.markdown("---")
    if st.button("🖨️ 入力内容を反映してPDF印刷・保存"):
        cols_to_print = [c for c in display_cols if c not in ['結果入力', '写真管理']]
        print_df = st.session_state.current_display_df[cols_to_print]
        html_table = print_df.to_html(index=False, classes='print-table')
        print_html = f"""
        <html>
        <head><style>
            .print-table {{ border-collapse: collapse; width: 100%; }}
            .print-table th, .print-table td {{ border: 1px solid black; padding: 8px; text-align: left; }}
            .print-table th {{ background-color: #f2f2f2; }}
        </style></head>
        <body><h2 style="text-align: center;">KSC試合管理一覧</h2>{html_table}
        <script>setTimeout(function() {{ window.print(); }}, 500);</script>
        </body></html>
        """
        components.html(print_html, height=0)
