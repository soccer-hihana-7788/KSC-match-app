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

# オレンジ基調の明るいダッシュボード用カスタムCSS
st.markdown("""
    <style>
    /* 全体の背景色を少し明るく温かみのあるオレンジ系（アイボリー）にする */
    .stApp {
        background-color: #FFF7ED;
        font-family: 'Helvetica Neue', Arial, sans-serif;
    }
    
    /* 余白の調整 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1400px;
    }

    /* Container (カード) のスタイル定義 */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
        border: 1px solid #FED7AA; /* 枠線も少しオレンジ系に */
        padding: 10px;
    }

    /* 全てのボタンの基本形状をモダンに */
    div.stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
        border: 1px solid #FDBA74 !important; /* ボタン枠線オレンジ系 */
        color: #431407 !important; /* 文字色濃いブラウン */
    }
    
    div.stButton > button:hover {
        background-color: #FFEDD5 !important;
        border-color: #F97316 !important;
    }

    /* Primary属性を持つ主要アクションボタンのスタイル */
    div.stButton > button[kind="primary"] {
        background-color: #F97316 !important; /* メインカラーをオレンジに */
        color: white !important;
        border: none !important;
        box-shadow: 0 4px 6px -1px rgba(249, 115, 22, 0.2) !important;
    }
    
    div.stButton > button[kind="primary"]:hover {
        background-color: #EA580C !important;
        transform: translateY(-2px);
        box-shadow: 0 6px 8px -1px rgba(234, 88, 12, 0.3) !important;
        color: white !important;
    }

    /* ダイアログ（ポップアップ）内のボタンスタイル */
    div[data-testid="stDialog"] div.stButton > button {
        border-radius: 6px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ブラウザストレージによる状態保持と自動復旧 ---
def sync_state_to_storage():
    if st.session_state.get("authenticated"):
        page = st.session_state.get("page", "list")
        year = st.session_state.get("selected_year", "2025")
        s_no = st.session_state.get("selected_no")
        m_no = st.session_state.get("media_no")
        e_no = st.session_state.get("edit_no")

        state_data = {
            "auth": True,
            "auth_time": str(st.session_state.get("auth_time", "")),
            "page": page,
            "selected_no": s_no,
            "media_no": m_no,
            "edit_no": e_no,
            "selected_year": year
        }
        js_code = f"localStorage.setItem('ksc_state', '{json.dumps(state_data)}');"
        components.html(f"<script>{js_code}</script>", height=0)

        # URLパラメータも同時に更新し、スマホ再読み込み(画面OFF/ON)からの復帰を確実にする
        st.query_params["ksc_auth"] = "true"
        st.query_params["auth_time"] = str(st.session_state.get("auth_time", ""))
        st.query_params["p"] = page
        st.query_params["s_year"] = year
        
        if s_no is not None: st.query_params["s_no"] = str(s_no)
        elif "s_no" in st.query_params: del st.query_params["s_no"]
        
        if m_no is not None: st.query_params["m_no"] = str(m_no)
        elif "m_no" in st.query_params: del st.query_params["m_no"]
        
        if e_no is not None: st.query_params["e_no"] = str(e_no)
        elif "e_no" in st.query_params: del st.query_params["e_no"]

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
                    
                    const page = parsed.page || 'list';
                    const year = parsed.selected_year || '2025';
                    
                    url.searchParams.set('p', page);
                    url.searchParams.set('s_year', year);
                    
                    // null文字列によるエラーを防ぐため、値がある場合のみセット
                    if(parsed.selected_no !== null && parsed.selected_no !== undefined) url.searchParams.set('s_no', parsed.selected_no);
                    if(parsed.media_no !== null && parsed.media_no !== undefined) url.searchParams.set('m_no', parsed.media_no);
                    if(parsed.edit_no !== null && parsed.edit_no !== undefined) url.searchParams.set('e_no', parsed.edit_no);
                    
                    window.location.replace(url.href);
                }
            }
        }
    } catch (e) {
        const url = new URL(window.location.href);
        if (!url.searchParams.get('ksc_auth')) {
            url.searchParams.set('ksc_auth', 'true');
            url.searchParams.set('auth_time', new Date().toISOString());
            url.searchParams.set('p', 'list');
            url.searchParams.set('s_year', '2025');
            window.location.replace(url.href);
        }
    }
    </script>
    """
    components.html(js_load, height=0)

# スマホ復帰時の状態復元（エラー時は確実に一覧画面へフォールバック）
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    params = st.query_params
    if params.get("ksc_auth") == "true" and params.get("auth_time"):
        try:
            stored_time = datetime.fromisoformat(params.get("auth_time"))
            if datetime.now() - stored_time < timedelta(hours=6):
                st.session_state.authenticated = True
                st.session_state.auth_time = stored_time
                
                # デフォルトを一覧画面として安全に初期化
                st.session_state.page = "list"
                st.session_state.selected_year = "2025"
                st.session_state.selected_no = None
                st.session_state.media_no = None
                st.session_state.edit_no = None
                
                def safe_int(val):
                    # null文字列等が混入した場合のエラーを防止
                    if val and str(val).lower() not in ["null", "none", "undefined", ""]:
                        return int(float(val))
                    return None

                try:
                    if params.get("p"): st.session_state.page = params.get("p")
                    if params.get("s_year"): st.session_state.selected_year = params.get("s_year")
                    
                    s_no = safe_int(params.get("s_no"))
                    if s_no is not None: st.session_state.selected_no = s_no
                        
                    m_no = safe_int(params.get("m_no"))
                    if m_no is not None: st.session_state.media_no = m_no
                        
                    e_no = safe_int(params.get("e_no"))
                    if e_no is not None: st.session_state.edit_no = e_no
                except Exception:
                    # 個別復元エラー時は強制的に一覧へ戻す
                    st.session_state.page = "list"
                    st.session_state.selected_no = None
                    st.session_state.media_no = None
                    st.session_state.edit_no = None
        except Exception:
            # 認証時間のパース等で致命的エラーになった場合も、一覧へ戻して操作可能にする
            st.session_state.authenticated = True
            st.session_state.auth_time = datetime.now()
            st.session_state.page = "list"
            st.session_state.selected_year = "2025"
            st.session_state.selected_no = None
            st.session_state.media_no = None
            st.session_state.edit_no = None

# --- 3. スプレッドシート設定 ---
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QmQ5uw5HI3tHmYTC29uR8jh1IeSnu4Afn7a4en7yvLc/edit#gid=0"
SHEET_COLUMNS = ["No", "カテゴリー", "日時", "競技分類", "対戦相手", "試合場所", "試合分類", "備考"]

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_info = json.loads(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}"); st.stop()

def get_worksheet_name():
    year = st.session_state.get("selected_year", "2025")
    return f"list_{year}"

def load_data():
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    ws_name = get_worksheet_name()
    
    try: ws_2025 = sh.worksheet("list_2025")
    except: ws_2025 = sh.get_worksheet(0)
    data_2025 = ws_2025.get_all_values()

    try:
        ws_list = sh.worksheet(ws_name)
        all_values = ws_list.get_all_values()
        
        if ws_name == "list_2026" and (not all_values or len(all_values) < 2):
            if len(data_2025) >= 2:
                ws_list.update("A1", data_2025)
                all_values = data_2025
    except:
        if ws_name == "list_2025":
            ws_list = ws_2025
            all_values = data_2025
        else:
            ws_list = sh.add_worksheet(title=ws_name, rows="500", cols=str(len(SHEET_COLUMNS)))
            init_data = data_2025 if ws_name == "list_2026" and len(data_2025) >= 2 else [SHEET_COLUMNS]
            ws_list.update("A1", init_data)
            all_values = init_data
            
    try:
        if not all_values or len(all_values) < 2:
            return pd.DataFrame(columns=['選択', '試合詳細'] + SHEET_COLUMNS + ['写真管理'])
        header = all_values[0]
        valid_rows = [r for r in all_values[1:] if len(r) > 4 and r[4].strip() != ""]
        df = pd.DataFrame(valid_rows, columns=header)
    except:
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
        df['試合詳細'] = False
        df['写真管理'] = False
    return df

# アプリ再起動時（リロード時）に最新データを強制取得してバグを防ぐ
if "initialized" in st.session_state and st.session_state.get("authenticated"):
    if "data_loaded_on_init" not in st.session_state:
        st.session_state.df_list = load_data()
        st.session_state.data_loaded_on_init = True

if not st.session_state.get("authenticated", False):
    load_auth_from_storage()

def update_or_add_row(data_dict, target_no=None):
    for attempt in range(3):
        try:
            client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
            ws_name = get_worksheet_name()
            try: ws = sh.worksheet(ws_name)
            except: ws = sh.get_worksheet(0)
            
            no_vals = ws.col_values(1)
            if target_no:
                cell = ws.find(str(target_no))
                if not cell: return None
                target_row = cell.row; new_no = target_no
            else:
                last_idx = 0
                for i, val in enumerate(no_vals):
                    if val.strip() != "": last_idx = i + 1
                existing_nos = [int(v) for v in no_vals[1:] if v.strip().isdigit()]
                new_no = max(existing_nos + [0]) + 1; target_row = last_idx + 1

            if target_row > ws.row_count:
                ws.add_rows(max(100, target_row - ws.row_count))

            row = []
            for col in SHEET_COLUMNS:
                if col == "No": val = new_no
                elif col == "試合場所": val = data_dict.get("対戦場所", "")
                else: val = data_dict.get(col, "")
                row.append(str(val.isoformat() if isinstance(val, (date, datetime)) else val))
            ws.update(f"A{target_row}", [row]); return new_no
        except Exception as e:
            if attempt == 2: st.error(f"保存エラー: {e}"); return None
            time.sleep(1)

# --- 4. 状態管理 ---
AUTH_TIMEOUT_HOURS = 6
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "selected_year" not in st.session_state: st.session_state.selected_year = None

if st.session_state.get("auth_time"):
    if datetime.now() - st.session_state.auth_time > timedelta(hours=AUTH_TIMEOUT_HOURS):
        st.session_state.authenticated = False
        st.query_params.clear()
        components.html("<script>localStorage.removeItem('ksc_state');</script>", height=0)

if 'df_list' not in st.session_state: st.session_state.df_list = pd.DataFrame()
if 'page' not in st.session_state: st.session_state.page = "list"
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None
if 'action_no' not in st.session_state: st.session_state.action_no = None
if 'edit_no' not in st.session_state: st.session_state.edit_no = None

# --- UI: ログイン画面 ---
if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.container(border=True):
            st.markdown("<h2 style='text-align: center; color: #431407;'>⚽ KSC ログイン</h2>", unsafe_allow_html=True)
            st.write("")
            u = st.text_input("👤 ユーザーID")
            p = st.text_input("🔑 パスワード", type="password")
            st.write("")
            if st.button("ログイン", type="primary", use_container_width=True):
                if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
                    now = datetime.now()
                    st.session_state.authenticated = True
                    st.session_state.auth_time = now
                    st.query_params["ksc_auth"] = "true"
                    st.query_params["auth_time"] = now.isoformat()
                    sync_state_to_storage()
                    st.rerun()
                else:
                    st.error("IDまたはパスワードが正しくありません。")
    st.stop()

# --- UI: 年度選択画面 ---
if st.session_state.selected_year is None:
    st.markdown("<h2>📅 年度選択ダッシュボード</h2>", unsafe_allow_html=True)
    st.info("表示または登録する年度を選択してください。")
    
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    worksheets = sh.worksheets()
    existing_years = []
    for ws in worksheets:
        if ws.title.startswith("list_"):
            existing_years.append(ws.title.replace("list_", ""))
    
    for y in ["2025", "2026"]:
        if y not in existing_years: existing_years.append(y)
    existing_years = sorted(list(set(existing_years)), reverse=True)

    with st.container(border=True):
        st.markdown("#### 管理対象の年度")
        cols = st.columns(min(len(existing_years), 4))
        for idx, y in enumerate(existing_years):
            with cols[idx % 4]:
                if st.button(f"{y}年度を開く", type="primary", key=f"year_btn_{y}", use_container_width=True):
                    st.session_state.selected_year = y
                    st.session_state.df_list = load_data()
                    sync_state_to_storage()
                    st.rerun()

    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        with st.expander("➕ 新規年度の登録"):
            new_y = st.text_input("登録する年度（例: 2027）")
            if st.button("年度を新規作成"):
                if new_y.isdigit() and len(new_y) == 4:
                    st.session_state.selected_year = new_y
                    st.session_state.df_list = load_data()
                    sync_state_to_storage()
                    st.success(f"{new_y}年度を作成しました。")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("4桁の数字で入力してください。")

    with col2:
        with st.expander("🗑️ 年度の削除"):
            st.write("削除する年度を選択してください。")
            for y in existing_years:
                if st.button(f"{y}年度を削除", key=f"del_confirm_{y}", use_container_width=True):
                    try:
                        target_ws = sh.worksheet(f"list_{y}")
                        sh.del_worksheet(target_ws)
                        st.success(f"{y}年度を削除しました。")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"削除に失敗しました: {e}")
    st.stop()

