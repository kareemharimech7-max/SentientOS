import streamlit as st
from supabase import create_client, Client, ClientOptions
from groq import Groq
from dotenv import load_dotenv
import os
import json
import time
import tempfile
from pypdf import PdfReader

# ==========================================
# 🧿 CONFIGURATION
# ==========================================
APP_NAME = "Sentient OS"
LOGO_FILE = "logo.jpg" 
# 👇 LIVE URL
PRODUCTION_URL = "https://sentientos.streamlit.app" 

st.set_page_config(page_title=APP_NAME, page_icon="🧠", layout="wide")
load_dotenv()

# ==========================================
# 💾 SYSTEM-LEVEL STORAGE (The "Nuclear" Fix)
# ==========================================
# We save the secret keys to the system's /tmp folder.
# This survives the Streamlit Cloud reboot during login.
class SystemFileStorage:
    def __init__(self):
        # Use the system temp directory which persists longer
        self.filename = os.path.join(tempfile.gettempdir(), "supabase_auth_lock.json")

    def set_item(self, key, value):
        try:
            data = {}
            if os.path.exists(self.filename):
                with open(self.filename, 'r') as f:
                    content = f.read()
                    if content: data = json.loads(content)
            data[key] = value
            with open(self.filename, 'w') as f:
                json.dump(data, f)
        except: pass

    def get_item(self, key):
        if not os.path.exists(self.filename): return None
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
            return data.get(key)
        except: return None

    def remove_item(self, key):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f: data = json.load(f)
                if key in data:
                    del data[key]
                    with open(self.filename, 'w') as f: json.dump(data, f)
            except: pass

# ==========================================
# 🔑 INIT CLIENTS
# ==========================================
# We DO NOT cache the client itself, only the logic to create it.
def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key: return None
    # Use SystemFileStorage to fix the redirect loop
    return create_client(url, key, options=ClientOptions(storage=SystemFileStorage()))

supabase = get_supabase()

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
# 🔄 AUTHENTICATION HANDLER
# ==========================================

# 1. HANDLE RETURN FROM GITHUB
if "code" in st.query_params:
    try:
        # The Verifier should now be found in /tmp
        session = supabase.auth.exchange_code_for_session({"auth_code": st.query_params["code"]})
        
        # Save tokens to Session State (Memory)
        st.session_state["access_token"] = session.access_token
        st.session_state["refresh_token"] = session.refresh_token
        
        # Clear URL and Rerun
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        # If this fails, it usually means the code is stale. 
        # We clear it to prevent the "Error Loop".
        st.query_params.clear()

# 2. RESTORE SESSION
if "access_token" in st.session_state:
    try:
        supabase.auth.set_session(
            st.session_state["access_token"], 
            st.session_state["refresh_token"]
        )
    except:
        # Token expired
        del st.session_state["access_token"]
        st.rerun()

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

def create_chat(email):
    res = supabase.table("chat_sessions").insert({"email": email, "title": "New Sequence"}).execute()
    return res.data[0]['chat_id'] if res.data else None

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

def get_msgs(chat_id):
    try: return supabase.table("chat_messages").select("*").eq("chat_id", chat_id).order("created_at", desc=False).execute().data
    except: return []

def delete_chat(chat_id):
    supabase.table("chat_sessions").delete().eq("chat_id", chat_id).execute()

def process_uploaded_file(uploaded_file):
    try:
        if uploaded_file.type == "application/pdf":
            reader = PdfReader(uploaded_file)
            text = ""
            for page in reader.pages: text += page.extract_text() + "\n"
            return text
        else: return uploaded_file.getvalue().decode("utf-8")
    except: return "Error reading file."

