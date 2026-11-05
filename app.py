import os
import io
import json
import sqlite3
import datetime
import urllib.parse
import requests
import streamlit as st
import pandas as pd
import numpy as np
from PIL import Image

# --- Page Configuration ---
st.set_page_config(
    page_title="Sabry Vision - Neonatal Nursery System",
    page_icon="👶",
    layout="wide"
)

# --- Permanent Medical Disclaimer & Privacy Notice ---
st.warning("⚠️ **MEDICAL DISCLAIMER:** Decision-support tool only. Verify all calculations and decisions against the official AAP 2022 nomogram (Kemper et al., Pediatrics) and the treating physician's clinical judgment.")
st.info("🔒 **Privacy & Data Notice:** Crib card photos and patient details sent to AI services may contain identifiable information. Ensure compliance with your hospital's institutional data privacy and HIPAA/GDPR policies.")

# --- Database & Persistence Setup (SQLite) ---
DB_NAME = "neonatal_nursery.db"

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            mrn TEXT PRIMARY KEY,
            baby_name TEXT,
            ga_weeks REAL,
            birth_weight REAL,
            birth_datetime TEXT,
            gender TEXT,
            mother_bg TEXT,
            baby_bg TEXT,
            dat TEXT,
            risk_factors TEXT,
            status TEXT,
            discharge_notes TEXT,
            management_plan TEXT,
            next_labs_due TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS labs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT,
            time_hours REAL,
            datetime_str TEXT,
            test_name TEXT,
            test_value REAL,
            unit TEXT,
            FOREIGN KEY (mrn) REFERENCES patients (mrn)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            action TEXT,
            patient_mrn TEXT,
            role TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def log_audit(action: str, patient_mrn: str, role: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_log (timestamp, action, patient_mrn, role) VALUES (?, ?, ?, ?)",
        (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, patient_mrn, role)
    )
    conn.commit()
    conn.close()

# --- Authentication & Role-Based Access Control (UNTOUCHED AS REQUESTED) ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "role" not in st.session_state:
        st.session_state.role = None
    if "login_time" not in st.session_state:
        st.session_state.login_time = None

    if st.session_state.authenticated:
        if st.session_state.role == "admin":
            return True
        elif st.session_state.role == "user":
            if st.session_state.login_time:
                delta = datetime.datetime.now() - st.session_state.login_time
                if delta.days <= 30:
                    return True
                else:
                    st.warning("⚠️ User session expired (30 days limit). Please login again.")
                    st.session_state.authenticated = False

    st.markdown("<h2 style='text-align: center;'>🔐 Login - Sabry Vision Neonatal System</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username (admin / user)")
            password = st.text_input("Password", type="password")
            submit_btn = st.form_submit_button("Login")
            
            if submit_btn:
                if username == "admin" and password == "admin":
                    st.session_state.authenticated = True
                    st.session_state.role = "admin"
                    st.session_state.login_time = datetime.datetime.now()
                    st.success("Logged in as Admin (Unlimited duration)")
                    st.rerun()
                elif username == "user" and password == "user":
                    st.session_state.authenticated = True
                    st.session_state.role = "user"
                    st.session_state.login_time = datetime.datetime.now()
                    st.success("Logged in as User (Valid for 30 days)")
                    st.rerun()
                else:
                    st.error("❌ Incorrect username or password.")
    return False

if not check_password():
    st.stop()

with st.sidebar:
    st.write(f"👤 Current User: **{st.session_state.role.upper()}**")
    if st.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.role = None
        st.rerun()
    st.markdown("---")

# --- API Key Configuration ---
try:
    api_key_env = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
except Exception:
    api_key_env = os.getenv("GEMINI_API_KEY", None)

api_key = st.sidebar.text_input("Gemini API Key", value=api_key_env or "", type="password")

# --- Direct REST API Helper for Gemini ---
import base64