# --- 5. 画面遷移 ---
# --- UI: 新規登録・修正ページ ---
if st.session_state.page == "create" or st.session_state.edit_no is not None:
    is_edit = st.session_state.edit_no is not None
    
    st.markdown(f"<h2>📝 {st.session_state.selected_year}年度 試合情報の{'修正' if is_edit else '新規登録'}</h2>", unsafe_allow_html=True)
    
    st.write("") # ボタン上部にスペース
    col_nav, _ = st.columns([1.5, 4.5])
    with col_nav:
        if st.button("← ダッシュボードへ戻る", use_container_width=True): 
            st.session_state.page = "list"
            st.session_state.edit_no = None
            st.session_state.df_list = load_data() # 最新データをロード
            sync_state_to_storage()
            st.rerun()

    st.info("必要項目を入力し、下部の「保存する」ボタンを押してください。")

    default_vals = {"カテゴリー":"U12", "日時":date.today(), "競技分類":"サッカー", "対戦相手":"", "対戦場所":"", "試合分類":"", "備考":""}
    
    if st.session_state.df_list is None or st.session_state.df_list.empty:
        st.session_state.df_list = load_data()
        
    if is_edit:
        target_rows = st.session_state.df_list[st.session_state.df_list["No"] == st.session_state.edit_no]
        if not target_rows.empty:
            row = target_rows.iloc[0]
            default_vals.update({"カテゴリー":row["カテゴリー"], "日時":row["日時"], "競技分類":row["競技分類"], "対戦相手":row["対戦相手"], "対戦場所":row["対戦場所"], "試合分類":row["試合分類"], "備考":row["備考"]})
    
    with st.container(border=True):
        with st.form("edit_form"):
            c_cat = st.selectbox("カテゴリー", ["U8", "U9", "U10", "U11", "U12"], index=["U8", "U9", "U10", "U11", "U12"].index(default_vals["カテゴリー"]))
            c_date = st.date_input("日時", value=default_vals["日時"])
            c_type = st.selectbox("競技分類", ["サッカー", "フットサル"], index=0 if default_vals["競技分類"]=="サッカー" else 1)
            c_opp = st.text_input("対戦相手", value=default_vals["対戦相手"], placeholder="例: 愛知FC")
            c_loc = st.text_input("対戦場所", value=default_vals["対戦場所"], placeholder="例: 一宮フットサルパーク")
            c_class = st.text_input("試合分類", value=default_vals["試合分類"], placeholder="例: TRM, 公式戦など")
            c_memo = st.text_area("備考", value=default_vals["備考"], placeholder="特記事項があれば入力してください")
            
            st.write("")
            submitted = st.form_submit_button("💾 保存する", type="primary")
            
            if submitted:
                with st.spinner("保存中..."):
                    res_no = update_or_add_row({"カテゴリー": c_cat, "日時": c_date, "競技分類": c_type, "対戦相手": c_opp, "対戦場所": c_loc, "試合分類": c_class, "備考": c_memo}, target_no=st.session_state.edit_no)
                    if res_no:
                        st.session_state.df_list = load_data()
                        st.session_state.edit_no = None
                        st.session_state.page = "list"
                        sync_state_to_storage()
                        st.success("登録が完了しました。")
                        time.sleep(1)
                        st.rerun()

    if is_edit:
        st.write("")
        if st.button("📸 紐づく写真を追加・管理する", use_container_width=True):
            st.session_state.media_no = st.session_state.edit_no
            st.session_state.edit_no = None
            st.session_state.page = "list"
            sync_state_to_storage(); st.rerun()

