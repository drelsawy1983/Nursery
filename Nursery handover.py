import os
import io
import json
import sqlite3
import datetime
import streamlit as st
import pandas as pd
import numpy as np

# --- Page Configuration ---
st.set_page_config(
    page_title="Sabry Vision - Neonatal Nursery Digital Logbook",
    page_icon="👶",
    layout="wide"
)

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
            ga_weeks INTEGER,
            ga_days INTEGER,
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
            next_labs_due TEXT,
            primary_physician TEXT,
            diagnosis TEXT,
            delivery_type TEXT,
            cchd_status TEXT,
            red_reflex_status TEXT,
            hearing_status TEXT,
            vit_k_status TEXT,
            hepb_status TEXT,
            rsv_status TEXT,
            feeding_type TEXT
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
        CREATE TABLE IF NOT EXISTS custom_references (
            test_name TEXT PRIMARY KEY,
            min_val REAL,
            max_val REAL,
            unit TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            full_name TEXT,
            national_id TEXT
        )
    ''')
    # Default admin & user accounts
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, role, full_name, national_id) VALUES (?, ?, ?, ?, ?)",
                       ("admin", "admin", "admin", "System Administrator", "0000000000"))
    cursor.execute("SELECT * FROM users WHERE username = 'user'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, role, full_name, national_id) VALUES (?, ?, ?, ?, ?)",
                       ("user", "user", "user", "Nursery Staff User", "1111111111"))
    conn.commit()
    conn.close()

init_db()

# --- Legal Consent & Disclaimer State ---
if "consented" not in st.session_state:
    st.session_state.consented = False

if not st.session_state.consented:
    st.markdown("<h2 style='text-align: center; color: #cc0000;'>⚖️ LEGAL DISCLAIMER & TERMS OF USE</h2>", unsafe_allow_html=True)
    st.markdown("""
    <div style='background-color: #f9f9f9; padding: 20px; border-radius: 10px; border: 1px solid #ddd;'>
    <p><b>By accessing and using the Sabry Vision Neonatal Nursery Logbook System, you acknowledge and agree that this software is strictly a digital logbook and handover tool for administrative and census tracking. The application designer, developer, and owner bear <u>ABSOLUTELY NO LIABILITY OR LEGAL RESPONSIBILITY</u> for any medical decisions, diagnostic errors, treatment outcomes, or data breaches resulting from the use of this system.</b></p>
    <p><b>ALL RESPONSIBILITY RESTS SOLELY WITH THE USER.</b> The healthcare professional using this software is entirely responsible for verifying all clinical data, patient privacy compliance, treatment plans, and medical interventions. By clicking "I Agree", you waive any right to legal claims against the designer or owner of this application.</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("I Agree & Enter System (أوافق وأدخل النظام)"):
        st.session_state.consented = True
        st.rerun()
    st.stop()

# --- Authentication & Role-Based Access Control ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = None
    if "role" not in st.session_state:
        st.session_state.role = None

    if st.session_state.authenticated:
        return True

    st.markdown("<h2 style='text-align: center;'>🔐 Login - Sabry Vision Neonatal Logbook</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username_input = st.text_input("Username (admin / user)")
            password_input = st.text_input("Password", type="password")
            submit_btn = st.form_submit_button("Login")
            
            if submit_btn:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username_input, password_input))
                user = cursor.fetchone()
                conn.close()
                
                if user:
                    st.session_state.authenticated = True
                    st.session_state.username = user["username"]
                    st.session_state.role = user["role"]
                    st.success("Logged in successfully!")
                    st.rerun()
                else:
                    st.error("❌ Incorrect username or password.")
    return False

if not check_password():
    st.stop()

with st.sidebar:
    st.write(f"👤 User: **{st.session_state.username}** ({st.session_state.role.upper()})")
    if st.button("Logout", key="sidebar_logout_btn"):
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.role = None
        st.rerun()
    st.markdown("---")
    
    # Admin User Management Panel in Sidebar
    if st.session_state.role == "admin":
        with st.expander("👑 Admin User Management"):
            new_u = st.text_input("New Username", key="admin_new_u")
            new_p = st.text_input("New Password", type="password", key="admin_new_p")
            new_role = st.selectbox("Role", ["user", "admin"], key="admin_new_role")
            new_name = st.text_input("Full Name", key="admin_new_name")
            new_nid = st.text_input("National ID / Employee ID", key="admin_new_nid")
            
            if st.button("Create / Update User", key="admin_create_user_btn"):
                if new_u and new_p:
                    conn = get_db_connection()
                    conn.execute("INSERT OR REPLACE INTO users (username, password, role, full_name, national_id) VALUES (?, ?, ?, ?, ?)",
                                 (new_u, new_p, new_role, new_name, new_nid))
                    conn.commit()
                    conn.close()
                    st.success(f"User {new_u} saved successfully!")
                else:
                    st.error("Please enter username and password.")

# --- Helper Functions ---
def convert_to_umol(val: float, unit: str) -> float:
    if unit and "mg" in unit.lower():
        return val * 17.1
    return val

def compute_hours_of_life(birth_dt_str: str) -> float:
    try:
        dt_birth = None
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d"]:
            try:
                dt_birth = datetime.datetime.strptime(birth_dt_str.replace('H', '').strip(), fmt)
                break
            except Exception:
                continue
        if not dt_birth:
            dt_birth = datetime.datetime.now() - datetime.timedelta(days=1)
        diff = datetime.datetime.now() - dt_birth
        return max(0.0, diff.total_seconds() / 3600.0)
    except Exception:
        return 24.0

# --- Main App Layout ---
current_date_str = datetime.date.today().strftime("%Y-%m-%d")
st.title(f"👶 Sabry Vision - Neonatal Nursery Digital Logbook [{current_date_str}]")

# Mode Selector Dropdown in Main Interface
mode_option = st.selectbox("🎛️ Select Operation Mode (اختر وضع التشغيل)", ["Actual Nursery (الحالات الفعلية)", "Demo Test Patient (الوضع الافتراضي للتجربة)"], key="main_mode_selectbox")

if "Demo" in mode_option:
    conn = get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, ga_days, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due, primary_physician, diagnosis, delivery_type, cchd_status, red_reflex_status, hearing_status, vit_k_status, hepb_status, rsv_status, feeding_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000000", "SON OF ...", 35, 3, 2.005, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Male", "O POS", "A POS", "Positive", "Preterm, ABO Incompatibility", "Still in Nursery", "", "Phototherapy initiated, IV fluids", "SBR Q12H", "Dr. Ibrahim BAHLAK", "PRETERM, ABO INCOMPATIBILITY", "SVD", "Pass", "Pass", "Pending", "Given", "Given", "Not Given", "Regular Formula")
    )
    conn.execute("INSERT OR IGNORE INTO labs (mrn, time_hours, datetime_str, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)", ("000000", 24.0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "CRP", 1.9, "mg/L"))
    conn.execute("INSERT OR IGNORE INTO labs (mrn, time_hours, datetime_str, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)", ("000000", 53.0, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "SBR", 245.0, "umol/L"))
    conn.commit()
    conn.close()

# Fetch patients from DB based on mode
conn = get_db_connection()
if "Demo" in mode_option:
    patients_cursor = conn.cursor()
    patients_cursor.execute("SELECT * FROM patients WHERE mrn = '000000'")
else:
    patients_cursor = conn.cursor()
    patients_cursor.execute("SELECT * FROM patients WHERE mrn != '000000'")
db_patients = patients_cursor.fetchall()
conn.close()

patients_dict = {}
for p in db_patients:
    conn = get_db_connection()
    labs_df = pd.read_sql("SELECT * FROM labs WHERE mrn = ? ORDER BY time_hours ASC", conn, params=(p["mrn"],))
    conn.close()
    
    ga_w = p["ga_weeks"] if p["ga_weeks"] is not None else 35
    ga_d = p["ga_days"] if p["ga_days"] is not None else 3
    
    patients_dict[p["mrn"]] = {
        "baby_name": p["baby_name"],
        "mrn": p["mrn"],
        "gestational_age": f"{ga_w} Weeks + {ga_d} Days",
        "ga_weeks": ga_w,
        "ga_days": ga_d,
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
        "primary_physician": p["primary_physician"],
        "diagnosis": p["diagnosis"],
        "delivery_type": p["delivery_type"],
        "cchd_status": p["cchd_status"] if p["cchd_status"] else "Pending",
        "red_reflex_status": p["red_reflex_status"] if p["red_reflex_status"] else "Pending",
        "hearing_status": p["hearing_status"] if p["hearing_status"] else "Pending",
        "vit_k_status": p["vit_k_status"] if p["vit_k_status"] else "Given",
        "hepb_status": p["hepb_status"] if p["hepb_status"] else "Given",
        "rsv_status": p["rsv_status"] if p["rsv_status"] else "Not Given",
        "feeding_type": p["feeding_type"] if p["feeding_type"] else "Regular Formula",
        "labs": labs_df
    }

# --- Main Page: Add New Newborn (Manual Entry Hub) ---
st.markdown("---")
with st.expander("➕ **Add New Newborn (Manual Entry Hub)**", expanded=len(patients_dict) == 0):
    st.markdown("إدخال بيانات مولود جديد يدوياً بالكامل:")
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        new_mrn = st.text_input("Baby MRN", value="177000000808", key="main_new_mrn")
        new_name = st.text_input("Patient Full Name", value="SON OF RASMIAH OBAID ALOTAIBI", key="main_new_name")
        gender_val = st.selectbox("Gender", ["Male", "Female"], index=0, key="main_new_gender")
        
        st.markdown("Gestational Age (عمر الحمل)")
        col_ga1, col_ga2 = st.columns(2)
        with col_ga1:
            new_ga_w = st.number_input("Weeks", min_value=24, max_value=44, value=35, key="main_new_gaw")
        with col_ga2:
            new_ga_d = st.number_input("Days", min_value=0, max_value=6, value=3, key="main_new_gad")
            
    with col_input2:
        new_wt = st.number_input("Birth Weight (kg)", value=2.005, key="main_new_wt")
        
        consultant_options = [
            "Dr. Amany",
            "Dr. Hosny",
            "Dr. Ibrahim BAHLAK",
            "Dr. Mahmoud El-Naggar",
            "Dr. NEMER",
            "Dr. Al-Thubaiti",
            "Other"
        ]
        selected_cons = st.selectbox("Treating Consultant", consultant_options, index=2, key="main_new_cons")
        new_physician = st.text_input("Custom Consultant Name", value="DR IBRAHIM-0829", key="main_new_cname") if selected_cons == "Other" else selected_cons
        
        new_diagnosis = st.text_input("Diagnosis", value="PRETERM, SVD, AGA", key="main_new_diag")
        new_delivery = st.selectbox("Delivery Type", ["SVD", "CS", "BBA"], index=0, key="main_new_del")

    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        mother_bg_val = st.selectbox("Mother Blood Group", ["A POS", "A NEG", "B POS", "B NEG", "AB POS", "AB NEG", "O POS", "O NEG"], index=0, key="main_mbg")
    with col_b2:
        baby_bg_val = st.selectbox("Baby Blood Group", ["A POS", "A NEG", "B POS", "B NEG", "AB POS", "AB NEG", "O POS", "O NEG"], index=0, key="main_bbg")
    with col_b3:
        dat_val = st.selectbox("DAT Test", ["Negative", "Positive"], index=0, key="main_dat")

    st.markdown("### 🍼 Feeding Type (نوع التغذية)")
    new_feeding = st.selectbox("Feeding", ["Regular Formula", "AR Formula", "Exclusive Breastfeeding"], index=0, key="main_feed")

    st.markdown("### 💉 Medications & Vaccines Status")
    col_v1, col_v2, col_v3 = st.columns(3)
    with col_v1:
        new_vit_k = st.selectbox("Vitamin K", ["Given", "Not Given"], index=0, key="main_vitk")
    with col_v2:
        new_hepb = st.selectbox("Hepatitis B Vaccine", ["Given", "Not Given"], index=0, key="main_hepb")
    with col_v3:
        new_rsv = st.selectbox("RSV Vaccine / Prophylaxis", ["Given", "Not Given"], index=1, key="main_rsv")

    st.markdown("### 🔍 Neonatal Screening Tests")
    col_sc1, col_sc2, col_sc3 = st.columns(3)
    with col_sc1:
        new_cchd = st.selectbox("CCHD Screening", ["Pending", "Pass", "Fail"], index=0, key="main_cchd")
    with col_sc2:
        new_red_reflex = st.selectbox("Red Reflex Test", ["Pending", "Pass", "Fail"], index=0, key="main_red")
    with col_sc3:
        new_hearing = st.selectbox("Hearing Screening", ["Pending", "Pass", "Fail"], index=0, key="main_hearing")

    risk_input = st.text_input("Risk Factors", value="Preterm, PROM 63 hrs", key="main_risk")
    mgmt_plan = st.text_area("Management Plan / Medications", value="Cholecalciferol Vitamin D3 400 units oral Q24H for 30 days. Special formula milk Q2H.", key="main_mgmt")
    next_labs = st.text_input("Next Labs Due", value="SBR Q12H", key="main_nlabs")

    if st.button("Create Manual Newborn Record", key="main_create_pat_btn"):
        if new_mrn:
            conn = get_db_connection()
            conn.execute(
                "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, ga_days, birth_weight, birth_datetime, gender, mother_bg, baby_bg, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due, primary_physician, diagnosis, delivery_type, cchd_status, red_reflex_status, hearing_status, vit_k_status, hepb_status, rsv_status, feeding_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_mrn, new_name, new_ga_w, new_ga_d, new_wt, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), gender_val, mother_bg_val, baby_bg_val, dat_val, risk_input, "Still in Nursery", "", mgmt_plan, next_labs, new_physician, new_diagnosis, new_delivery, new_cchd, new_red_reflex, new_hearing, new_vit_k, new_hepb, new_rsv, new_feeding)
            )
            conn.commit()
            conn.close()
            st.success("تم إضافة المريض بنجاح!")
            st.rerun()

st.markdown("---")

# --- Census Overview Table & Quick Selection Cards ---
st.subheader("📊 Nursery Census Overview & Quick Patient Selection")
conn = get_db_connection()
census_df = pd.read_sql("SELECT mrn, baby_name, ga_weeks, ga_days, birth_weight, status, primary_physician FROM patients", conn)
conn.close()

if not census_df.empty:
    st.dataframe(census_df, use_container_width=True)
    
    st.markdown("### 🗂️ Quick Select Patient:")
    cols = st.columns(min(len(patients_dict), 4))
    for idx, (mrn_val, p_data) in enumerate(patients_dict.items()):
        col_idx = idx % 4
        with cols[col_idx]:
            if st.button(f"👶 {p_data['baby_name']}\nMRN: {mrn_val}\n[{p_data['status']}]", key=f"btn_pat_{mrn_val}"):
                st.session_state['active_mrn'] = mrn_val
else:
    st.info("لا توجد حالات مسجلة حالياً.")

default_mrn = list(patients_dict.keys())[0] if patients_dict else None
if 'active_mrn' not in st.session_state or st.session_state['active_mrn'] not in patients_dict:
    st.session_state['active_mrn'] = default_mrn

if not patients_dict:
    st.stop()

selected_mrn = st.sidebar.selectbox(
    "Select Active Patient:",
    list(patients_dict.keys()),
    index=list(patients_dict.keys()).index(st.session_state['active_mrn']) if st.session_state['active_mrn'] in patients_dict else 0,
    format_func=lambda x: f"{patients_dict[x]['baby_name']} (MRN: {x}) [{patients_dict[x]['status']}]",
    key="sidebar_active_patient_select"
)
st.session_state['active_mrn'] = selected_mrn
current_patient = patients_dict[selected_mrn]

st.markdown("---")
st.markdown(f"### 🩺 Active Patient Management: **{current_patient['baby_name']}** (MRN: {current_patient['mrn']})")

# --- Main Interface Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Crib Card & Clinical Profile", 
    "📈 Bilirubin Log & Trend Chart", 
    "🧪 Cumulative Labs & Comparison", 
    "💡 Clinical Summary", 
    "📤 Shift Handover (Secure Internal & Print)"
])

with tab1:
    st.subheader(f"Hospital Crib Card Format & Patient Editing: {current_patient['baby_name']}")
    
    with st.expander("✏️ Edit Patient Details, Feeding & Vaccines"):
        edit_name = st.text_input("Edit Patient Name", value=current_patient["baby_name"], key="tab1_edit_name")
        edit_diag = st.text_area("Edit Diagnosis", value=current_patient["diagnosis"], key="tab1_edit_diag")
        edit_mgmt = st.text_area("Edit Management Plan", value=current_patient["management_plan"], key="tab1_edit_mgmt")
        edit_labs = st.text_input("Edit Next Labs Due", value=current_patient["next_labs_due"], key="tab1_edit_labs")
        
        st.markdown("**Feeding Type:**")
        feed_opt = ["Regular Formula", "AR Formula", "Exclusive Breastfeeding"]
        edit_feeding = st.selectbox("Feeding", feed_opt, index=feed_opt.index(current_patient["feeding_type"]) if current_patient["feeding_type"] in feed_opt else 0, key="tab1_edit_feed")

        st.markdown("**Vaccines & Medications Status:**")
        v_opt = ["Given", "Not Given"]
        edit_vit_k = st.selectbox("Vitamin K", v_opt, index=v_opt.index(current_patient["vit_k_status"]) if current_patient["vit_k_status"] in v_opt else 0, key="tab1_edit_vitk")
        edit_hepb = st.selectbox("Hepatitis B Vaccine", v_opt, index=v_opt.index(current_patient["hepb_status"]) if current_patient["hepb_status"] in v_opt else 0, key="tab1_edit_hepb")
        edit_rsv = st.selectbox("RSV Vaccine / Prophylaxis", v_opt, index=v_opt.index(current_patient["rsv_status"]) if current_patient["rsv_status"] in v_opt else 1, key="tab1_edit_rsv")

        st.markdown("**Screening Tests Status:**")
        opt_list = ["Pending", "Pass", "Fail"]
        edit_cchd = st.selectbox("CCHD Status", opt_list, index=opt_list.index(current_patient["cchd_status"]) if current_patient["cchd_status"] in opt_list else 0, key="tab1_edit_cchd")
        edit_red = st.selectbox("Red Reflex Status", opt_list, index=opt_list.index(current_patient["red_reflex_status"]) if current_patient["red_reflex_status"] in opt_list else 0, key="tab1_edit_red")
        edit_hearing = st.selectbox("Hearing Screening Status", opt_list, index=opt_list.index(current_patient["hearing_status"]) if current_patient["hearing_status"] in opt_list else 0, key="tab1_edit_hearing")
        
        if st.button("Save Patient Updates", key="tab1_save_updates_btn"):
            conn = get_db_connection()
            conn.execute("UPDATE patients SET baby_name = ?, diagnosis = ?, management_plan = ?, next_labs_due = ?, cchd_status = ?, red_reflex_status = ?, hearing_status = ?, vit_k_status = ?, hepb_status = ?, rsv_status = ?, feeding_type = ? WHERE mrn = ?",
                         (edit_name, edit_diag, edit_mgmt, edit_labs, edit_cchd, edit_red, edit_hearing, edit_vit_k, edit_hepb, edit_rsv, edit_feeding, current_patient["mrn"]))
            conn.commit()
            conn.close()
            st.success("تم تحديث بيانات المريض بنجاح!")
            st.rerun()

    status_options = ["Still in Nursery", "Discharged", "Transferred to NICU"]
    try:
        default_status_idx = status_options.index(current_patient["status"])
    except ValueError:
        default_status_idx = 0
        
    col_st1, col_st2, col_st3 = st.columns(3)
    with col_st1:
        new_status = st.selectbox("Patient Status", status_options, index=default_status_idx, key="tab1_p_status")
    with col_st2:
        discharge_notes = st.text_input("Follow-up Date / Transfer Notes", current_patient["discharge_notes"], key="tab1_p_notes")
    with col_st3:
        if st.button("Update Status", key="tab1_update_status_btn"):
            conn = get_db_connection()
            conn.execute("UPDATE patients SET status = ?, discharge_notes = ? WHERE mrn = ?", (new_status, discharge_notes, current_patient["mrn"]))
            conn.commit()
            conn.close()
            st.success("Status updated successfully!")
            st.rerun()

    if st.button("🗑️ Delete Patient Record", key="tab1_delete_pat_btn"):
        conn = get_db_connection()
        conn.execute("DELETE FROM labs WHERE mrn = ?", (current_patient["mrn"],))
        conn.execute("DELETE FROM patients WHERE mrn = ?", (current_patient["mrn"],))
        conn.commit()
        conn.close()
        st.warning("Patient record deleted.")
        if 'active_mrn' in st.session_state:
            del st.session_state['active_mrn']
        st.rerun()

    st.markdown("---")
    st.markdown("### 1. Identification & Situation")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("MRN", current_patient["mrn"])
        st.metric("Birth Date/Time", current_patient["birth_date"])
        st.metric("Gender", current_patient["gender"])
    with c2:
        st.metric("Gestational Age", current_patient["gestational_age"])
        st.metric("Birth Weight", current_patient["birth_weight"])
        st.metric("Treating Consultant", current_patient["primary_physician"])
    with c3:
        st.metric("Mother Blood Group", current_patient["blood_group_mother"])
        st.metric("Baby Blood Group", current_patient["blood_group_baby"])
        st.metric("DAT Test", current_patient["dat"])

    st.markdown("### 🍼 Feeding & Medications")
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        st.metric("Feeding Type", current_patient["feeding_type"])
    with fc2:
        st.metric("Vitamin K", current_patient["vit_k_status"])
    with fc3:
        st.metric("Hepatitis B", current_patient["hepb_status"])
    with fc4:
        st.metric("RSV Prophylaxis", current_patient["rsv_status"])

    st.markdown("### 🔍 Screening Tests Results")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.metric("CCHD Screening", current_patient["cchd_status"])
    with sc2:
        st.metric("Red Reflex Test", current_patient["red_reflex_status"])
    with sc3:
        st.metric("Hearing Screening", current_patient["hearing_status"])

    st.markdown("### 2. Background & Assessment")
    st.info(f"📝 **Diagnosis ({current_patient['delivery_type']}):**\n\n{current_patient['diagnosis']}\n\n**Management Plan:**\n{current_patient['management_plan']}")
    st.warning(f"⏰ **Next Labs Due:**\n\n{current_patient['next_labs_due']}")

with tab2:
    st.subheader("📈 Bilirubin Log & Trend Chart (سجل البيليروبين)")

    with st.expander("➕ Add New SBR Result"):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            hours_life = st.number_input("Hours of Life (HOF)", min_value=0.0, max_value=720.0, value=53.0, key="tab2_sbr_hof")
        with col_b:
            sbr_val = st.number_input("Total Bilirubin Result", min_value=0.0, max_value=800.0, value=245.0, key="tab2_sbr_val")
        with col_c:
            sbr_unit = st.selectbox("Unit", ["umol/L", "mg/dL"], index=0, key="tab2_sbr_unit")
        
        if st.button("Add SBR Reading", key="tab2_add_sbr_btn"):
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
            st.markdown("### 📊 Bilirubin Trend Plot")
            chart_data = bili_trend_df.set_index("time_hours")[["test_value"]]
            st.line_chart(chart_data)
            
            st.markdown("### 🔵 Patient Bilirubin Trend Table")
            st.dataframe(bili_trend_df, use_container_width=True)
        else:
            st.info("No Bilirubin readings recorded yet.")

with tab3:
    st.subheader("🧪 Cumulative Laboratory Results & Comparison (التحاليل التراكمية)")
    
    with st.expander("➕ Add Any Laboratory Test"):
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            test_category = st.selectbox("Test Category", ["SBR (Bilirubin)", "CRP", "Calcium", "Creatinine", "CBC", "Thyroid (TSH)", "Electrolytes"], key="tab3_t_cat")
        with col_t2:
            if test_category == "SBR (Bilirubin)":
                custom_test_name = "SBR"
            elif test_category == "CRP":
                custom_test_name = "CRP"
            elif test_category == "Calcium":
                custom_test_name = "Calcium"
            elif test_category == "Creatinine":
                custom_test_name = "Creatinine"
            elif test_category == "Thyroid (TSH)":
                custom_test_name = st.selectbox("Select Test", ["Cord TSH", "Baby TSH", "Free T4"], key="tab3_t_tsh")
            elif test_category == "Electrolytes":
                custom_test_name = st.selectbox("Select Test", ["Sodium (Na)", "Potassium (K)"], key="tab3_t_elec")
            else:
                custom_test_name = st.text_input("Enter Custom Lab Name", value="WBC", key="tab3_t_custom")
        with col_t3:
            test_val = st.number_input("Test Value", value=1.9, key="tab3_t_val")
            test_unit = st.text_input("Unit", value="mg/L", key="tab3_t_unit")

        test_hours = st.number_input("Hours of Life at Lab Draw", min_value=0.0, max_value=720.0, value=compute_hours_of_life(current_patient["birth_date"]), key="tab3_t_hours")

        if st.button("Save Lab Result", key="tab3_save_lab_btn"):
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, time_hours, datetime_str, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)",
                         (current_patient["mrn"], test_hours, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), custom_test_name, test_val, test_unit))
            conn.commit()
            conn.close()
            st.success("Lab result saved successfully!")
            st.rerun()
            
    st.markdown("### 📋 Cumulative Lab Records & Comparison Table")
    raw_labs_df = current_patient["labs"]
    if not raw_labs_df.empty:
        def get_reference(t_name):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT min_val, max_val, unit FROM custom_references WHERE test_name = ?", (t_name,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return f"{row['min_val']} - {row['max_val']} {row['unit']}"
            return "Standard Range"

        display_labs = raw_labs_df.copy()
        display_labs["Reference Range"] = display_labs["test_name"].apply(lambda x: get_reference(x))
        st.dataframe(display_labs, use_container_width=True)
        
        st.markdown("---")
        st.markdown("**Cumulative Trend Comparison (مقارنة التغير بين القراءات):**")
        
        unique_tests = raw_labs_df["test_name"].unique()
        for t_name in unique_tests:
            t_df = raw_labs_df[raw_labs_df["test_name"] == t_name].sort_values("time_hours").reset_index(drop=True)
            if len(t_df) > 0:
                comparison_rows = []
                prev_val = None
                for idx, row in t_df.iterrows():
                    curr_val = row["test_value"]
                    if prev_val is None:
                        trend_status = "Baseline (أول قياس)"
                    elif curr_val > prev_val:
                        trend_status = "Increased (ارتفاع)"
                    elif curr_val < prev_val:
                        trend_status = "Decreased (انخفاض)"
                    else:
                        trend_status = "Stable (ثابت)"
                        
                    comparison_rows.append({
                        "Hours of Life": row["time_hours"],
                        "Datetime": row["datetime_str"],
                        "Test Name": row["test_name"],
                        "Value": curr_val,
                        "Unit": row["unit"],
                        "Reference Range": get_reference(row["test_name"]),
                        "Trend Comparison": trend_status
                    })
                    prev_val = curr_val
                
                comp_df = pd.DataFrame(comparison_rows)
                st.markdown(f"**🧪 Test: {t_name}**")
                st.dataframe(comp_df, use_container_width=True)
    else:
        st.info("لا توجد تحاليل مسجلة.")

with tab4:
    st.subheader("💡 Clinical Summary & Data Log")
    labs_df = current_patient["labs"]
    bili_labs = labs_df[labs_df["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])] if not labs_df.empty else pd.DataFrame()
    if not bili_labs.empty:
        latest_sbr = bili_labs.iloc[-1]["test_value"]
        latest_hrs = bili_labs.iloc[-1]["time_hours"]
        st.info(f"**Latest recorded SBR:** {round(latest_sbr, 1)} µmol/L at {latest_hrs} hours of life.")
    else:
        st.info("No SBR results recorded yet.")

with tab5:
    st.subheader("📤 Shift Handover (Secure Internal & Print)")
    
    anonymize_flag = st.checkbox("🔒 تفعيل إخفاء الهوية (Anonymize Patient Identity)", value=False, key="tab5_anon_checkbox")
    
    p_name = "[ANONYMIZED PATIENT]" if anonymize_flag else current_patient['baby_name']
    p_mrn = "[HIDDEN MRN]" if anonymize_flag else current_patient['mrn']
    
    latest_sbr_txt = "N/A"
    if not current_patient["labs"].empty:
        bili_row = current_patient["labs"][current_patient["labs"]["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])]
        if not bili_row.empty:
            r = bili_row.iloc[-1]
            latest_sbr_txt = f"{r['test_value']} {r['unit']} at {r['time_hours']} hours"
        
    handover_text = f"""📋 NEONATAL NURSERY SHIFT HANDOVER LOG (INTERNAL)
Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
Patient: {p_name} (MRN: {p_mrn})
Status: {current_patient['status']}
GA: {current_patient['gestational_age']} | Weight: {current_patient['birth_weight']}
Treating Consultant: {current_patient['primary_physician']}
Diagnosis ({current_patient['delivery_type']}): {current_patient['diagnosis']}
Risk Factors: {current_patient['risk_factors']} | DAT: {current_patient['dat']}
Feeding: {current_patient['feeding_type']}
Medications & Vaccines: Vit K [{current_patient['vit_k_status']}] | Hep B [{current_patient['hepb_status']}] | RSV [{current_patient['rsv_status']}]
Screening: CCHD [{current_patient['cchd_status']}] | Red Reflex [{current_patient['red_reflex_status']}] | Hearing [{current_patient['hearing_status']}]
Latest SBR: {latest_sbr_txt}

Management Plan:
{current_patient['management_plan']}

Next Labs Due:
{current_patient['next_labs_due']}"""

    st.markdown("### Report Preview (Secure Internal Review & Print):")
    st.code(handover_text, language="text")
    
    if st.button("🖨️ Print Report (Save as PDF securely)", key="tab5_print_btn"):
        st.markdown("<script>window.print();</script>", unsafe_allow_html=True)
        st.info("Use your browser's print dialog (Ctrl+P / Cmd+P) to print or save as PDF securely.")