def call_gemini_rest(prompt: str, image_bytes=None, mime_type="image/jpeg") -> str:
    if not api_key:
        return "Error: Gemini API Key is missing."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    parts = [{"text": prompt}]
    if image_bytes:
        encoded = base64.b64encode(image_bytes).decode('utf-8')
        parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
    payload = {"contents": [{"parts": parts}]}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        res_json = response.json()
        if "candidates" in res_json:
            return res_json["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"API Error: {res_json.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Request Exception: {str(e)}"

def extract_medical_data_with_gemini(image_bytes=None, audio_bytes=None, mime_type="image/jpeg") -> dict:
    prompt = """
    Extract neonatal clinical data from this crib card or lab image/audio. Return ONLY valid JSON with these exact keys:
    mrn, baby_name, gestational_age_weeks, birth_weight_kg, mother_blood_group, baby_blood_group, dat_status, risk_factors, total_bilirubin, bilirubin_unit, tsh, crp, management_plan.
    No extra text, just raw JSON.
    """
    file_bytes = image_bytes if image_bytes else audio_bytes
    res_text = call_gemini_rest(prompt, image_bytes=file_bytes, mime_type=mime_type)
    cleaned = res_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:-3].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:-3].strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return {"baby_name": "Extracted via AI", "management_plan": res_text}

def get_ai_clinical_summary(p, sbr, hrs, risk) -> str:
    prompt = (f"Neonatal case: GA {p['ga_weeks']} weeks, birth weight "
              f"{p['birth_weight']}, latest total bilirubin {sbr} umol/L at "
              f"{hrs} hours, risk factors: {risk}, DAT {p['dat']}, mother "
              f"{p['blood_group_mother']}, baby {p['blood_group_baby']}. "
              "Give a brief clinical summary and considerations per AAP 2022. "
              "Do not give definitive orders or doses.")
    return call_gemini_rest(prompt)

# --- Clinical Logic Helper Functions ---
def parse_blood_group(bg_str: str) -> tuple:
    if not bg_str or not isinstance(bg_str, str):
        return None, None
    s = bg_str.strip().upper()
    abo, rh = None, None
    if "AB" in s:
        abo = "AB"
    elif "A" in s:
        abo = "A"
    elif "B" in s:
        abo = "B"
    elif "O" in s:
        abo = "O"
    if "NEG" in s or "-" in s:
        rh = "NEG"
    elif "POS" in s or "+" in s:
        rh = "POS"
    return abo, rh

def check_incompatibilities(mother_bg: str, baby_bg: str, dat: str) -> tuple:
    m_abo, m_rh = parse_blood_group(mother_bg)
    b_abo, b_rh = parse_blood_group(baby_bg)
    abo_risk = (m_abo == "O" and b_abo in ["A", "B", "AB"]) if (m_abo and b_abo) else False
    rh_risk = (m_rh == "NEG" and b_rh == "POS") if (m_rh and b_rh) else False
    dat_pos = dat is not None and ("POS" in dat.strip().upper())
    return abo_risk, rh_risk, dat_pos

def convert_to_umol(val: float, unit: str) -> float:
    if unit and "mg" in unit.lower():
        return val * 17.1
    return val

def compute_hours_of_life(birth_dt_str: str, current_dt_str: str) -> float:
    try:
        dt_birth = None
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]:
            try:
                dt_birth = datetime.datetime.strptime(birth_dt_str.replace('H', '').strip(), fmt)
                break
            except Exception:
                continue
        if not dt_birth:
            dt_birth = datetime.datetime.now() - datetime.timedelta(days=1)
            
        dt_current = datetime.datetime.now()
        if current_dt_str:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]:
                try:
                    dt_current = datetime.datetime.strptime(current_dt_str.replace('H', '').strip(), fmt)
                    break
                except Exception:
                    continue
        diff = dt_current - dt_birth
        return max(0.0, diff.total_seconds() / 3600.0)
    except Exception:
        return 24.0

def get_aap_thresholds(ga_weeks: float, hours: float, has_risk: bool) -> tuple:
    base_photo = 170.0 if has_risk else 220.0
    base_exchange = 300.0 if has_risk else 380.0
    if hours < 24:
        factor = 0.65 + (hours / 24.0) * 0.35
    else:
        factor = 1.0 + min(0.5, (hours - 24) / 150.0)
    ga_factor = 1.0 if ga_weeks >= 38 else (0.85 if ga_weeks >= 35 else 0.75)
    photo = base_photo * factor * ga_factor
    exchange = base_exchange * factor * ga_factor
    return round(photo, 1), round(exchange, 1)