# --- UI: 写真管理ページ ---
elif st.session_state.media_no is not None:
    no = st.session_state.media_no
    
    st.markdown("<h2>🖼️ 写真管理ダッシュボード</h2>", unsafe_allow_html=True)
    
    st.write("")
    col_nav, _ = st.columns([1.5, 4.5])
    with col_nav:
        if st.button("← ダッシュボードへ戻る", use_container_width=True): 
            st.session_state.media_no = None
            st.session_state.df_list = load_data() # 最新データをロード
            sync_state_to_storage()
            st.rerun()
    
    st.info("試合に関連する写真をアップロードして保管できます。")
    
    with st.container(border=True):
        client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
        try: ws_media = sh.worksheet("media_storage")
        except: ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3"); ws_media.append_row(["match_no", "filename", "base64_data"])
        
        uploaded_file = st.file_uploader("写真を選択 (JPG / PNG)", type=["png", "jpg", "jpeg"])
        if uploaded_file and st.button("アップロードを実行", type="primary"):
            with st.spinner("最適化中..."):
                img = Image.open(uploaded_file); img = ImageOps.exif_transpose(img).convert("RGB"); q=60; img.thumbnail((600,600))
                for _ in range(7):
                    buf=BytesIO(); img.save(buf, format="JPEG", quality=q); enc=base64.b64encode(buf.getvalue()).decode()
                    if len(enc)<48000: break
                    q-=10; img.thumbnail((img.size[0]*0.9, img.size[1]*0.9))
                if len(enc) >= 50000: st.error("サイズ超過。別の画像をお試しください。")
                else: ws_media.append_row([str(no), uploaded_file.name, enc]); st.success("完了"); st.rerun()
                
    st.write("#### 登録済み写真")
    match_photos = [r for r in ws_media.get_all_records() if str(r.get('match_no')) == str(no)]
    if match_photos:
        cols = st.columns(3)
        for idx, item in enumerate(match_photos):
            with cols[idx % 3]:
                with st.container(border=True):
                    st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                    if st.button("削除", key=f"del_{idx}", use_container_width=True):
                        cell=ws_media.find(item['base64_data']); ws_media.delete_rows(cell.row); st.rerun()
    else:
        st.write("登録されている写真はありません。")

