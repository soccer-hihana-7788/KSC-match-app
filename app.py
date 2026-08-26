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
    
    /* サイドバーの背景色調整 */
    [data-testid="stSidebar"] {
        background-color: #FFEDD5 !important;
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
        border: 1px solid #FED7AA; 
        padding: 10px;
    }

    /* 端末のダークモード設定等に影響されず、文字色を暗いグレーに固定する（白飛び防止） */
    .stApp, .stMarkdown, .stText, p, span, label, h1, h2, h3, h4, h5, h6, li {
        color: #333333 !important;
    }

    /* 入力フィールドやドロップダウンの背景色と文字色を強制的にライトテーマ化 */
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    div[data-baseweb="textarea"] > div,
    div[data-testid="stDateInput"] > div {
        background-color: #FFFFFF !important;
        color: #333333 !important;
    }
    
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea,
    div[data-baseweb="select"] div {
        color: #333333 !important;
    }

    /* Expanderのタイトルや内容の文字色 */
    div[data-testid="stExpander"] summary {
        color: #333333 !important;
    }

    /* 全てのボタンの基本形状をモダンに */
    div.stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
        border: 1px solid #FDBA74 !important; 
        color: #431407 !important; 
    }
    
    div.stButton > button:hover {
        background-color: #FFEDD5 !important;
        border-color: #F97316 !important;
    }

    /* Primary属性を持つ主要アクションボタンのスタイル */
    div.stButton > button[kind="primary"] {
        background-color: #F97316 !important; 
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

    /* メトリック（ダッシュボードのサマリー数字）のスタイル調整 */
    div[data-testid="stMetricValue"] {
        color: #EA580C !important;
        font-weight: 700 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. ブラウザストレージによる状態保持と自動復旧 ---
def sync_state_to_storage():
    if st.session_state.get("authenticated"):
        page = st.session_state.get("page", "list")
        year = st.session_state.get("selected_year", "2025")
        
        def to_py_int(val):
            if val is not None:
                try:
                    return int(val)
                except Exception:
                    return None
            return None

        s_no = to_py_int(st.session_state.get("selected_no"))
        m_no = to_py_int(st.session_state.get("media_no"))
        e_no = to_py_int(st.session_state.get("edit_no"))

        state_data = {
            "auth": True,
            "auth_time": str(st.session_state.get("auth_time", "")),
            "page": str(page),
            "selected_no": s_no,
            "media_no": m_no,
            "edit_no": e_no,
            "selected_year": str(year)
        }
        js_code = f"localStorage.setItem('ksc_state', '{json.dumps(state_data, default=str)}');"
        components.html(f"<script>{js_code}</script>", height=0)

        st.query_params["ksc_auth"] = "true"
        st.query_params["auth_time"] = str(st.session_state.get("auth_time", ""))
        st.query_params["p"] = str(page)
        st.query_params["s_year"] = str(year)
        
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

if "initialized" not in st.session_state:
    st.session_state.initialized = True
    params = st.query_params
    if params.get("ksc_auth") == "true" and params.get("auth_time"):
        try:
            stored_time = datetime.fromisoformat(params.get("auth_time"))
            if datetime.now() - stored_time < timedelta(hours=6):
                st.session_state.authenticated = True
                st.session_state.auth_time = stored_time
                
                st.session_state.page = "list"
                st.session_state.selected_year = "2025"
                st.session_state.selected_no = None
                st.session_state.media_no = None
                st.session_state.edit_no = None
                
                def safe_int(val):
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
                    st.session_state.page = "list"
                    st.session_state.selected_no = None
                    st.session_state.media_no = None
                    st.session_state.edit_no = None
        except Exception:
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
「いいね！」のお言葉、ありがとうございます！ダッシュボードでの可視化機能を一覧の最上部に追加すれば、登録状況がひと目で把握できてかなり使いやすくなりそうですね。

ただ、大変申し訳ありません。私の方でこれまでの会話の文脈がリセットされてしまっており、ベースとなるシステムや「一覧」の仕様（どのようなドキュメントやコードを作成していたか）が現在参照できない状態です。

お手数ですが、**ベースとなる「一覧」の仕様や、前回作成した内容**をもう一度貼り付けて（または教えて）いただけますでしょうか？ 

情報をいただき次第、ご要望のダッシュボード要素（全体の試合数、サッカー/フットサルの内訳、U-〇別の内訳など）を組み込んだ修正案をすぐに作成いたします！
