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
st.set_page_config(page_title="KSC試合管理ツール", page_icon="⚽", layout="wide")

# --- モダンSaaS風・ダッシュボードカスタムCSS ---
st.markdown("""
    <style>
    /* 全体背景をクールなライトグレーに */
    .stApp {
        background-color: #F8FAFC;
        font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    }
    
    /* 余白の調整 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1400px;
    }

    /* Container (カード) のスタイル定義（白背景＋シャドウ） */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        border: 1px solid #E2E8F0;
        padding: 1.2rem;
    }

    /* メトリクス（KPI）の数字の色をプロっぽく */
    div[data-testid="stMetricValue"] {
        color: #1E3A8A !important; /* 深いネイビー */
        font-weight: 700;
    }

    /* 文字色を暗いグレーに固定 */
    .stApp, .stMarkdown, .stText, p, span, label, h1, h2, h3, h4, h5, h6, li {
        color: #334155 !important;
    }

    /* 入力フィールドの洗練 */
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-baseweb="textarea"] > div,
    div[data-testid="stDateInput"] > div {
        background-color: #F1F5F9 !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 8px !important;
        color: #334155 !important;
    }

    /* ボタンの共通スタイル */
    div.stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
        border: 1px solid #CBD5E1 !important;
        color: #475569 !important;
    }
    
    div.stButton > button:hover {
        background-color: #F1F5F9 !important;
        border-color: #94A3B8 !important;
    }

    /* 主要アクションボタン（Primary）のスタイル */
    div.stButton > button[kind="primary"] {
        background-color: #2563EB !important; /* 鮮やかなブルー */
        color: white !important;
        border: none !important;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.3) !important;
    }
    
    div.stButton > button[kind="primary"]:hover {
        background-color: #1D4ED8 !important;
        transform: translateY(-2px);
        box-shadow: 0 6px 8px -1px rgba(37, 99, 235, 0.4) !important;
    }
    
    /* サイドバーの背景 */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E2E8F0;
    }
    </style>
    """, unsafe_allow_html=True)


# --- 2. ブラウザストレージによる状態保持 (省略なし) ---
def sync_state_to_storage():
    if st.session_state.get("authenticated"):
        state_data = {
            "auth": True,
            "auth_time": str(st.session_state.get("auth_time", "")),
            "page": st.session_state.get("page", "dashboard"),
            "selected_year": st.session_state.get("selected_year", "2025")
        }
        js_code = f"localStorage.setItem('ksc_state', '{json.dumps(state_data)}');"
        components.html(f"<script>{js_code}</script>", height=0)

def load_auth_from_storage():
    js_load = """
    <script>
    try {
        const data = localStorage.getItem('ksc_state');
        if (data) {
            const parsed = JSON.parse(data);
            const url = new URL(window.location.href);
            const authTime = new Date(parsed.auth_time);
            const now = new Date();
            const diffHours = (now - authTime) / (1000 * 60 * 60);

            if (parsed.auth && diffHours < 6) {
                if (!url.searchParams.get('ksc_auth')) {
                    url.searchParams.set('ksc_auth', 'true');
                    url.searchParams.set('auth_time', parsed.auth_time);
                    window.location.replace(url.href);
                }
            }
        }
    } catch (e) {}
    </script>
    """
    components.html(js_load, height=0)

if "initialized" not in st.session_state:
    st.session_state.initialized = True
    params = st.query_params
    if params.get("ksc_auth") == "true" and params.get("auth_time"):
        try:
            stored_time = datetime.fromisoformat(params.get("auth_time"))
            if datetime.now() - stored_time < timedelta(hours=6):
                st.session_state.authenticated = True
                st.session_state.auth_time = stored_time
                st.session_state.page = "dashboard"
                st.session_state.selected_year = "2025"
        except Exception:
            pass

# --- 3. スプレッドシート設定 ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QmQ5uw5HI3tHmYTC29uR8jh1IeSnu4Afn7a4en7yvLc/edit#gid=0"
SHEET_COLUMNS = ["No", "カテゴリー", "日時", "競技分類", "対戦相手", "対戦場所", "試合分類", "備考"]

