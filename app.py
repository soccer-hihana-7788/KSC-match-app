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
    /* 削除ボタン用の赤色スタイル（ポップアップ内） */
    div[data-testid="stPopover"] div.stButton > button {
        background-color: #c0392b !important;
        color: white !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ブラウザストレージによる状態保持 ---
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
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    ws_name = get_worksheet_name()
    
    try:
        ws = sh.worksheet(ws_name)
        all_values = ws.get_all_values()
    except:
        # シート作成時に行数を1000に増やしてエラーを予防
        ws = sh.add_worksheet(title=ws_name, rows="1000", cols=str(len(SHEET_COLUMNS)))
        ws.update("A1", [SHEET_COLUMNS])
        all_values = [SHEET_COLUMNS]
            
    if not all_values or len(all_values) < 2:
        return pd.DataFrame(columns=['選択', '結果入力'] + SHEET_COLUMNS + ['写真管理'])

    header = all_values[0]
    valid_rows = [r for r in all_values[1:] if len(r) > 4 and r[4].strip() != ""]
    df = pd.DataFrame(valid_rows, columns=header)
    
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
            client = get_gspread_client()
            sh = client.open_by_url(SPREADSHEET_URL)
            ws_name = get_worksheet_name()
            ws = sh.worksheet(ws_name)
            
            # APIError対策: 行数が足りない場合は自動拡張
            if ws.row_count < 100:
                ws.add_rows(500)

            no_vals = ws.col_values(1)
            if target_no:
                cell = ws.find(str(target_no))
                if not cell: return None
                target_row = cell.row
                new_no = target_no
            else:
                last_idx = 0
                for i, val in enumerate(no_vals):
                    if val.strip() != "": last_idx = i + 1
                existing_nos = [int(v) for v in no_vals[1:] if v.strip().isdigit()]
                new_no = max(existing_nos + [0]) + 1
                target_row = last_idx + 1
            
            row = []
            for col in SHEET_COLUMNS:
                if col == "No": val = new_no
                elif col == "試合場所": val = data_dict.get("対戦場所", "")
                else: val = data_dict.get(col, "")
                row.append(str(val.isoformat() if isinstance(val, (date, datetime)) else val))
            
            ws.update(f"A{target_row}", [row])
            return new_no
        except Exception as e:
            if attempt == 2: st.error(f"保存エラー: {e}"); return None
            time.sleep(1)

# --- 4. 状態管理 ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "selected_year" not in st.session_state: st.session_state.selected_year = None
if 'df_list' not in st.session_state: st.session_state.df_list = pd.DataFrame()
if 'page' not in st.session_state: st.session_state.page = "list"
if 'selected_no' not in st.session_state: st.session_state.selected_no = None
if 'media_no' not in st.session_state: st.session_state.media_no = None
if 'action_no' not in st.session_state: st.session_state.action_no = None
if 'edit_no' not in st.session_state: st.session_state.edit_no = None

# ログイン
if not st.session_state.authenticated:
    st.title("⚽ KSCログイン")
    u = st.text_input("ID")
    p = st.text_input("PASS", type="password")
    if st.button("ログイン"):
        if u == st.secrets["LOGIN_ID"] and p == st.secrets["LOGIN_PASS"]:
            st.session_state.authenticated = True
            st.session_state.auth_time = datetime.now()
            sync_state_to_storage()
            st.rerun()
    st.stop()

# 年度選択画面
if st.session_state.selected_year is None:
    st.title("📅 年度選択")
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    worksheets = sh.worksheets()
    existing_years = sorted([ws.title.replace("list_", "") for ws in worksheets if ws.title.startswith("list_")])

    tabs = st.tabs([f"{y}年度" for y in existing_years])
    for i, y in enumerate(existing_years):
        with tabs[i]:
            if st.button(f"{y}年度を開く", key=f"y_{y}", use_container_width=True):
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
                st.rerun()

    with st.popover("🗑️ 年度削除", use_container_width=True):
        st.write("削除する年度を選択してください。")
        del_tabs = st.tabs([f"{y}年度" for y in existing_years])
        for i, y in enumerate(existing_years):
            with del_tabs[i]:
                if st.button(f"{y}年度を削除OK", key=f"del_{y}", use_container_width=True):
                    try:
                        sh.del_worksheet(sh.worksheet(f"list_{y}"))
                        st.rerun()
                    except Exception as e:
                        st.error(f"エラー: {e}")
    st.stop()

# 修正・新規登録
if st.session_state.page == "create" or st.session_state.edit_no is not None:
    is_edit = st.session_state.edit_no is not None
    st.title(f"📝 {st.session_state.selected_year}年度 試合情報の" + ("修正" if is_edit else "新規登録"))
    
    default_vals = {"カテゴリー":"U12", "日時":date.today(), "競技分類":"サッカー", "対戦相手":"", "対戦場所":"", "試合分類":"", "備考":""}
    if is_edit:
        target_rows = st.session_state.df_list[st.session_state.df_list["No"] == st.session_state.edit_no]
        if not target_rows.empty:
            row = target_rows.iloc[0]
            default_vals.update({"カテゴリー":row["カテゴリー"], "日時":row["日時"], "競技分類":row["競技分類"], "対戦相手":row["対戦相手"], "対戦場所":row["対戦場所"], "試合分類":row["試合分類"], "備考":row["備考"]})
    
    if st.button("← 戻る"):
        st.session_state.page = "list"
        st.session_state.edit_no = None
        st.rerun()

    with st.form("edit_form"):
        c_cat = st.selectbox("カテゴリー", ["U8", "U9", "U10", "U11", "U12"], index=["U8", "U9", "U10", "U11", "U12"].index(default_vals["カテゴリー"]))
        c_date = st.date_input("日時", value=default_vals["日時"])
        c_type = st.selectbox("競技分類", ["サッカー", "フットサル"], index=0 if default_vals["競技分類"]=="サッカー" else 1)
        c_opp = st.text_input("対戦相手", value=default_vals["対戦相手"])
        c_loc = st.text_input("対戦場所", value=default_vals["対戦場所"])
        c_class = st.text_input("試合分類", value=default_vals["試合分類"])
        c_memo = st.text_area("備考", value=default_vals["備考"])
        if st.form_submit_button("登録"):
            update_or_add_row({"カテゴリー": c_cat, "日時": c_date, "競技分類": c_type, "対戦相手": c_opp, "対戦場所": c_loc, "試合分類": c_class, "備考": c_memo}, target_no=st.session_state.edit_no)
            st.session_state.page = "list"
            st.session_state.edit_no = None
            st.session_state.df_list = load_data()
            st.rerun()

# 結果入力
elif st.session_state.selected_no is not None:
    no = st.session_state.selected_no
    st.title("📝 試合結果入力")
    if st.button("← 一覧に戻る"):
        st.session_state.selected_no = None
        st.rerun()
    
    client = get_gspread_client()
    sh = client.open_by_url(SPREADSHEET_URL)
    try:
        ws_res = sh.worksheet("results")
    except:
        ws_res = sh.add_worksheet(title="results", rows="1000", cols="2")
        ws_res.append_row(["key", "data"])
    
    res_raw = ws_res.acell("A2").value
    all_results = json.loads(res_raw) if res_raw else {}
    
    for i in range(1, 11):
        rk = f"res_{no}_{i}"
        curr = all_results.get(rk, {"score": " - ", "scorers": [], "result": "", "memo": ""})
        with st.expander(f"第 {i} 試合", expanded=(i==1)):
            res_val = st.radio("結果", ["勝ち", "負け", "引き分け"], index=0, key=f"rad_{rk}")
            s_p = curr["score"].split("-")
            l_v = s_p[0].strip() if len(s_p)>0 else ""
            r_v = s_p[1].strip() if len(s_p)>1 else ""
            
            # SyntaxError修正: with文と処理を別々の行に分割
            cl, cr = st.columns(2)
            with cl:
                nl = st.text_input("自", value=l_v, key=f"l_{rk}")
            with cr:
                nr = st.text_input("相手", value=r_v, key=f"r_{rk}")
                
            sc_in = st.text_area("得点者", value=", ".join(curr.get("scorers",[])), key=f"txt_{rk}")
            res_memo = st.text_area("備考", value=curr.get("memo", ""), key=f"memo_{rk}")
            if st.button("保存", key=f"btn_{rk}"):
                all_results[rk] = {"score": f"{nl}-{nr}", "scorers": [s.strip() for s in sc_in.split(",") if s.strip()], "result": res_val, "memo": res_memo}
                ws_res.update("A2", [[json.dumps(all_results, ensure_ascii=False)]])
                st.success("保存完了")

# 一覧
else:
    st.title(f"⚽ {st.session_state.selected_year}年度 試合一覧")
    if st.button("📅 年度を変更"):
        st.session_state.selected_year = None
        st.rerun()

    if st.button("➕ 新規試合登録", use_container_width=True):
        st.session_state.page = "create"
        st.rerun()

    c1, c2 = st.columns([2, 1])
    # SyntaxError修正: with文と処理を別々の行に分割
    with c1:
        sq = st.text_input("🔍 検索")
    with c2:
        cf = st.selectbox("📅 絞り込み", ["すべて", "U8", "U9", "U10", "U11", "U12"])

    df = st.session_state.df_list
    if not df.empty:
        edf = st.data_editor(df, hide_index=True, use_container_width=True, key="main_editor")