def calculate_rate_of_rise(labs_df: pd.DataFrame) -> float:
    if labs_df is None or labs_df.empty:
        return 0.0
    bili_df = labs_df[labs_df["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])]
    if len(bili_df) < 2:
        return 0.0
    sorted_df = bili_df.sort_values("time_hours")
    r1 = sorted_df.iloc[-2]
    r2 = sorted_df.iloc[-1]
    dh = r2["time_hours"] - r1["time_hours"]
    if dh <= 0:
        return 0.0
    dv = r2["test_value"] - r1["test_value"]
    return round(dv / dh, 2)

# --- Main App Layout ---
current_date_str = datetime.date.today().strftime("%Y-%m-%d")
st.title(f"👶 Sabry Vision - Neonatal Nursery Census ({current_date_str})")

# Fetch patients from DB
conn = get_db_connection()
patients_cursor = conn.cursor()
patients_cursor.execute("SELECT * FROM patients")
db_patients = patients_cursor.fetchall()
conn.close()

patients_dict = {}
for p in db_patients:
    conn = get_db_connection()
    labs_df = pd.read_sql("SELECT * FROM labs WHERE mrn = ? ORDER BY time_hours", conn, params=(p["mrn"],))
    conn.close()
    
    patients_dict[p["mrn"]] = {
        "baby_name": p["baby_name"],
        "mrn": p["mrn"],
        "gestational_age": f"{p['ga_weeks']} weeks",
        "ga_weeks": p["ga_weeks"],
        "birth_weight": f"{p['birth_weight']} kg",
        "birth_weight_val": p["birth_weight"],
        "birth_date": p["birth_datetime"],
        "gender": p["gender"],
        "blood_group_mother": p["mother_bg"],
        "blood_group_baby": p["baby_bg"],
        "dat": p["dat"],
        "risk_factors": p["risk_factors"],
        "status": p["status"],
        "discharge_notes": p["discharge_notes"],
        "management_plan": p["management_plan"],
        "next_labs_due": p["next_labs_due"],
        "labs": labs_df
    }

# --- Main Page: Add New Newborn with AI Input Hub ---
st.markdown("---")
with st.expander("➕ **Add New Newborn (AI Powered Input Hub)**", expanded=len(patients_dict) == 0):
    st.markdown("إدخال مولود جديد بالذكاء الاصطناعي (الكاميرا، رفع الصور، الميكروفون، أو الإدخال اليدوي):")
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        new_mrn = st.text_input("Baby MRN (رقم الملف الطبي)")
        new_name = st.text_input("Baby / Mother Name (اسم الطفل / الأم)")
    
    input_method = st.radio("اختر طريقة إدخال البيانات:", ("Manual / Direct (يدوي)", "Open Camera (فتح الكاميرا)", "Upload Photo (رفع صورة الكريب كارد)", "Open Microphone (تسجيل صوتي)"))
    
    extracted_json = None
    if input_method == "Open Camera (فتح الكاميرا)":
        cam_file = st.camera_input("Take Crib Card / Document Photo")
        if cam_file and st.button("Extract Data with AI 🚀"):
            with st.spinner("جاري تحليل الصورة بالذكاء الاصطناعي..."):
                extracted_json = extract_medical_data_with_gemini(image_bytes=cam_file.getvalue())
    elif input_method == "Upload Photo (رفع صورة الكريب كارد)":
        up_img_file = st.file_uploader("Upload Crib Card / Lab Report", type=["jpg", "jpeg", "png"])
        if up_img_file and st.button("Extract Data with AI 🚀"):
            with st.spinner("جاري قراءة الصورة..."):
                extracted_json = extract_medical_data_with_gemini(image_bytes=up_img_file.getvalue())
    elif input_method == "Open Microphone (تسجيل صوتي)":
        audio_file = st.audio_input("Record Patient Clinical Details")
        if audio_file and st.button("Extract Data via Voice AI 🚀"):
            with st.spinner("جاري تفريغ وتحليل الصوت..."):
                extracted_json = extract_medical_data_with_gemini(audio_bytes=audio_file.read(), mime_type=audio_file.type if hasattr(audio_file, 'type') else "audio/wav")

    if extracted_json and isinstance(extracted_json, dict):
        st.success("✅ تم استخراج البيانات بنجاح! راجعها وقم بالتأكيد:")
        rev_mrn = st.text_input("Review MRN", value=str(extracted_json.get("mrn", new_mrn)))
        rev_name = st.text_input("Review Name", value=str(extracted_json.get("baby_name", new_name)))
        rev_ga = st.number_input("Review GA (weeks)", value=float(extracted_json.get("gestational_age_weeks", 38.0)))
        rev_wt = st.number_input("Review Weight (kg)", value=float(extracted_json.get("birth_weight_kg", 3.0)))
        
        if st.button("Confirm and Save New Patient to Census"):
            conn = get_db_connection()
            conn.execute(
                "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rev_mrn or "UNKNOWN", rev_name or "Newborn", rev_ga, rev_wt, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Unknown", str(extracted_json.get("mother_blood_group", "Unknown")), str(extracted_json.get("baby_blood_group", "Unknown")), str(extracted_json.get("dat_status", "Negative")), str(extracted_json.get("risk_factors", "None")), "In Nursery", "", str(extracted_json.get("management_plan", "Routine care")), "Pending")
            )
            conn.commit()
            conn.close()
            st.success("تم حفظ المريض بنجاح!")
            st.rerun()

    if input_method == "Manual / Direct (يدوي)" and st.button("Create Newborn Record"):
        if new_mrn:
            conn = get_db_connection()
            conn.execute(
                "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_mrn, new_name or "Newborn", 38.0, 3.0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Unknown", "Unknown", "Unknown", "Negative", "None", "In Nursery", "", "Initial observation", "Pending")
            )
            conn.commit()
            conn.close()
            st.success("تم إضافة المريض بنجاح!")
            st.rerun()

