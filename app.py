import streamlit as st
from supabase import create_client, Client, ClientOptions
from groq import Groq
from dotenv import load_dotenv
import os
import time
from pypdf import PdfReader

# ==========================================
# 🧿 CONFIGURATION
# ==========================================
APP_NAME = "Sentient OS"
LOGO_FILE = "logo.jpg" 
PRODUCTION_URL = "https://sentientos.streamlit.app" 

st.set_page_config(page_title=APP_NAME, page_icon="🧠", layout="wide")
load_dotenv()

# ==========================================
# 🎨 UI STYLING
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #02040a; color: #e0e0e0; }
    .feature-box {
        background: #0a0a0f; border: 1px solid #1f1f2e; padding: 20px;
        border-radius: 12px; text-align: center; height: 100%;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    }
    .feature-icon { font-size: 30px; margin-bottom: 10px; display: block; }
    .feature-title { font-weight: bold; color: #00d4ff; margin-bottom: 5px; font-size: 16px; text-transform: uppercase; }
    .feature-desc { color: #888; font-size: 14px; }
    div.stButton > button {
        background-color: #0f1016; color: #00d4ff; border: 1px solid #00d4ff;
        width: 100%; border-radius: 6px; font-weight: bold; transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        background-color: #00d4ff; color: #000; box-shadow: 0 0 15px rgba(0, 212, 255, 0.4);
    }
    .stSidebar { background-color: #050508; border-right: 1px solid #111; }
    .upgrade-box { 
        border: 1px solid #a855f7; 
        background: linear-gradient(135deg, #2e1065 0%, #000 100%); 
        padding: 15px; border-radius: 8px; margin-bottom: 20px; 
    }
    section[data-testid="stFileUploader"] {
        background-color: #0a0a0f; border: 1px dashed #333; border-radius: 8px; padding: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔑 INIT CLIENTS
# ==========================================
# 1. Initialize Supabase (No caching, unique per user)
def init_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key: return None
    return create_client(url, key)

if "supabase_client" not in st.session_state:
    st.session_state.supabase_client = init_supabase()

supabase = st.session_state.supabase_client

# 2. Initialize Groq (Cached is fine for API key)
@st.cache_resource
def init_groq():
    key = os.getenv("GROQ_API_KEY")
    if not key: return None
    return Groq(api_key=key)

groq_client = init_groq()
PAYPAL_EMAIL = os.getenv("PAYPAL_EMAIL")

if not supabase:
    st.error("❌ Critical: Missing Supabase Keys")
    st.stop()

# ==========================================
# 🔄 AUTH CALLBACK & PERSISTENCE (THE FIX)
# ==========================================

# 1. Handle the redirect from GitHub
if "code" in st.query_params:
    try:
        res = supabase.auth.exchange_code_for_session({"auth_code": st.query_params["code"]})
        # SAVE SESSION TO STATE SO IT SURVIVES RELOAD
        st.session_state.user_session = res.session
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Login Error: {e}")
        st.query_params.clear()

# 2. Restore Session from State if available
if "user_session" in st.session_state:
    try:
        # Manually set the session on the client
        supabase.auth.set_session(
            st.session_state.user_session.access_token, 
            st.session_state.user_session.refresh_token
        )
    except:
        # If session expired, clear it
        del st.session_state.user_session

# ==========================================
# ☁️ DATABASE FUNCTIONS
# ==========================================
def sync_user(email):
    try:
        res = supabase.table("profiles").select("*").eq("email", email).execute()
        if not res.data: supabase.table("profiles").insert({"email": email, "is_premium": False}).execute()
    except: pass

def is_premium(email):
    try:
        res = supabase.table("profiles").select("is_premium").eq("email", email).single().execute()
        return res.data.get("is_premium", False)
    except: return False

def create_chat(email, title="New Sequence"):
    res = supabase.table("chat_sessions").insert({"email": email, "title": title}).execute()
    return res.data[0]['chat_id'] if res.data else None

def update_chat_title(chat_id, new_title):
    supabase.table("chat_sessions").update({"title": new_title}).eq("chat_id", chat_id).execute()

def get_chats(email):
    try: return supabase.table("chat_sessions").select("*").eq("email", email).order("created_at", desc=True).execute().data
    except: return []

def save_msg(chat_id, role, content, email_fallback=None):
    try:
        supabase.table("chat_messages").insert({"chat_id": chat_id, "role": role, "content": content}).execute()
    except Exception as e:
        if "23503" in str(e) and email_fallback:
            supabase.table("chat_sessions").insert({"chat_id": chat_id, "email": email_fallback, "title": "Restored Sequence"}).execute()
            supabase.table("chat_messages").insert({"chat_id": chat_id, "role": role, "content": content}).execute()
        else:
            print(f"Save Error: {e}")

def get_msgs(chat_id):
    try: return supabase.table("chat_messages").select("*").eq("chat_id", chat_id).order("created_at", desc=False).execute().data
    except: return []

def delete_chat(chat_id):
    supabase.table("chat_sessions").delete().eq("chat_id", chat_id).execute()

# ==========================================
# 📂 FILE PROCESSING
# ==========================================
def process_uploaded_file(uploaded_file):
    try:
        if uploaded_file.type == "application/pdf":
            reader = PdfReader(uploaded_file)
            text = ""
            for page in reader.pages: text += page.extract_text() + "\n"
            return text
        else:
            return uploaded_file.getvalue().decode("utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

# ==========================================
# 🚀 APP LOGIC
# ==========================================
# Check if we have a valid session
session = supabase.auth.get_session()

# --- LANDING PAGE ---
if not session:
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, use_container_width=True)
        else: st.header(APP_NAME)
    
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown("<div class='feature-box'><span class='feature-icon'>⚡</span><div class='feature-title'>LPU™ VELOCITY</div><div class='feature-desc'>Real-time inference speeds.</div></div>", unsafe_allow_html=True)
    with c2: st.markdown("<div class='feature-box'><span class='feature-icon'>🧠</span><div class='feature-title'>70B REASONING</div><div class='feature-desc'>Chain-of-thought processing.</div></div>", unsafe_allow_html=True)
    with c3: st.markdown("<div class='feature-box'><span class='feature-icon'>☁️</span><div class='feature-title'>HIVE MEMORY</div><div class='feature-desc'>Cloud synchronization.</div></div>", unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    _, center_col, _ = st.columns([1, 1.5, 1])
    with center_col:
        st.markdown("<h3 style='text-align: center'>INITIALIZE LINK</h3>", unsafe_allow_html=True)
        tab_login, tab_reg = st.tabs(["LOGIN", "REGISTER"])
        with tab_login:
            try:
                res = supabase.auth.sign_in_with_oauth({ "provider": "github", "options": { "redirectTo": PRODUCTION_URL } })
                st.link_button("▶ ACCESS TERMINAL", res.url, type="primary", use_container_width=True)
            except: st.error("Link Failure")
        with tab_reg:
            try: st.link_button("▶ CREATE IDENTITY", res.url, type="secondary", use_container_width=True)
            except: pass

# --- APP INTERFACE ---
else:
    user = session.user
    email = user.email
    sync_user(email)
    user_premium = is_premium(email)

    NAME_FREE, NAME_PRO = "SENTIENT CORE", "SENTIENT PRO"
    active_model = "llama-3.3-70b-versatile" if user_premium else "llama-3.1-8b-instant"
    display_name = NAME_PRO if user_premium else NAME_FREE

    # SIDEBAR
    with st.sidebar:
        if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, use_container_width=True)
        st.caption(f"OPERATOR: {email}")
        
        if user_premium: st.markdown(f"<span style='color:#a855f7'>● {NAME_PRO}</span>", unsafe_allow_html=True)
        else: st.markdown(f"<span style='color:#00d4ff'>● {NAME_FREE}</span>", unsafe_allow_html=True)
        st.divider()

        # NEURAL INGESTION
        st.markdown("### NEURAL INGESTION")
        uploaded_file = st.file_uploader("Upload Data Matrix", type=['txt', 'py', 'js', 'pdf', 'md', 'csv'], label_visibility="collapsed")
        
        st.divider()
        if st.button("➕ New Sequence", use_container_width=True):
            st.session_state.chat = create_chat(email)
            st.rerun()
            
        st.subheader("MEMORY")
        chats = get_chats(email)
        for c in chats:
            if st.button(f"▪ {c['title']}", key=c['chat_id'], use_container_width=True):
                st.session_state.chat = c['chat_id']
                st.rerun()
        
        st.divider()
        if not user_premium:
            st.markdown(f"<div class='upgrade-box'><b>UPGRADE TO {NAME_PRO}</b><br><span style='font-size:12px; color:#e9d5ff'>• 70B Model<br>• Unlimited Context</span></div>", unsafe_allow_html=True)
            st.link_button("PURCHASE LICENSE ($10)", f"https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business={PAYPAL_EMAIL}&item_name=SentientPro&amount=10.00", use_container_width=True)
        if st.button("TERMINATE LINK"):
            supabase.auth.sign_out()
            if "user_session" in st.session_state: del st.session_state.user_session
            st.rerun()

    # CHAT ID LOGIC
    if "chat" not in st.session_state or not st.session_state.chat:
        if chats: st.session_state.chat = chats[0]['chat_id']
        else: 
            new_id = create_chat(email)
            st.session_state.chat = new_id
            st.rerun()
    chat_id = st.session_state.chat

    # FILE UPLOAD HANDLER
    if uploaded_file and "last_uploaded" not in st.session_state:
        st.session_state.last_uploaded = uploaded_file.name
        file_content = process_uploaded_file(uploaded_file)
        new_title = f"Data: {uploaded_file.name}"
        update_chat_title(chat_id, new_title)
        
        save_msg(chat_id, "user", f"Uploaded File: {uploaded_file.name}", email)
        
        system_injection = f"The user has uploaded a file named '{uploaded_file.name}'. Detect the file type. Analyze it thoroughly and summarize its contents."
        full_prompt = f"### FILE CONTENT ({uploaded_file.name}):\n{file_content}\n\n### INSTRUCTION:\n{system_injection}"
        
        with st.spinner("ANALYZING DATA STREAM..."):
            sys = f"You are {APP_NAME}."
            api_msgs = [{"role": "system", "content": sys}, {"role": "user", "content": full_prompt}]
            try:
                resp = groq_client.chat.completions.create(model=active_model, messages=api_msgs)
                save_msg(chat_id, "assistant", resp.choices[0].message.content, email)
                st.rerun()
            except Exception as e: st.error(f"Failed: {e}")
            
    if not uploaded_file and "last_uploaded" in st.session_state:
        del st.session_state.last_uploaded

    # HEADER
    c1, c2 = st.columns([6,1])
    c1.subheader(f"SYSTEM: {display_name}")
    if c2.button("✖", help="Purge"):
        delete_chat(chat_id)
        st.session_state.chat = None
        st.rerun()

    # RENDER MESSAGES
    msgs = get_msgs(chat_id)
    for m in msgs:
        with st.chat_message(m['role']):
            content = m['content']
            if "<thinking>" in content:
                parts = content.split("</thinking>")
                with st.status("Analytic Process", state="complete", expanded=False):
                    st.code(parts[0].replace("<thinking>", "").strip(), language="text")
                st.markdown(parts[1])
            else:
                st.markdown(content)
            
            if m['role'] == "assistant":
                st.download_button(
                    label="⬇ DOWNLOAD",
                    data=content,
                    file_name=f"sentient_log_{m['created_at'][:10]}.md",
                    mime="text/markdown",
                    key=m['msg_id']
                )

    # CORTEX ACCELERATORS
    st.markdown("### CORTEX ACCELERATORS")
    ac1, ac2, ac3, ac4 = st.columns(4)
    auto_prompt = None
    if ac1.button("🔍 DEBUG CODE"): auto_prompt = "Review the previous code for bugs, security vulnerabilities, and logic errors. Suggest fixes."
    if ac2.button("🛡️ SECURITY AUDIT"): auto_prompt = "Perform a security audit on the discussion above. Identify risks."
    if ac3.button("🏗️ ARCHITECTURE"): auto_prompt = "Propose a scalable system architecture for this concept."
    if ac4.button("📝 GENERATE DOCS"): auto_prompt = "Generate professional documentation (README.md) for this."

    # INPUT
    user_input = st.chat_input("Enter command...")
    final_prompt = auto_prompt if auto_prompt else user_input

    if final_prompt:
        with st.chat_message("user"): st.markdown(final_prompt)
        save_msg(chat_id, "user", final_prompt, email)
        
        with st.chat_message("assistant"):
            sys = f"You are {APP_NAME}."
            if user_premium: sys += " You are on Sentient Pro. Use <thinking> tags for reasoning."
            else: sys += " You are on Sentient Core."
            
            api_msgs = [{"role": "system", "content": sys}]
            for m in msgs: api_msgs.append({"role": m['role'], "content": m['content']})
            api_msgs.append({"role": "user", "content": final_prompt})

            try:
                stream = groq_client.chat.completions.create(model=active_model, messages=api_msgs, stream=True)
                resp_box = st.empty()
                full_resp = ""
                for chunk in stream:
                    full_resp += chunk.choices[0].delta.content or ""
                    resp_box.markdown(full_resp + "█")
                resp_box.markdown(full_resp)
                save_msg(chat_id, "assistant", full_resp, email)
                time.sleep(0.1) 
                st.rerun()
            except Exception as e: st.error(f"Error: {e}")