@st.cache_resource
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_info = json.loads(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

def get_worksheet_name():
    year = st.session_state.get("selected_year", "2025")
    return f"list_{year}"

def load_data():
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws_name = get_worksheet_name()
    
    try: ws = sh.worksheet(ws_name)
    except:
        ws = sh.add_worksheet(title=ws_name, rows="500", cols=str(len(SHEET_COLUMNS)))
        ws.update("A1", [SHEET_COLUMNS])
        
    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        return pd.DataFrame(columns=SHEET_COLUMNS)
    
    header = all_values[0]
    valid_rows = [r for r in all_values[1:] if len(r) > 4 and r[4].strip() != ""]
    df = pd.DataFrame(valid_rows, columns=header)
    
    if not df.empty:
        if 'No' in df.columns:
            df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
        if '日時' in df.columns:
            df['日時'] = pd.to_datetime(df['日時'], errors='coerce').dt.date
    return df

def update_or_add_row(data_dict, target_no=None):
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws_name = get_worksheet_name()
    ws = sh.worksheet(ws_name)
    
    no_vals = ws.col_values(1)
    existing_nos = [int(v) for v in no_vals[1:] if v.strip().isdigit()]
    new_no = max(existing_nos + [0]) + 1

    row = []
    for col in SHEET_COLUMNS:
        val = data_dict.get(col, "")
        if col == "No": val = new_no if not target_no else target_no
        row.append(str(val.isoformat() if isinstance(val, (date, datetime)) else val))

    if target_no:
        cell = ws.find(str(target_no))
        if cell:
            ws.update(f"A{cell.row}", [row])
            return target_no
    else:
        ws.insert_row(row, index=2)
        return new_no
    return None


# --- 4. 状態管理初期化 ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "page" not in st.session_state: st.session_state.page = "dashboard"
if "selected_year" not in st.session_state: st.session_state.selected_year = "2025"
if "edit_data" not in st.session_state: st.session_state.edit_data = None
if "active_match_no" not in st.session_state: st.session_state.active_match_no = None

if not st.session_state.authenticated:
    load_auth_from_storage()

# --- UI: ログイン画面 ---
if not st.session_state.authenticated:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.container(border=True):
            st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>⚽ KSC 管理ポータル</h2>", unsafe_allow_html=True)
            st.write("")
            u = st.text_input("👤 ユーザーID")
            p = st.text_input("🔑 パスワード", type="password")
            st.write("")
            if st.button("ログイン", type="primary", use_container_width=True):
                if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
                    st.session_state.authenticated = True
                    st.session_state.auth_time = datetime.now()
                    sync_state_to_storage()
                    st.rerun()
                else:
                    st.error("IDまたはパスワードが正しくありません。")
    st.stop()


# --- UI: サイドバーナビゲーション ---
with st.sidebar:
    st.markdown("### ⚽ KSC Menu")
    st.markdown("---")
    
    if st.button("📊 ダッシュボード (一覧)", use_container_width=True, type="primary" if st.session_state.page == "dashboard" else "secondary"):
        st.session_state.page = "dashboard"
        st.session_state.active_match_no = None
        st.rerun()
        
    if st.button("➕ 新規試合登録", use_container_width=True, type="primary" if st.session_state.page == "create" else "secondary"):
        st.session_state.page = "create"
        st.session_state.edit_data = None
        st.rerun()
        
    st.markdown("---")
    # 年度切り替え
    years = ["2025", "2026", "2027"]
    sel_year = st.selectbox("📅 管理年度", years, index=years.index(st.session_state.selected_year))
    if sel_year != st.session_state.selected_year:
        st.session_state.selected_year = sel_year
        st.session_state.page = "dashboard"
        sync_state_to_storage()
        st.rerun()
        
    st.markdown("---")
    if st.button("🚪 ログアウト", use_container_width=True):
        st.session_state.clear()
        components.html("<script>localStorage.removeItem('ksc_state');</script>", height=0)
        st.rerun()


# --- データのロード ---
df = load_data()


# ==========================================
# メイン画面ルーティング
# ==========================================

# --- UI: メインダッシュボード（一覧画面） ---
if st.session_state.page == "dashboard":
    st.markdown(f"<h2>📊 {st.session_state.selected_year}年度 ダッシュボード</h2>", unsafe_allow_html=True)
    
    # 1. KPIサマリー (ダッシュボード感の演出)
    if not df.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📌 総試合数", f"{len(df)} 試合")
        col2.metric("⚽ サッカー", f"{len(df[df['競技分類'] == 'サッカー'])} 試合")
        col3.metric("👟 フットサル", f"{len(df[df['競技分類'] == 'フットサル'])} 試合")
        col4.metric("🏆 最新の試合日", df['日時'].max().strftime('%Y/%m/%d') if pd.notnull(df['日時'].max()) else "-")
        st.write("")

    # 2. 検索＆フィルタリング
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        with c1: sq = st.text_input("🔍 キーワード検索", placeholder="対戦相手、場所、メモなど...")
        with c2: cf = st.selectbox("📂 カテゴリー", ["すべて", "U8", "U9", "U10", "U11", "U12"])

    # フィルタ適用
    if not df.empty:
        if cf != "すべて": df = df[df["カテゴリー"] == cf]
        if sq: df = df[df.apply(lambda r: sq.lower() in r.astype(str).str.lower().values, axis=1)]
        df = df.sort_values(by=['日時', 'No'], ascending=[False, False])

    st.markdown("💡 **Tip:** 表の行をクリックすると、下部に詳細メニューが表示されます。")

    # 3. データテーブル（行選択機能付き）
    if not df.empty:
        # 表の表示項目を整理
        disp_df = df[['No', '日時', 'カテゴリー', '競技分類', '対戦相手', '対戦場所', '試合分類']].copy()
        
        event = st.dataframe(
            disp_df,
            hide_index=True,
            use_container_width=True,
            selection_mode="single-row",
            on_select="rerun",
            key="match_table"
        )
        
        # 4. アクションパネル（行が選択されたら表示）
        selected_rows = event.selection.rows
        if selected_rows:
            sel_idx = selected_rows[0]
            sel_data = df.iloc[sel_idx]
            match_no = sel_data['No']
            st.session_state.active_match_no = match_no
            
            st.markdown("---")
            st.markdown(f"### ⚙️ 選択中の試合: {sel_data['対戦相手']} ({sel_data['日時']})")
            
            ac1, ac2, ac3, ac4 = st.columns(4)
            with ac1:
                if st.button("📝 試合詳細/スコア登録", use_container_width=True, type="primary"):
                    st.session_state.page = "details"
                    st.rerun()
            with ac2:
                if st.button("🖼️ 写真を追加・管理", use_container_width=True):
                    st.session_state.page = "photos"
                    st.rerun()
            with ac3:
                if st.button("✏️ 内容を修正", use_container_width=True):
                    st.session_state.edit_data = sel_data.to_dict()
                    st.session_state.page = "create"
                    st.rerun()
            with ac4:
                if st.button("🗑️ 削除", use_container_width=True):
                    client = get_gspread_client()
                    ws = client.open_by_url(SPREADSHEET_URL).worksheet(get_worksheet_name())
                    cell = ws.find(str(match_no))
                    if cell: ws.delete_rows(cell.row)
                    st.success("削除しました！")
                    time.sleep(1)
                    st.rerun()
    else:
        st.info("データがありません。「新規試合登録」から追加してください。")


# --- UI: 新規登録・修正ページ ---
elif st.session_state.page == "create":
    is_edit = st.session_state.edit_data is not None
    st.markdown(f"<h2>{'✏️ 試合情報の修正' if is_edit else '➕ 新規試合の登録'}</h2>", unsafe_allow_html=True)
    
    defaults = {"カテゴリー":"U12", "日時":date.today(), "競技分類":"サッカー", "対戦相手":"", "対戦場所":"", "試合分類":"", "備考":""}
    if is_edit: defaults.update(st.session_state.edit_data)
    
    with st.container(border=True):
        with st.form("match_form"):
            col1, col2 = st.columns(2)
            with col1:
                c_date = st.date_input("📅 日時", value=defaults["日時"])
                c_cat = st.selectbox("📂 カテゴリー", ["U8", "U9", "U10", "U11", "U12"], index=["U8","U9","U10","U11","U12"].index(defaults["カテゴリー"]))
                c_type = st.selectbox("⚽ 競技分類", ["サッカー", "フットサル"], index=0 if defaults["競技分類"]=="サッカー" else 1)
            with col2:
                c_opp = st.text_input("⚔️ 対戦相手", value=defaults["対戦相手"], placeholder="例: 愛知FC")
                c_loc = st.text_input("📍 対戦場所", value=defaults["対戦場所"], placeholder="例: 一宮フットサルパーク")
                c_class = st.text_input("🏷️ 試合分類", value=defaults["試合分類"], placeholder="例: TRM, 公式戦など")
            
            c_memo = st.text_area("📝 備考", value=defaults["備考"], placeholder="特記事項があれば入力してください")
            
            st.write("")
            submitted = st.form_submit_button("💾 保存する", type="primary")
            if submitted:
                with st.spinner("保存中..."):
                    save_data = {"カテゴリー": c_cat, "日時": c_date, "競技分類": c_type, "対戦相手": c_opp, "対戦場所": c_loc, "試合分類": c_class, "備考": c_memo}
                    target = st.session_state.edit_data['No'] if is_edit else None
                    update_or_add_row(save_data, target_no=target)
                    st.success("保存が完了しました！")
                    st.session_state.page = "dashboard"
                    time.sleep(1)
                    st.rerun()


# --- UI: 試合詳細・スコア登録 ---
elif st.session_state.page == "details" and st.session_state.active_match_no:
    no = st.session_state.active_match_no
    st.markdown("<h2>📝 スコア・詳細結果登録</h2>", unsafe_allow_html=True)
    if st.button("← ダッシュボードに戻る"):
        st.session_state.page = "dashboard"
        st.rerun()

    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: 
        ws_res = sh.add_worksheet(title="results", rows="100", cols="2")
        ws_res.append_row(["key", "data"])
        
    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}

    with st.container(border=True):
        st.info("第1試合〜第3試合までの結果を入力できます。（必要に応じて展開してください）")
        for i in range(1, 4): # 見やすさのためデフォルト3試合表示に削減
            rk = f"res_{no}_{i}"
            curr = all_results.get(rk, {"score": "", "scorers": [], "result": "", "memo": ""})
            
            with st.expander(f"🏅 第 {i} 試合", expanded=(i==1)):
                r_opts = ["勝ち", "負け", "引き分け"]
                res_val = st.radio("試合結果", r_opts, index=r_opts.index(curr["result"]) if curr["result"] in r_opts else None, horizontal=True, key=f"rad_{rk}")
                
                s_p = curr["score"].split("-") if "-" in curr["score"] else []
                cl, cr = st.columns(2)
                with cl: nl = st.text_input("自チーム得点", value=s_p[0].strip() if len(s_p)>0 else "", key=f"l_{rk}")
                with cr: nr = st.text_input("相手チーム得点", value=s_p[1].strip() if len(s_p)>1 else "", key=f"r_{rk}")
                
                sc_in = st.text_input("得点者 (カンマ区切り)", value=", ".join(curr.get("scorers",[])), key=f"txt_{rk}")
                if st.button("結果を保存", key=f"btn_{rk}", type="primary"):
                    all_results[rk] = {
                        "score": f"{nl}-{nr}" if nl or nr else "", 
                        "scorers": [s.strip() for s in sc_in.split(",") if s.strip()], 
                        "result": res_val if res_val else "",
                        "memo": ""
                    }
                    ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                    st.success("保存しました！")