st.markdown("---")

# --- Census Overview Table at Top ---
st.subheader("📊 Nursery Census Overview")
conn = get_db_connection()
census_df = pd.read_sql("SELECT mrn, baby_name, ga_weeks, birth_weight, status FROM patients", conn)
conn.close()
if not census_df.empty:
    st.dataframe(census_df, use_container_width=True)
else:
    st.info("لا توجد حالات مسجلة حالياً في الحضانة. استخدم خانة (Add New Newborn) أعلاه لإضافة أول مولود.")
    st.stop()

# Patient Selection Sidebar
st.sidebar.header("🏥 Active Patient Selection")
patient_keys = list(patients_dict.keys())
selected_mrn = st.sidebar.selectbox(
    "Select Active Patient:",
    patient_keys,
    format_func=lambda x: f"{patients_dict[x]['baby_name']} (MRN: {x}) [{patients_dict[x]['status']}]"
)

current_patient = patients_dict[selected_mrn]

# --- Main Interface Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Crib Card & Clinical Profile", 
    "📈 Bilirubin Trend & AAP Charts", 
    "🧪 Laboratory Results", 
    "💡 Clinical Assessment & Risk", 
    "📤 Shift Handover (WhatsApp)"
])

with tab1:
    st.subheader(f"Patient Profile: {current_patient['baby_name']}")
    
    status_options = ["In Nursery", "Discharged", "Transferred to NICU"]
    try:
        default_status_idx = status_options.index(current_patient["status"])
    except ValueError:
        default_status_idx = 0
        
    col_st1, col_st2, col_st3 = st.columns(3)
    with col_st1:
        new_status = st.selectbox("Patient Status", status_options, index=default_status_idx)
    with col_st2:
        discharge_notes = st.text_input("Follow-up Date / Transfer Notes", current_patient["discharge_notes"])
    with col_st3:
        if st.button("Update Status"):
            conn = get_db_connection()
            conn.execute("UPDATE patients SET status = ?, discharge_notes = ? WHERE mrn = ?", (new_status, discharge_notes, current_patient["mrn"]))
            conn.commit()
            conn.close()
            st.success("Status updated!")
            st.rerun()

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("MRN", current_patient["mrn"])
        st.metric("Birth Date/Time", current_patient["birth_date"])
        st.metric("Gender", current_patient["gender"])
    with c2:
        st.metric("Gestational Age", current_patient["gestational_age"])
        st.metric("Birth Weight", current_patient["birth_weight"])
        st.metric("Mother Blood Group", current_patient["blood_group_mother"])
    with c3:
        st.metric("Baby Blood Group", current_patient["blood_group_baby"])
        st.metric("DAT Test", current_patient["dat"])
        st.metric("Risk Factors", current_patient["risk_factors"])

    st.markdown("---")
    st.info(f"📝 **Current Management Plan:**\n\n{current_patient['management_plan']}")
    st.warning(f"⏰ **Next Labs Due:**\n\n{current_patient['next_labs_due']}")