# ==========================================
# 🎨 UI STYLING
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #02040a; color: #e0e0e0; }
    .auth-card { background: #0a0a0f; border: 1px solid #333; border-radius: 12px; padding: 30px; text-align: center; }
    .feature-box { background: #0f1016; border: 1px solid #1f1f2e; padding: 20px; border-radius: 12px; text-align: center; height: 100%; }
    .feature-title { font-weight: bold; color: #00d4ff; margin-bottom: 5px; font-size: 16px; }
    .feature-desc { color: #888; font-size: 14px; }
    div.stButton > button { background-color: #1a1a1a; color: white; border: 1px solid #333; width: 100%; border-radius: 6px; }
    div.stButton > button:hover { border-color: #00d4ff; color: #00d4ff; }
    .stSidebar { background-color: #000; border-right: 1px solid #111; }
    .upgrade-box { border: 1px solid #a855f7; background: linear-gradient(135deg, #2e1065 0%, #000 100%); padding: 15px; border-radius: 8px; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🚀 APP LOGIC
# ==========================================

# CHECK SESSION
try: 
    session = supabase.auth.get_session()
except: 
    session = None

# 1. LANDING PAGE
if not session:
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, use_container_width=True)
        else: st.header(APP_NAME)
    
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.markdown("<div class='feature-box'><span style='font-size:30px'>⚡</span><div class='feature-title'>VELOCITY</div><div class='feature-desc'>Real-time inference.</div></div>", unsafe_allow_html=True)
    with c2: st.markdown("<div class='feature-box'><span style='font-size:30px'>🧠</span><div class='feature-title'>REASONING</div><div class='feature-desc'>Chain-of-thought logic.</div></div>", unsafe_allow_html=True)
    with c3: st.markdown("<div class='feature-box'><span style='font-size:30px'>🔐</span><div class='feature-title'>SECURE</div><div class='feature-desc'>Encrypted memory.</div></div>", unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    _, center_col, _ = st.columns([1, 1.2, 1])
    with center_col:
        st.markdown("<div class='auth-card'>", unsafe_allow_html=True)
        st.subheader("INITIALIZE LINK")
        
        tab_gh, tab_email = st.tabs(["GITHUB", "EMAIL"])
        with tab_gh:
            st.write("")
            if st.button("▶ ACCESS VIA GITHUB", type="primary", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_oauth({ "provider": "github", "options": { "redirectTo": PRODUCTION_URL } })
                    st.link_button("CLICK TO CONNECT", res.url, type="primary", use_container_width=True)
                except: st.error("Link Error")
        
        with tab_email:
            st.write("")
            email_input = st.text_input("Operator Email")
            if st.button("▶ SEND MAGIC LINK", use_container_width=True):
                if email_input:
                    try:
                        supabase.auth.sign_in_with_otp({"email": email_input, "options": {"email_redirect_to": PRODUCTION_URL}})
                        st.success("CHECK INBOX")
                    except: st.error("Failed")
        st.markdown("</div>", unsafe_allow_html=True)

# 2. LOGGED IN APP
else:
    user = session.user
    email = user.email
    sync_user(email)
    user_premium = is_premium(email)

    active_model = "llama-3.3-70b-versatile" if user_premium else "llama-3.1-8b-instant"
    display_name = "SENTIENT PRO" if user_premium else "SENTIENT CORE"

    with st.sidebar:
        if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, use_container_width=True)
        st.caption(f"OPERATOR: {email}")
        if user_premium: st.markdown(f"<span style='color:#a855f7'>● {display_name}</span>", unsafe_allow_html=True)
        else: st.markdown(f"<span style='color:#00d4ff'>● {display_name}</span>", unsafe_allow_html=True)
        
        st.divider()
        st.markdown("### NEURAL INGESTION")
        uploaded_file = st.file_uploader("Upload Data", type=['txt', 'py', 'js', 'pdf'], label_visibility="collapsed")
        
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
            st.markdown(f"<div class='upgrade-box'><b>UPGRADE SYSTEM</b><br><span style='font-size:12px; color:#e9d5ff'>Unlock 70B Model</span></div>", unsafe_allow_html=True)
            st.link_button("PURCHASE ($10)", f"https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business={PAYPAL_EMAIL}&item_name=SentientPro&amount=10.00", use_container_width=True)
        
        if st.button("TERMINATE LINK"):
            supabase.auth.sign_out()
            if "access_token" in st.session_state: del st.session_state["access_token"]
            st.rerun()

    # CHAT
    if "chat" not in st.session_state or not st.session_state.chat:
        if chats: st.session_state.chat = chats[0]['chat_id']
        else: 
            new_id = create_chat(email)
            st.session_state.chat = new_id
            st.rerun()
    chat_id = st.session_state.chat

    # FILE HANDLING
    if uploaded_file and "last_uploaded" not in st.session_state:
        st.session_state.last_uploaded = uploaded_file.name
        content = process_uploaded_file(uploaded_file)
        update_chat_title(chat_id, f"Data: {uploaded_file.name}")
        save_msg(chat_id, "user", f"Uploaded: {uploaded_file.name}", email)
        
        with st.spinner("ANALYZING..."):
            sys = f"You are {APP_NAME}."
            api_msgs = [{"role": "system", "content": sys}, {"role": "user", "content": f"Analyze this file:\n{content}"}]
            try:
                resp = groq_client.chat.completions.create(model=active_model, messages=api_msgs)
                save_msg(chat_id, "assistant", resp.choices[0].message.content, email)
                st.rerun()
            except: pass
            
    if not uploaded_file and "last_uploaded" in st.session_state: del st.session_state.last_uploaded

    # HEADER
    c1, c2 = st.columns([6,1])
    c1.subheader(f"SYSTEM: {display_name}")
    if c2.button("✖", help="Purge"):
        delete_chat(chat_id)
        st.session_state.chat = None
        st.rerun()

    # MESSAGES
    msgs = get_msgs(chat_id)
    for m in msgs:
        with st.chat_message(m['role']):
            content = m['content']
            if "<thinking>" in content:
                parts = content.split("</thinking>")
                with st.status("Analytic Process", state="complete", expanded=False):
                    st.code(parts[0].replace("<thinking>", "").strip(), language="text")
                st.markdown(parts[1])
            else: st.markdown(content)
            
            if m['role'] == "assistant":
                st.download_button("⬇ DOWNLOAD", content, f"log_{m['created_at'][:10]}.md", "text/markdown", key=m['msg_id'])

    # CORTEX ACCELERATORS
    st.markdown("### CORTEX ACCELERATORS")
    ac1, ac2, ac3, ac4 = st.columns(4)
    auto_prompt = None
    if ac1.button("🔍 DEBUG"): auto_prompt = "Find bugs in previous code."
    if ac2.button("🛡️ AUDIT"): auto_prompt = "Security audit."
    if ac3.button("🏗️ ARCHITECT"): auto_prompt = "Design system architecture."
    if ac4.button("📝 DOCS"): auto_prompt = "Write documentation."

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