# --- UI: 試合詳細（スコア結果入力）ページ ---
elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    
    st.markdown("<h2>📝 試合詳細とスコア登録</h2>", unsafe_allow_html=True)
    
    st.write("")
    col_nav, _ = st.columns([1.5, 4.5])
    with col_nav:
        if st.button("← ダッシュボードへ戻る", use_container_width=True): 
            st.session_state.selected_no = None
            st.session_state.df_list = load_data() # 最新データをロード
            sync_state_to_storage()
            st.rerun()
        
    st.info("各試合の結果スコアや得点者を記録できます。")

    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: ws_res = sh.add_worksheet(title="results", rows="100", cols="2"); ws_res.append_row(["key", "data"])
    res_raw = ws_res.acell("A2").value; all_results = json.loads(res_raw) if res_raw else {}
    
    with st.container(border=True):
        for i in range(1, 11):
            rk = f"res_{no}_{i}"; curr = all_results.get(rk, {"score": " - ", "scorers": [], "result": "", "memo": ""})
            c_res = curr.get("result", "")
            h_txt = f"第 {i} 試合" + (f" （{c_res} {curr['score']}）" if c_res else "")
            
            # 得点者がいる場合はタブのタイトルにも反映して表示する
            scorers_list = curr.get("scorers", [])
            if scorers_list:
                h_txt += f" ⚽ 得点者: {', '.join(scorers_list)}"
            
            with st.expander(h_txt, expanded=(i==1)):
                r_opts = ["勝ち", "負け", "引き分け"]; r_idx = r_opts.index(c_res) if c_res in r_opts else 0
                res_val = st.radio("試合結果", r_opts, index=r_idx, key=f"rad_{rk}", horizontal=True)
                
                s_p = curr["score"].split("-"); l_v = s_p[0].strip() if len(s_p)>0 else ""; r_v = s_p[1].strip() if len(s_p)>1 else ""
                cl, cr = st.columns(2)
                with cl: nl = st.text_input("自チーム得点", value=l_v, key=f"l_{rk}")
                with cr: nr = st.text_input("相手チーム得点", value=r_v, key=f"r_{rk}")
                
                sc_in = st.text_input("得点者 (カンマ区切り)", value=", ".join(curr.get("scorers",[])), key=f"txt_{rk}")
                res_memo = st.text_area("特記事項・メモ", value=curr.get("memo", ""), key=f"memo_{rk}")
                
                if st.button("保存する", key=f"btn_{rk}", type="primary"):
                    with st.spinner("保存中..."):
                        all_results[rk] = {
                            "score": f"{nl}-{nr}", 
                            "scorers": [s.strip() for s in sc_in.split(",") if s.strip()], 
                            "result": res_val,
                            "memo": res_memo
                        }
                        ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                        st.success(f"第 {i} 試合の結果を保存しました。")
                        sync_state_to_storage(); time.sleep(0.5); st.rerun()