with tab2:
    st.subheader("📈 Bilirubin Trend & AAP 2022 Guidelines Charts")
    
    mom_bg = current_patient["blood_group_mother"]
    baby_bg = current_patient["blood_group_baby"]
    dat_res = current_patient["dat"]
    
    is_abo, is_rh, is_dat = check_incompatibilities(mom_bg, baby_bg, dat_res)
    has_risk_factors = (current_patient.get("ga_weeks", 38.0) < 38.0) or is_abo or is_rh or is_dat
    
    st.markdown(f"""
    **Automated Risk Evaluation:**
    * **DAT Status:** {dat_res} ➔ {'⚠️ POSITIVE (Risk)' if is_dat else 'Negative'}
    * **ABO Incompatibility:** {'⚠️ Detected (Mother O, Baby A/B/AB)' if is_abo else 'None'}
    * **Rh Incompatibility:** {'⚠️ Detected (Mother Rh-, Baby Rh+)' if is_rh else 'None'}
    * **Overall AAP Risk Category:** **{'WITH RISK FACTORS' if has_risk_factors else 'NO RISK FACTORS'}**
    """)

    with st.expander("➕ Add New SBR Result"):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            hours_life = st.number_input("Hours of Life (HOF)", min_value=0.0, max_value=720.0, value=compute_hours_of_life(current_patient["birth_date"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        with col_b:
            sbr_val = st.number_input("Total Bilirubin Result", min_value=0.0, max_value=800.0, value=150.0)
        with col_c:
            sbr_unit = st.selectbox("Unit", ["umol/L", "mg/dL"])
        
        if st.button("Add SBR Reading & Plot Trend"):
            val_umol = convert_to_umol(sbr_val, sbr_unit)
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, time_hours, datetime_str, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)",
                         (current_patient["mrn"], hours_life, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "SBR", val_umol, "umol/L"))
            conn.commit()
            conn.close()
            st.success("SBR Reading added successfully!")
            st.rerun()

    labs_df = current_patient["labs"]
    if not labs_df.empty:
        bili_trend_df = labs_df[labs_df["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])]
        if not bili_trend_df.empty:
            ror = calculate_rate_of_rise(labs_df)
            if ror > 8.5:
                st.error(f"⚠️ **Rapid Rate of Rise Warning:** Bilirubin is rising at {ror} µmol/L per hour!")
            else:
                st.info(f"📊 Current rate of rise: {ror} µmol/L per hour.")
                
            chart_data = bili_trend_df.set_index("time_hours")[["test_value"]]
            st.line_chart(chart_data)
        else:
            st.info("لا توجد قراءات سابقة للبيليروبين مرسومة حتى الآن. أضف قراءة من الأعلى.")
            
        st.markdown("### سجل الفحوصات الكامل")
        st.dataframe(labs_df, use_container_width=True)

with tab3:
    st.subheader("🧪 Comprehensive Laboratory Results & Custom Labs")
    st.markdown("إدخال وتتبع كافة التحاليل المخبرية بدقة (CBC, Chemistry, Renal, Electrolytes, TSH, Free T4, وغيرها).")
    
    with st.expander("➕ Add Any Laboratory Test (CBC, TSH, Sodium, Urea, etc.)"):
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            test_category = st.selectbox("Test Category", ["SBR (Bilirubin)", "CBC", "Renal Profile / Electrolytes", "Thyroid (Cord/Baby TSH & T4)", "Bone Profile", "Other Custom Lab"])
        with col_t2:
            if test_category == "SBR (Bilirubin)":
                custom_test_name = "SBR"
            elif test_category == "Thyroid (Cord/Baby TSH & T4)":
                custom_test_name = st.selectbox("Select Test", ["Cord TSH", "Baby TSH", "Free T4", "Total T4"])
            elif test_category == "Renal Profile / Electrolytes":
                custom_test_name = st.selectbox("Select Test", ["Sodium (Na)", "Potassium (K)", "Chloride (Cl)", "Urea", "Creatinine"])
            elif test_category == "CBC":
                custom_test_name = st.selectbox("Select Test", ["Hemoglobin (Hb)", "WBC", "Platelets", "CRP", "Neutrophils"])
            else:
                custom_test_name = st.text_input("Enter Lab Name (e.g. Calcium, Albumin, AST, ALT)")
        with col_t3:
            test_val = st.number_input("Test Value", value=0.0)
            test_unit = st.text_input("Unit (e.g. mmol/L, mg/dL, mIU/L)", value="")

        test_hours = st.number_input("Hours of Life at Lab Draw", min_value=0.0, max_value=720.0, value=compute_hours_of_life(current_patient["birth_date"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        if st.button("Save Lab Result"):
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, time_hours, datetime_str, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)",
                         (current_patient["mrn"], test_hours, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), custom_test_name, test_val, test_unit))
            conn.commit()
            conn.close()
            st.success(f"تم حفظ تحليل ({custom_test_name}) بنجاح!")
            st.rerun()
            
    st.markdown("### جميع التحاليل والنتائج المسجلة للمريض:")
    if not current_patient["labs"].empty:
        st.dataframe(current_patient["labs"], use_container_width=True)
    else:
        st.info("لا توجد تحاليل مسجلة لهذا المريض بعد.")

with tab4:
    st.subheader("💡 Clinical Zone Assessment & Recommendations")
    
    labs_df = current_patient["labs"]
    bili_labs = labs_df[labs_df["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])] if not labs_df.empty else pd.DataFrame()
    
    if not bili_labs.empty:
        latest_sbr = bili_labs.iloc[-1]["test_value"]
        latest_hrs = bili_labs.iloc[-1]["time_hours"]
        
        photo_thresh, exchange_thresh = get_aap_thresholds(current_patient.get("ga_weeks", 38.0), latest_hrs, has_risk_factors)
        
        zone_status = "Within Safe Zone / Below Phototherapy"
        if latest_sbr >= exchange_thresh:
            zone_status = "🚨 Exchange Transfusion Zone!"
        elif latest_sbr >= photo_thresh + 40:
            zone_status = "⚠️ Intensive Phototherapy Zone"
        elif latest_sbr >= photo_thresh:
            zone_status = "⚡ Phototherapy Zone"
            
        st.error(f"**Current Zone Status (at {latest_hrs} hours):** {zone_status} (SBR: {round(latest_sbr, 1)} µmol/L | Threshold: {photo_thresh} µmol/L)")
    else:
        st.info("No SBR results recorded yet.")
        
    if api_key and not bili_labs.empty and st.button("Generate AI Clinical Summary"):
        with st.spinner("Generating expert clinical assessment..."):
            latest_val = bili_labs.iloc[-1]["test_value"]
            latest_h = bili_labs.iloc[-1]["time_hours"]
            risk_desc = current_patient["risk_factors"]
            summary_text = get_ai_clinical_summary(current_patient, latest_val, latest_h, risk_desc)
            st.success("AI Summary Generated:")
            st.write(summary_text)

with tab5:
    st.subheader("📤 Shift Handover (Ready for WhatsApp)")
    
    latest_sbr_txt = "N/A"
    if not current_patient["labs"].empty:
        bili_row = current_patient["labs"][current_patient["labs"]["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])]
        if not bili_row.empty:
            r = bili_row.iloc[-1]
            latest_sbr_txt = f"{r['test_value']} {r['unit']} at {r['time_hours']} hours"
        
    handover_text = f"""📋 NEONATAL NURSERY SHIFT HANDOVER
Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
Patient: {current_patient['baby_name']} (MRN: {current_patient['mrn']})
Status: {current_patient['status']}
GA: {current_patient['gestational_age']} | Weight: {current_patient['birth_weight']}
Risk Factors: {current_patient['risk_factors']} | DAT: {current_patient['dat']}
Latest SBR: {latest_sbr_txt}

Management Plan:
{current_patient['management_plan']}

Next Labs Due:
{current_patient['next_labs_due']}"""

    st.text_area("Copy handover text:", handover_text, height=220)
    wa_url = f"https://wa.me/?text={urllib.parse.quote(handover_text)}"
    st.markdown(f"[📲 Send Handover via WhatsApp]({wa_url})", unsafe_allow_html=True)
