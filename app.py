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
    div[data-testid="stHorizontalBlock"] div.stButton > button {
        background-color: #767676 !important;
        color: white !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ブラウザストレージによる状態保持と自動復旧 ---
def sync_state_to_storage():
    state_data = {
        "auth": st.session_state.get("authenticated", False),
        "auth_time": str(st.session_state.get("auth_time", "")),
        "page": st.session_state.get("page", "list"),
        "selected_no": st.session_state.get("selected_no"),
        "media_no": st.session_state.get("media_no"),
        "edit_no": st.session_state.get("edit_no"),
        "selected_year": st.session_state.get("selected_year")
    }
    js_code = f"localStorage.setItem('ksc_state', '{json.dumps(state_data)}');"
    components.html(f"<script>{js_code}</script>", height=0)

def load_auth_from_storage():
    js_load = """
    <script>
    const data = localStorage.getItem('ksc_state');
    if (data) {
        const parsed = JSON.parse(data);
        const url = new URL(window.location.href);
        if (parsed.auth && !url.searchParams.get('ksc_auth')) {
            url.searchParams.set('ksc_auth', 'true');
            url.searchParams.set('auth_time', parsed.auth_time);
            if(parsed.page) url.searchParams.set('p', parsed.page);
            if(parsed.selected_no) url.searchParams.set('s_no', parsed.selected_no);
            if(parsed.selected_year) url.searchParams.set('s_year', parsed.selected_year);
            window.location.href = url.href;
        }
    }
    </script>
    """
    components.html(js_load, height=0)

if "initialized" not in st.session_state:
    st.session_state.initialized = True
    load_auth_from_storage()
    
    params = st.query_params
    if params.get("ksc_auth") == "true" and params.get("auth_time"):
        try:
            stored_time = datetime.fromisoformat(params.get("auth_time"))
            if datetime.now() - stored_time < timedelta(hours=6):
                st.session_state.authenticated = True
                st.session_state.auth_time = stored_time
                if params.get("p"): st.session_state.page = params.get("p")
                if params.get("s_no"): st.session_state.selected_no = int(params.get("s_no"))
                if params.get("s_year"): st.session_state.selected_year = params.get("s_year")
        except:
            pass

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
            return pd.DataFrame(columns=['選択', '結果入力'] + SHEET_COLUMNS + ['写真管理'])
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
        df['結果入力'] = False
        df['写真管理'] = False
    return df

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
        sync_state_to_storage()

if 'df_list' not in st.session_state: st.session_state.df_list = pd.DataFrame()
if 'page' not in st.session_state: st.session_state.page = "list"
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None
if 'action_no' not in st.session_state: st.session_state.action_no = None
if 'edit_no' not in st.session_state: st.session_state.edit_no = None

# ログイン画面
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID"); p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            now = datetime.now()
            st.session_state.authenticated = True
            st.session_state.auth_time = now
            st.query_params["ksc_auth"] = "true"
            st.query_params["auth_time"] = now.isoformat()
            sync_state_to_storage()
            st.rerun()
    st.stop()

# 年度選択画面
if st.session_state.selected_year is None:
    st.title("📅 年度選択")
    st.write("表示または登録する年度を選択してください。")
    
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    worksheets = sh.worksheets()
    existing_years = []
    for ws in worksheets:
        if ws.title.startswith("list_"):
            existing_years.append(ws.title.replace("list_", ""))
    
    for y in ["2025", "2026"]:
        if y not in existing_years: existing_years.append(y)
    existing_years = sorted(list(set(existing_years)))

    tabs = st.tabs([f"{y}年度" for y in existing_years])
    for i, y in enumerate(existing_years):
        with tabs[i]:
            if st.button(f"{y}年度の管理画面を開く", key=f"year_btn_{y}"):
                st.session_state.selected_year = y
                st.session_state.df_list = load_data()
                sync_state_to_storage()
                st.rerun()

    st.markdown("---")
    with st.expander("➕ 新規年度登録"):
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
    st.stop()

# --- 5. 画面遷移 ---
# 修正・新規登録
if st.session_state.page == "create" or st.session_state.edit_no is not None:
    is_edit = st.session_state.edit_no is not None; st.title(f"📝 {st.session_state.selected_year}年度 試合情報の" + ("修正" if is_edit else "新規登録"))
    default_vals = {"カテゴリー":"U12", "日時":date.today(), "競技分類":"サッカー", "対戦相手":"", "対戦場所":"", "試合分類":"", "備考":""}
    if is_edit:
        target_rows = st.session_state.df_list[st.session_state.df_list["No"] == st.session_state.edit_no]
        if not target_rows.empty:
            row = target_rows.iloc[0]
            default_vals.update({"カテゴリー":row["カテゴリー"], "日時":row["日時"], "競技分類":row["競技分類"], "対戦相手":row["対戦相手"], "対戦場所":row["対戦場所"], "試合分類":row["試合分類"], "備考":row["備考"]})
    
    if st.button("← 戻る"): st.session_state.page = "list"; st.session_state.edit_no = None; sync_state_to_storage(); st.rerun()
    
    with st.form("edit_form"):
        c_cat = st.selectbox("カテゴリー", ["U8", "U9", "U10", "U11", "U12"], index=["U8", "U9", "U10", "U11", "U12"].index(default_vals["カテゴリー"]))
        c_date = st.date_input("日時", value=default_vals["日時"])
        c_type = st.selectbox("競技分類", ["サッカー", "フットサル"], index=0 if default_vals["競技分類"]=="サッカー" else 1)
        c_opp = st.text_input("対戦相手", value=default_vals["対戦相手"])
        c_loc = st.text_input("対戦場所", value=default_vals["対戦場所"])
        c_class = st.text_input("試合分類", value=default_vals["試合分類"])
        c_memo = st.text_area("備考", value=default_vals["備考"])
        submitted = st.form_submit_button("登録")
        
        if submitted:
            with st.spinner("登録中..."):
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
        if st.checkbox("写真管理 (写真を追加する)"):
            st.session_state.media_no = st.session_state.edit_no
            st.session_state.edit_no = None
            st.session_state.page = "list"
            sync_state_to_storage(); st.rerun()

# 写真管理
elif st.session_state.media_no is not None:
    no = st.session_state.media_no; st.title("🖼️ 写真管理")
    if st.button("← 一覧に戻る"): st.session_state.media_no = None; sync_state_to_storage(); st.rerun()
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_media = sh.worksheet("media_storage")
    except: ws_media = sh.add_worksheet(title="media_storage", rows="2000", cols="3"); ws_media.append_row(["match_no", "filename", "base64_data"])
    uploaded_file = st.file_uploader("写真を選択", type=["png", "jpg", "jpeg"])
    if uploaded_file and st.button("アップロードを実行"):
        with st.spinner("最適化中..."):
            img = Image.open(uploaded_file); img = ImageOps.exif_transpose(img).convert("RGB"); q=60; img.thumbnail((600,600))
            for _ in range(7):
                buf=BytesIO(); img.save(buf, format="JPEG", quality=q); enc=base64.b64encode(buf.getvalue()).decode()
                if len(enc)<48000: break
                q-=10; img.thumbnail((img.size[0]*0.9, img.size[1]*0.9))
            if len(enc) >= 50000: st.error("サイズ超過。別の画像をお試しください。")
            else: ws_media.append_row([str(no), uploaded_file.name, enc]); st.success("完了"); st.rerun()
    match_photos = [r for r in ws_media.get_all_records() if str(r.get('match_no')) == str(no)]
    if match_photos:
        cols = st.columns(3)
        for idx, item in enumerate(match_photos):
            with cols[idx % 3]: 
                st.image(base64.b64decode(item['base64_data']), use_container_width=True)
                if st.button("削除", key=f"del_{idx}"):
                    cell=ws_media.find(item['base64_data']); ws_media.delete_rows(cell.row); st.rerun()

# 結果入力
elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no; st.title("📝 試合結果入力")
    if st.button("← 一覧に戻る"): st.session_state.selected_no = None; sync_state_to_storage(); st.rerun()
    client = get_gspread_client(); sh = client.open_by_url(SPREADSHEET_URL)
    try: ws_res = sh.worksheet("results")
    except: ws_res = sh.add_worksheet(title="results", rows="100", cols="2"); ws_res.append_row(["key", "data"])
    res_raw = ws_res.acell("A2").value; all_results = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"; curr = all_results.get(rk, {"score": " - ", "scorers": [], "result": ""})
        c_res = curr.get("result", "")
        h_txt = f"第 {i} 試合" + (f" （{c_res} {curr['score']}）" if c_res else "")
        with st.expander(h_txt, expanded=(i==1)):
            r_opts = ["勝ち", "負け", "引き分け"]; r_idx = r_opts.index(c_res) if c_res in r_opts else 0
            res_val = st.radio("結果", r_opts, index=r_idx, key=f"rad_{rk}")
            s_p = curr["score"].split("-"); l_v = s_p[0].strip() if len(s_p)>0 else ""; r_v = s_p[1].strip() if len(s_p)>1 else ""
            cl, cr = st.columns(2)
            with cl: nl = st.text_input("自", value=l_v, key=f"l_{rk}")
            with cr: nr = st.text_input("相手", value=r_v, key=f"r_{rk}")
            sc_in = st.text_area("得点者", value=", ".join(curr.get("scorers",[])), key=f"txt_{rk}")
            if st.button("保存", key=f"btn_{rk}"):
                with st.spinner("保存中..."):
                    all_results[rk] = {"score": f"{nl}-{nr}", "scorers": [s.strip() for s in sc_in.split(",") if s.strip()], "result": res_val}
                    ws_res.update_acell("A2", json.dumps(all_results, ensure_ascii=False))
                    st.success(f"第 {i} 試合の結果を保存しました。")
                    sync_state_to_storage(); time.sleep(0.5); st.rerun()

# 一覧
else:
    st.title(f"⚽ KSC試合管理一覧 ({st.session_state.selected_year}年度)")
    
    col_nav1, col_nav2 = st.columns([1, 5])
    with col_nav1:
        if st.button("📅 年度を変更"):
            st.session_state.selected_year = None
            st.session_state.df_list = pd.DataFrame()
            sync_state_to_storage()
            st.rerun()

    if st.session_state.action_no:
        st.warning("選択した試合に対する操作を選択してください")
        ca1, ca2, ca3 = st.columns(3)
        with ca1:
            if st.button("修正", use_container_width=True): 
                st.session_state.edit_no = st.session_state.action_no
                st.session_state.action_no = None
                sync_state_to_storage()
                st.rerun()
        with ca2:
            if st.button("削除", use_container_width=True):
                client = get_gspread_client()
                sh = client.open_by_url(SPREADSHEET_URL)
                ws_name = get_worksheet_name()
                
                # 修正：指定したシートがない場合は最初のシートを参照する（エラー回避）
                try: ws = sh.worksheet(ws_name)
                except: ws = sh.get_worksheet(0)
                
                cell = ws.find(str(st.session_state.action_no))
                if cell:
                    ws.delete_rows(cell.row)
                    st.success("削除が完了しました。")
                
                st.session_state.action_no = None
                st.session_state.df_list = load_data()
                st.rerun()
        with ca3:
            if st.button("キャンセル", use_container_width=True): 
                st.session_state.action_no = None
                st.rerun()
    
    if st.button("➕ 新規試合登録", use_container_width=True): st.session_state.page = "create"; st.session_state.edit_no = None; sync_state_to_storage(); st.rerun()
    
    c1, c2 = st.columns([2, 1])
    with c1: sq = st.text_input("🔍 検索")
    with c2: cf = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])

    if st.session_state.df_list.empty:
        st.session_state.df_list = load_data()
        
    df = st.session_state.df_list.copy()
    if cf != "すべて": df = df[df["カテゴリー"] == cf]
    if sq: df = df[df.apply(lambda r: sq.lower() in r.astype(str).str.lower().values, axis=1)]
    
    if not df.empty:
        disp = ['選択', '結果入力', '対戦相手', '対戦場所', '日時', 'カテゴリー', '試合分類', '競技分類', '写真管理']
        edf = st.data_editor(df[['No'] + disp].reset_index(drop=True), hide_index=True, 
            column_config={
                "No": None,
                "選択": st.column_config.CheckboxColumn("選択", width="small"), 
                "結果入力": st.column_config.CheckboxColumn("結果入力", width="small"), 
                "写真管理": st.column_config.CheckboxColumn("写真管理", width="small"), 
                "日時": st.column_config.DateColumn("日時", format="YYYY-MM-DD")
            }, 
            use_container_width=True, key="main_editor")
        
        for i in range(len(edf)):
            row = edf.iloc[i]
            if row.get("選択"): st.session_state.action_no = int(row["No"]); st.rerun()
            if row.get("結果入力"): st.session_state.selected_no = int(row["No"]); sync_state_to_storage(); st.rerun()
            if row.get("写真管理"): st.session_state.media_no = int(row["No"]); sync_state_to_storage(); st.rerun()
    else:
        st.info("登録されている試合はありません。")

    st.markdown("---")
    if st.button("🖨️ 一覧を印刷用表示"):
        if not df.empty:
            p_df = df[disp]
            components.html(f"<html><body>{p_df.to_html(index=False)}<script>window.print()</script></body></html>", height=0)
