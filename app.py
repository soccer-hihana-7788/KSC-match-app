import streamlit as st
import pandas as pd
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
        df = pd.DataFrame({
            "No": range(1, 101), "カテゴリー": ["U12"] * 100,
            "日時": [date.today().isoformat()] * 100,
            "競技分類": ["サッカー"] * 100,
            "対戦相手": [""] * 100,
            "試合場所": [""] * 100, "試合分類": [""] * 100, "備考": [""] * 100
        })
    else:
        df = pd.DataFrame(data)
        # 競技分類列の挿入
        if "競技分類" not in df.columns:
            df.insert(3, "競技分類", "サッカー")
    
    # 型の強制変換（int64エラー対策）
    if 'No' in df.columns: df['No'] = pd.to_numeric(df['No']).astype(int)
    if '日時' in df.columns: 
        df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    
    df['詳細'] = False
    df['写真(画像)'] = False
    
    target_order = ['詳細', 'No', 'カテゴリー', '日時', '競技分類', '対戦相手', '試合場所', '試合分類', '備考', '写真(画像)']
    return df[[c for c in target_order if c in df.columns]]

# 高速化・エラー対策版更新関数
def update_row(actual_index, updated_row_series):
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        ws = sh.get_worksheet(0)
        
        # Pythonの標準型に変換（int64回避）
        row_data = updated_row_series.copy()
        if '日時' in row_data:
            row_data['日時'] = str(row_data['日時'])
        
        drop_cols = ["詳細", "写真(画像)"]
        row_values = row_data.drop(labels=[c for c in drop_cols if c in row_data.index]).values.tolist()
        
        # 確実に標準的なPythonの型にキャスト
        row_values = [int(v) if isinstance(v, (pd.Int64Dtype, pd.api.types.np_dtype("int64"))) else v for v in row_values]
        
        ws.update(f"A{actual_index + 2}", [row_values])
    except Exception as e:
        st.error(f"保存エラー: {e}")

# --- 3. ログイン保持制御 ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

auth_check_js = """
<script>
    const expiry = window.localStorage.getItem('ksc_auth_expiry');
    const now = Date.now() / 1000;
    if (expiry && Number(expiry) > now) {
        const url = new URL(window.location.href);
        if (!url.searchParams.has('auth')) {
            url.searchParams.set('auth', 'true');
            window.location.href = url.href;
        }
    }
</script>
"""
components.html(auth_check_js, height=0)

if st.query_params.get("auth") == "true":
    st.session_state.authenticated = True

if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID")
    p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            expiry = (datetime.now() + timedelta(hours=6)).timestamp()
            set_storage_js = f"""
            <script>
                window.localStorage.setItem('ksc_auth_expiry', '{expiry}');
                const url = new URL(window.location.href);
                url.searchParams.set('auth', 'true');
                window.location.href = url.href;
            </script>
            """
            components.html(set_storage_js, height=0)
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
        
        if edit_values.get("詳細") is True:
            st.session_state.selected_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        if edit_values.get("写真(画像)") is True:
            st.session_state.media_no = int(st.session_state.df_list.at[actual_index, "No"])
            return
        
        for col, val in edit_values.items():
            if col not in ["詳細", "写真(画像)"]:
                st.session_state.df_list.at[actual_index, col] = val
        
        update_row(actual_index, st.session_state.df_list.iloc[actual_index])

# --- 5. メイン画面制御 ---
if st.session_state.media_no is not None:
    no = st.session_state.media_no
    st.title(f"🖼️ 写真管理 (No.{no})")
    if st.button("← 一覧に戻る"):
        st.session_state.media_no = None
        st.rerun()
    
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_media = sh.worksheet("media_storage")
    except:
        ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3")
        ws_media.append_row(["match_no", "filename", "base64_data"])
    
    uploaded_file = st.file_uploader("スマホ写真を選択", type=["png", "jpg", "jpeg"])
    if uploaded_file and st.button("アップロード実行"):
        with st.spinner("処理中..."):
            try:
                img = Image.open(uploaded_file)
                img = ImageOps.exif_transpose(img).convert("RGB")
                buf = BytesIO()
                img.thumbnail((800, 800))
                img.save(buf, format="JPEG", quality=70)
                encoded = base64.b64encode(buf.getvalue()).decode()
                ws_media.append_row([str(no), uploaded_file.name, encoded])
                st.success("保存しました")
                st.rerun()
            except Exception as e: st.error(f"エラー: {e}")

    match_photos = [r for r in ws_media.get_all_records() if str(r['match_no']) == str(no)]
    if match_photos:
        cols = st.columns(3)
        for idx, item in enumerate(match_photos):
            with cols[idx % 3]:
                st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                if st.button("削除", key=f"del_{idx}"):
                    cell = ws_media.find(item['base64_data'])
                    ws_media.delete_rows(cell.row)
                    st.rerun()

elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    st.title(f"📝 試合結果入力 (No.{no})")
    if st.button("← 一覧に戻る"):
        st.session_state.selected_no = None
        st.rerun()
    
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except:
        ws_res = sh.add_worksheet(title="results", rows="100", cols="2")
        ws_res.append_row(["key", "data"])

    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        sd = all_results.get(rk, {"score": "", "scorers": [""] * 10})
        with st.expander(f"第 {i} 試合"):
            sc = st.text_input("スコア", value=sd["score"], key=f"s_{rk}")
            sc_input = st.text_area("得点者", value=", ".join([s for s in sd["scorers"] if s]), key=f"p_{rk}")
            if st.button("保存", key=f"b_{rk}"):
                new_s = [s.strip() for s in sc_input.split(",") if s.strip()] + [""] * 10
                all_results[rk] = {"score": sc, "scorers": new_s[:10]}
                ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                st.success("保存しました")

else:
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
            "競技分類": st.column_config.SelectboxColumn("競技分類", options=["サッカー", "フットサル"], required=True),
            "カテゴリー": st.column_config.SelectboxColumn("カテゴリー", options=["U8", "U9", "U10", "U11", "U12"]),
            "日時": st.column_config.DateColumn("日時")
        }, 
        use_container_width=True, 
        key="editor", 
        on_change=on_data_change
    )