# --- UI: 写真管理 ---
elif st.session_state.page == "photos" and st.session_state.active_match_no:
    no = st.session_state.active_match_no
    st.markdown("<h2>🖼️ 写真管理</h2>", unsafe_allow_html=True)
    if st.button("← ダッシュボードに戻る"):
        st.session_state.page = "dashboard"
        st.rerun()

    with st.container(border=True):
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL)
        try: ws_media = sh.worksheet("media_storage")
        except: 
            ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3")
            ws_media.append_row(["match_no", "filename", "base64_data"])
            
        uploaded_file = st.file_uploader("📸 試合の写真をアップロード", type=["png", "jpg", "jpeg"])
        if uploaded_file and st.button("アップロード実行", type="primary"):
            with st.spinner("画像を最適化中..."):
                img = Image.open(uploaded_file)
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((600,600))
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=60)
                enc = base64.b64encode(buf.getvalue()).decode()
                
                ws_media.append_row([str(no), uploaded_file.name, enc])
                st.success("アップロード完了！")
                st.rerun()

        st.markdown("### 登録済み写真")
        match_photos = [r for r in ws_media.get_all_records() if str(r.get('match_no')) == str(no)]
        if match_photos:
            cols = st.columns(3)
            for idx, item in enumerate(match_photos):
                with cols[idx % 3]:
                    st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                    if st.button("🗑️ 削除", key=f"del_img_{idx}"):
                        cell = ws_media.find(item['base64_data'])
                        ws_media.delete_rows(cell.row)
                        st.rerun()
        else:
            st.info("登録されている写真はありません。")
