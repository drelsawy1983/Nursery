import os
import io
import json
import sqlite3
import datetime
import urllib.parse
import streamlit as st
import pandas as pd
import numpy as np
from PIL import Image
import google.generativeai as genai

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
    """Create and return a SQLite database connection with row factory."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """Initialize SQLite tables and insert seed patient data if empty."""
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
            total_bilirubin_umol REAL,
            unit_original TEXT,
            tsh REAL,
            crp REAL,
            other_tests TEXT,
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
    
    cursor.execute("SELECT COUNT(*) FROM patients WHERE mrn = ?", ("177000000808",))
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO patients (mrn, baby_name, ga_weeks, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            "177000000808",
            "Son of Rasmiah Obaid Alotaibi",
            35.43,
            2.005,
            "2026-10-30 19:20:00",
            "Male",
            "A POS",
            "O POS",
            "Negative",
            "Preterm (<38w), PPROM",
            "In Nursery",
            "",
            "Follow-up SBR q12h, continue routine phototherapy, monitor vitals.",
            "SBR & TSH in 12 hours"
        ))
        cursor.execute('''
            INSERT INTO labs (mrn, time_hours, datetime_str, total_bilirubin_umol, unit_original, tsh, crp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            "177000000808",
            33.67,
            "2026-11-01 05:00:00",
            144.8,
            "umol/L",
            14.87,
            1.9
        ))
        conn.commit()
    conn.close()

init_db()

def log_audit(action: str, patient_mrn: str, role: str) -> None:
    """Record an audit log entry."""
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

if api_key:
    genai.configure(api_key=api_key)

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
    if labs_df is None or len(labs_df) < 2:
        return 0.0
    valid_bili = labs_df[labs_df["Total_Bilirubin"].notnull() & (labs_df["Total_Bilirubin"] > 0)].sort_values("Time_Hours")
    if len(valid_bili) < 2:
        return 0.0
    r1 = valid_bili.iloc[-2]
    r2 = valid_bili.iloc[-1]
    dh = r2["Time_Hours"] - r1["Time_Hours"]
    if dh <= 0:
        return 0.0
    dv = r2["Total_Bilirubin"] - r1["Total_Bilirubin"]
    return round(dv / dh, 2)

# --- Gemini AI Extraction Function using GenerativeModel ---
def extract_medical_data_with_gemini(image_bytes=None, audio_bytes=None):
    if not api_key:
        st.error("API Key required.")
        return None
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = "Extract neonatal clinical data (MRN, baby_name, gestational_age_weeks, birth_weight_kg, mother_blood_group, baby_blood_group, dat_status, risk_factors, total_bilirubin, bilirubin_unit, tsh, crp, management_plan) as a JSON object."
        contents = [prompt]
        if image_bytes:
            contents.append({"mime_type": "image/jpeg", "data": image_bytes})
        
        response = model.generate_content(contents)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"Gemini Extraction Error: {str(e)}")
        return None

def get_ai_clinical_summary(p, sbr, hrs, risk):
    if not api_key:
        return "API Key required."
    prompt = (f"Neonatal case: GA {p['ga_weeks']} weeks, birth weight "
              f"{p['birth_weight']}, latest total bilirubin {sbr} umol/L at "
              f"{hrs} hours, risk factors: {risk}, DAT {p['dat']}, mother "
              f"{p['blood_group_mother']}, baby {p['blood_group_baby']}. "
              "Give a brief clinical summary and considerations per AAP 2022. "
              "Do not give definitive orders or doses.")
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        return model.generate_content(prompt).text
    except Exception as e:
        return f"AI error: {e}"

# --- Main App Layout ---
current_date_str = datetime.date.today().strftime("%Y-%m-%d")
st.title(f"👶 Sabry Vision - Neonatal Nursery Census ({current_date_str})")

st.subheader("📊 Nursery Census Overview")
conn = get_db_connection()
census_df = pd.read_sql("SELECT mrn, baby_name, ga_weeks, birth_weight, status FROM patients", conn)
conn.close()
if not census_df.empty:
    st.dataframe(census_df, use_container_width=True)

st.sidebar.header("🏥 Nursery Census Management")

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
    
    labs_df = labs_df.rename(columns={
        "time_hours": "Time_Hours", "datetime_str": "Date_Time",
        "total_bilirubin_umol": "Total_Bilirubin",
        "unit_original": "Unit_original", "tsh": "TSH", "crp": "CRP"
    })
    
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

with st.sidebar.expander("➕ Add New Newborn"):
    new_mrn = st.text_input("Baby MRN", key="new_mrn_input")
    new_name = st.text_input("Baby / Mother Name", key="new_name_input")
    input_method = st.selectbox("Input Method", ("Manual / Direct", "Camera / Scanner Capture", "Image Upload"))
    
    extracted_json = None
    if input_method == "Camera / Scanner Capture":
        cam_file = st.camera_input("Take Crib Card Photo")
        if cam_file and st.button("Extract with AI"):
            extracted_json = extract_medical_data_with_gemini(image_bytes=cam_file.getvalue())
    elif input_method == "Image Upload":
        up_img_file = st.file_uploader("Upload Crib Card / Lab Image", type=["jpg", "jpeg", "png"])
        if up_img_file and st.button("Extract with AI"):
            extracted_json = extract_medical_data_with_gemini(image_bytes=up_img_file.getvalue())

    if extracted_json:
        st.info("Review extracted data before saving:")
        rev_name = st.text_input("Review Name", value=extracted_json.get("baby_name", new_name))
        rev_ga = st.number_input("Review GA (weeks)", value=float(extracted_json.get("gestational_age_weeks", 38.0)))
        rev_wt = st.number_input("Review Weight (kg)", value=float(extracted_json.get("birth_weight_kg", 3.0)))
        if st.button("Confirm and Save New Patient"):
            conn = get_db_connection()
            conn.execute(
                "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_mrn or extracted_json.get("mrn", "UNKNOWN"), rev_name, rev_ga, rev_wt, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Unknown", extracted_json.get("mother_blood_group", "Unknown"), extracted_json.get("baby_blood_group", "Unknown"), extracted_json.get("dat_status", "Negative"), extracted_json.get("risk_factors", "None"), "In Nursery", "", extracted_json.get("management_plan", "Routine care"), "Pending")
            )
            conn.commit()
            conn.close()
            log_audit("ADD_PATIENT", new_mrn, st.session_state.role)
            st.success("Patient created successfully!")
            st.rerun()

    if input_method == "Manual / Direct" and st.button("Create Newborn Record"):
        if new_mrn:
            conn = get_db_connection()
            conn.execute(
                "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_mrn, new_name or "Newborn", 38.0, 3.0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Unknown", "Unknown", "Unknown", "Negative", "None", "In Nursery", "", "Initial observation", "Pending")
            )
            conn.commit()
            conn.close()
            log_audit("ADD_PATIENT", new_mrn, st.session_state.role)
            st.success("Newborn added!")
            st.rerun()

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
            log_audit("UPDATE_STATUS", current_patient["mrn"], st.session_state.role)
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
        
        if st.button("Add Reading & Plot Trend"):
            val_umol = convert_to_umol(sbr_val, sbr_unit)
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, time_hours, datetime_str, total_bilirubin_umol, unit_original) VALUES (?, ?, ?, ?, ?)",
                         (current_patient["mrn"], hours_life, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), val_umol, sbr_unit))
            conn.commit()
            conn.close()
            log_audit("ADD_LAB_SBR", current_patient["mrn"], st.session_state.role)
            st.success("Reading added successfully!")
            st.rerun()

    labs_df = current_patient["labs"]
    if not labs_df.empty:
        ror = calculate_rate_of_rise(labs_df)
        if ror > 8.5:
            st.error(f"⚠️ **Rapid Rate of Rise Warning:** Bilirubin is rising at {ror} µmol/L per hour!")
        else:
            st.info(f"📊 Current rate of rise: {ror} µmol/L per hour.")
            
        valid_bili_chart = labs_df[labs_df["Total_Bilirubin"].notnull() & (labs_df["Total_Bilirubin"] > 0)]
        if not valid_bili_chart.empty:
            chart_data = valid_bili_chart.set_index("Time_Hours")[["Total_Bilirubin"]]
            st.line_chart(chart_data)
        st.dataframe(labs_df, use_container_width=True)

with tab3:
    st.subheader("🧪 Comprehensive Laboratory Results")
    st.markdown("Flexible lab tracking for TSH, CBC, CRP, Electrolytes, Renal, and Liver functions.")
    
    with st.expander("➕ Add General Lab Test"):
        t_name = st.text_input("Test Name (e.g. TSH, CRP, Creatinine)")
        t_val = st.number_input("Value", value=0.0)
        t_unit = st.text_input("Unit", value="")
        if st.button("Save Lab Entry"):
            current_hof = compute_hours_of_life(current_patient["birth_date"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, time_hours, datetime_str, total_bilirubin_umol, unit_original, tsh, crp) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                         (current_patient["mrn"], current_hof, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), t_unit or "unit", t_val if 'tsh' in t_name.lower() else None, t_val if 'crp' in t_name.lower() else None))
            conn.commit()
            conn.close()
            st.success("Lab saved!")
            st.rerun()
            
    st.dataframe(current_patient["labs"], use_container_width=True)

with tab4:
    st.subheader("💡 Clinical Zone Assessment & Recommendations")
    
    labs_df = current_patient["labs"]
    valid_labs = labs_df[labs_df["Total_Bilirubin"].notnull() & (labs_df["Total_Bilirubin"] > 0)] if not labs_df.empty else pd.DataFrame()
    
    if not valid_labs.empty:
        latest_sbr = valid_labs.iloc[-1]["Total_Bilirubin"]
        latest_hrs = valid_labs.iloc[-1]["Time_Hours"]
        
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
        
    if api_key and not valid_labs.empty and st.button("Generate AI Clinical Summary"):
        with st.spinner("Generating expert clinical assessment..."):
            latest_val = valid_labs.iloc[-1]["Total_Bilirubin"]
            latest_h = valid_labs.iloc[-1]["Time_Hours"]
            risk_desc = current_patient["risk_factors"]
            summary_text = get_ai_clinical_summary(current_patient, latest_val, latest_h, risk_desc)
            st.success("AI Summary Generated:")
            st.write(summary_text)

with tab5:
    st.subheader("📤 Shift Handover (Ready for WhatsApp)")
    
    latest_sbr_txt = "N/A"
    if not current_patient["labs"].empty and len(current_patient["labs"][current_patient["labs"]["Total_Bilirubin"].notnull() & (current_patient["labs"]["Total_Bilirubin"] > 0)]) > 0:
        row = current_patient["labs"][current_patient["labs"]["Total_Bilirubin"].notnull() & (current_patient["labs"]["Total_Bilirubin"] > 0)].iloc[-1]
        latest_sbr_txt = f"{row['Total_Bilirubin']} {row['Unit_original']} at {row['Time_Hours']} hours"
        
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