# --- UI: メインダッシュボード（一覧画面） ---
else:
    # ヘッダーと年度切り替え
    col_title, col_nav = st.columns([4, 1])
    with col_title:
        st.markdown(f"<h2>📊 KSC試合管理ダッシュボード <span style='font-size:1.2rem; color:#6B7280;'>({st.session_state.selected_year}年度)</span></h2>", unsafe_allow_html=True)
    with col_nav:
        if st.button("📅 年度を変更", use_container_width=True):
            st.session_state.selected_year = None
            st.session_state.df_list = pd.DataFrame()
            sync_state_to_storage()
            st.rerun()

    # 初心者向けガイド
    st.info("💡 **初めての方へ:** 右側の「➕ 新規登録」から新しい試合を追加できます。一覧の左端「選択」にチェックを入れると、修正・コピー・削除メニューが表示されます。")

    # --- アクション用ポップアップダイアログの定義 ---
    @st.dialog("⚙️ 選択した試合に対する操作")
    def show_action_dialog():
        st.write("実行する操作を選択してください。")
        ca1, ca2, ca3, ca4 = st.columns(4)
        with ca1:
            if st.button("修正", use_container_width=True): 
                st.session_state.edit_no = st.session_state.action_no
                st.session_state.action_no = None
                sync_state_to_storage()
                st.rerun()
        with ca2:
            if st.button("コピー", use_container_width=True):
                with st.spinner("コピー作成中..."):
                    target_rows = st.session_state.df_list[st.session_state.df_list["No"] == st.session_state.action_no]
                    if not target_rows.empty:
                        row = target_rows.iloc[0]
                        copy_data = {
                            "カテゴリー": row.get("カテゴリー", ""),
                            "日時": row.get("日時", date.today()),
                            "競技分類": row.get("競技分類", ""),
                            "対戦相手": row.get("対戦相手", ""),
                            "対戦場所": row.get("対戦場所", ""),
                            "試合分類": row.get("試合分類", ""),
                            "備考": row.get("備考", "")
                        }
                        res_no = update_or_add_row(copy_data, target_no=None)
                        if res_no:
                            st.session_state.df_list = load_data()
                            st.success("選択した試合を一番下へコピーしました。")
                st.session_state.action_no = None
                sync_state_to_storage()
                time.sleep(1)
                st.rerun()
        with ca3:
            if st.button("削除", use_container_width=True):
                client = get_gspread_client()
                sh = client.open_by_url(SPREADSHEET_URL)
                ws_name = get_worksheet_name()
                try: ws = sh.worksheet(ws_name)
                except: ws = sh.get_worksheet(0)
                cell = ws.find(str(st.session_state.action_no))
                if cell:
                    ws.delete_rows(cell.row)
                    st.success("削除が完了しました。")
                st.session_state.action_no = None
                st.session_state.df_list = load_data()
                time.sleep(1)
                st.rerun()
        with ca4:
            if st.button("キャンセル", use_container_width=True): 
                st.session_state.action_no = None
                st.rerun()
    # -----------------------------------------------

    # チェックボックスが選択されている場合はポップアップダイアログを呼び出す
    if st.session_state.action_no:
        show_action_dialog()
    
    # コントロールパネル（検索・絞り込み・新規登録）
    with st.container(border=True):
        st.markdown("**🔍 検索 & 操作パネル**")
        c1, c2, c3, c4 = st.columns([2, 1.5, 0.5, 1.5])
        with c1: 
            sq = st.text_input("検索", label_visibility="collapsed", placeholder="キーワード検索 (対戦相手・場所など)...")
        with c2: 
            cf = st.selectbox("カテゴリー", ["すべて", "U8", "U9", "U10", "U11", "U12"], label_visibility="collapsed")
        with c4:
            if st.button("➕ 新規試合登録", type="primary", use_container_width=True): 
                st.session_state.page = "create"; st.session_state.edit_no = None; sync_state_to_storage(); st.rerun()

    # データ一覧パネル
    if st.session_state.df_list is None or st.session_state.df_list.empty:
        st.session_state.df_list = load_data()
        
    df = st.session_state.df_list.copy()
    if not df.empty:
        if cf != "すべて": df = df[df["カテゴリー"] == cf]
        if sq: df = df[df.apply(lambda r: sq.lower() in r.astype(str).str.lower().values, axis=1)]
        
        # 登録日付（日時）の新しい行が一番上にくるようにソート（同日の場合はNoの降順）
        if '日時' in df.columns:
            df = df.sort_values(by=['日時', 'No'], ascending=[False, False])
    
    with st.container(border=True):
        if not df.empty:
            disp = ['選択', '試合詳細', '対戦相手', '対戦場所', '日時', 'カテゴリー', '試合分類', '競技分類', '写真管理']
            
            # スマホ復帰時などのキャッシュ不整合(無限ループフリーズ)を防ぐため、エディタ用キーをユニーク化
            editor_key = f"main_editor_{st.session_state.get('editor_key_counter', 0)}"
            
            edf = st.data_editor(df[['No'] + disp].reset_index(drop=True), hide_index=True, 
                column_config={
                    "No": None,
                    "選択": st.column_config.CheckboxColumn("選択", width="small"), 
                    "試合詳細": st.column_config.CheckboxColumn("試合詳細", width="small"), 
                    "写真管理": st.column_config.CheckboxColumn("写真管理", width="small"), 
                    "日時": st.column_config.DateColumn("日時", format="YYYY-MM-DD")
                }, 
                use_container_width=True, key=editor_key, height=500)
            
            needs_rerun = False
            for i in range(len(edf)):
                row = edf.iloc[i]
                if row.get("選択"): 
                    st.session_state.action_no = int(row["No"])
                    needs_rerun = True
                if row.get("試合詳細"): 
                    st.session_state.selected_no = int(row["No"])
                    needs_rerun = True
                if row.get("写真管理"): 
                    st.session_state.media_no = int(row["No"])
                    needs_rerun = True
            
            if needs_rerun:
                # 状態が変わったらカウンターを増やして次回は完全に新しいエディタとして描画する
                st.session_state.editor_key_counter = st.session_state.get("editor_key_counter", 0) + 1
                sync_state_to_storage()
                st.rerun()
        else:
            st.warning("該当する試合データが見つかりません。")

    st.write("")
    col_print, _ = st.columns([1, 4])
    with col_print:
        if st.button("🖨️ 画面を印刷する", use_container_width=True):
            if not df.empty:
                p_df = df[disp]
                components.html(f"<html><body>{p_df.to_html(index=False)}<script>window.print()</script></body></html>", height=0)
