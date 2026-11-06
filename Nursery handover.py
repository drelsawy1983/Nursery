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
    page_title="Sabry Vision - Neonatal Nursery Digital Handover",
    page_icon="👶",
    layout="wide"
)

# --- Custom CSS for Professional Handover Tables & Print Isolation ---
st.markdown("""
<style>
.metric-container { font-size: 11px !important; }
.pink-warning { background-color: #ffe6f2; padding: 4px 8px; border-radius: 4px; border: 1px solid #ffb3d9; color: #99004d; font-weight: bold; display: inline-block; }

@media print {
    body * {
        visibility: hidden;
    }
    #printable-handover-area, #printable-handover-area * {
        visibility: visible;
    }
    #printable-handover-area {
        position: absolute;
        left: 0;
        top: 0;
        width: 100%;
        background: white;
    }
}

.handover-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 15px;
    font-family: Arial, sans-serif;
    font-size: 12px;
    color: #000;
}
.handover-table th, .handover-table td {
    border: 1px solid #333;
    padding: 6px 8px;
    text-align: left;
}
.handover-table th {
    background-color: #f2f2f2;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

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
            mother_abo TEXT,
            mother_rh TEXT,
            baby_abo TEXT,
            baby_rh TEXT,
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
            feeding_type TEXT,
            prom_status TEXT,
            prom_hours REAL,
            prom_mins REAL,
            antibiotic_status TEXT,
            antibiotic_name TEXT,
            antibiotic_doses INTEGER,
            antibiotic_treated TEXT,
            pethidine_status TEXT,
            pethidine_details TEXT,
            ctg_category TEXT,
            ctg_findings TEXT,
            hvs_status TEXT,
            hvs_organism TEXT,
            hvs_treated TEXT,
            gbs_status TEXT,
            gbs_site TEXT,
            gbs_treated TEXT,
            hypothyroid_status TEXT,
            thyroxine_status TEXT,
            thyroxine_dose TEXT,
            dm_status TEXT,
            dm_treatment TEXT,
            maternal_diseases TEXT,
            gravida INTEGER,
            para INTEGER,
            abortion INTEGER,
            obs_history TEXT,
            family_history TEXT,
            echo_status TEXT,
            echo_result TEXT,
            echo_followup_months INTEGER,
            consultation_type TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS labs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT,
            sample_datetime TEXT,
            hours_elapsed REAL,
            test_name TEXT,
            test_value REAL,
            unit TEXT,
            FOREIGN KEY (mrn) REFERENCES patients (mrn) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS imaging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT,
            img_type TEXT,
            img_name TEXT,
            img_result TEXT,
            img_date TEXT,
            FOREIGN KEY (mrn) REFERENCES patients (mrn) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rbs_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT,
            rbs_val REAL,
            rbs_time TEXT,
            FOREIGN KEY (mrn) REFERENCES patients (mrn) ON DELETE CASCADE
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
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password, role, full_name, national_id) VALUES (?, ?, ?, ?, ?)",
                       ("admin", "admin", "admin", "System Administrator", "0000000000"))
    conn.commit()
    conn.close()

init_db()

# --- Mandatory Legal Disclaimer State ---
if "consented" not in st.session_state:
    st.session_state.consented = False

if not st.session_state.consented:
    st.markdown("<h2 style='text-align: center; color: #cc0000;'>⚖️ LEGAL DISCLAIMER & TERMS OF USE</h2>", unsafe_allow_html=True)
    st.markdown("""
    <div style='background-color: #f9f9f9; padding: 20px; border-radius: 10px; border: 1px solid #ddd;'>
    <p><b>By accessing and using the Sabry Vision Neonatal Nursery Logbook System, you acknowledge and agree that this software is strictly a digital logbook and handover tool for administrative and census tracking. The application designer, developer, and owner bear <u>ABSOLUTELY NO LIABILITY OR LEGAL RESPONSIBILITY</u> for any medical decisions, diagnostic errors, treatment outcomes, or data breaches resulting from the use of this system.</b></p>
    <p><b>ALL RESPONSIBILITY RESTS SOLELY WITH THE USER.</b> The healthcare professional using this software is entirely responsible for verifying all clinical data, patient privacy compliance, treatment plans, and medical interventions.</p>
    </div>
    """, unsafe_allow_html=True)
    
    with st.form("disclaimer_form"):
        consent_check = st.selectbox("Do you confirm that you have read, understood, and agreed to all terms and instructions?", ["Select...", "Yes, I Agree & Accept", "No"], index=0)
        disclaimer_submit = st.form_submit_button("Proceed to System")
        if disclaimer_submit:
            if consent_check == "Yes, I Agree & Accept":
                st.session_state.consented = True
                st.rerun()
            else:
                st.error("You must select 'Yes, I Agree & Accept' to enter the system.")
    st.stop()

# --- Helper Functions ---
def convert_to_umol(val: float, unit: str) -> float:
    if unit and "mg" in unit.lower():
        return val * 17.1
    return val

def calculate_hours_from_parts(birth_dt_str, sample_date, sample_hour, sample_min):
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
        
        sample_dt = datetime.datetime.combine(sample_date, datetime.time(int(sample_hour), int(sample_min)))
        diff = sample_dt - dt_birth
        return round(max(0.0, diff.total_seconds() / 3600.0), 2)
    except Exception:
        return 24.0

# --- Main App Layout ---
current_date_str = datetime.date.today().strftime("%Y-%m-%d")
st.title(f"👶 Sabry Vision - Neonatal Nursery Digital Logbook [{current_date_str}]")

mode_option = st.selectbox("🎛️ Select Operation Mode", ["Actual Nursery", "Demo Test Patient (Rich Data Version)"], key="main_mode_selectbox")

# Populate Demo Patient with anonymous rich test data if Demo mode is selected
if "Demo" in mode_option:
    conn = get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, ga_days, birth_weight, birth_datetime, gender, mother_abo, mother_rh, baby_abo, baby_rh, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due, primary_physician, diagnosis, delivery_type, cchd_status, red_reflex_status, hearing_status, vit_k_status, hepb_status, rsv_status, feeding_type, prom_status, prom_hours, prom_mins, antibiotic_status, antibiotic_name, antibiotic_doses, antibiotic_treated, pethidine_status, pethidine_details, ctg_category, ctg_findings, hvs_status, hvs_organism, hvs_treated, gbs_status, gbs_site, gbs_treated, hypothyroid_status, thyroxine_status, thyroxine_dose, dm_status, dm_treatment, maternal_diseases, gravida, para, abortion, obs_history, family_history, echo_status, echo_result, echo_followup_months, consultation_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000000", "SON OF ***", 35, 3, 2.005, "2026-10-30 19:20:00", "Male", "O", "NEG", "A", "POS", "Positive", "Preterm, SVD, AGA, Episode of cyanosis", "Still in Nursery", "", "Cholecalciferol, Vit A, IV fluids Q24H", "SBR Q12H", "Dr. Amany", "PRETERM, SVD, AGA", "SVD", "Pass", "Pass", "Pending", "Given", "Given", "Not Given", "Special Formula Milk Q2HR - SIMILAC 24KCAL / TOLERATED - 15 TO 20 ML", "Yes", 63, 0, "Yes", "Ampicillin", 9, "Treated", "Yes", "100mg IV", "Category C", "Variable decelerations", "Yes", "E. coli", "Treated", "Yes", "in urine", "Treated", "Yes", "On Thyroxin", "50 mcg daily", "Gestational DM", "insulin", "Hypothyroidism, GDM", 3, 2, 1, "Previous IUFD at 28 weeks", "No family history of genetic disorders", "Requested before discharge", "Normal PDA closed, mild PFO", 6, "Orthopedic consultation")
    )
    conn.execute("DELETE FROM labs WHERE mrn = '000000'")
    demo_labs = [
        ("000000", "2026-10-31 10:00", 14.5, "SBR", 101.3, "umol/L"),
        ("000000", "2026-10-31 22:00", 26.5, "SBR", 165.0, "umol/L"),
        ("000000", "2026-11-01 15:00", 44.0, "SBR", 245.0, "umol/L"),
        ("000000", "2026-10-31 12:00", 16.5, "CRP", 1.9, "mg/L"),
        ("000000", "2026-11-01 09:00", 37.0, "CRP", 4.2, "mg/L"),
        ("000000", "2026-10-31 12:00", 16.5, "Calcium", 2.1, "mmol/L"),
        ("000000", "2026-11-01 09:00", 37.0, "Calcium", 1.9, "mmol/L"),
        ("000000", "2026-11-02 08:00", 60.5, "Calcium", 2.3, "mmol/L"),
        ("000000", "2026-10-31 12:00", 16.5, "Creatinine", 85.0, "umol/L"),
        ("000000", "2026-11-01 09:00", 37.0, "Creatinine", 110.0, "umol/L"),
        ("000000", "2026-11-02 08:00", 60.5, "Creatinine", 65.0, "umol/L"),
        ("000000", "2026-10-31 12:00", 16.5, "TSH", 3.4, "mIU/L"),
        ("000000", "2026-10-31 12:00", 16.5, "Blood Sugar", 3.8, "mmol/L")
    ]
    conn.executemany("INSERT INTO labs (mrn, sample_datetime, hours_elapsed, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)", demo_labs)
    
    conn.execute("DELETE FROM imaging WHERE mrn = '000000'")
    demo_imgs = [
        ("000000", "Ultrasound", "Cranial Ultrasound", "Normal ventricular system, no ICH or periventricular leukomalacia.", "2026-10-31"),
        ("000000", "Ultrasound", "Abdomen Ultrasound", "Normal liver, spleen, and kidneys. No hydronephrosis.", "2026-10-31"),
        ("000000", "X-Ray", "Chest X-Ray", "Clear lung fields, normal cardiothoracic ratio.", "2026-10-30"),
        ("000000", "X-Ray", "X-Ray Clavicles", "Intact bilateral clavicles with no fractures.", "2026-10-30")
    ]
    conn.executemany("INSERT INTO imaging (mrn, img_type, img_name, img_result, img_date) VALUES (?, ?, ?, ?, ?)", demo_imgs)

    conn.execute("DELETE FROM rbs_logs WHERE mrn = '000000'")
    demo_rbs = [
        ("000000", 3.8, "2026-10-30 19:40"),
        ("000000", 4.2, "2026-10-30 22:00"),
        ("000000", 4.5, "2026-10-31 06:00"),
        ("000000", 4.1, "2026-10-31 12:00")
    ]
    conn.executemany("INSERT INTO rbs_logs (mrn, rbs_val, rbs_time) VALUES (?, ?, ?)", demo_rbs)

    conn.commit()
    conn.close()

# Fetch patients from DB based on mode
conn = get_db_connection()
patients_cursor = conn.cursor()
if "Demo" in mode_option:
    patients_cursor.execute("SELECT * FROM patients WHERE mrn = '000000'")
else:
    patients_cursor.execute("SELECT * FROM patients WHERE mrn != '000000'")
db_patients = patients_cursor.fetchall()
conn.close()

patients_dict = {}
for p in db_patients:
    conn = get_db_connection()
    labs_df = pd.read_sql("SELECT * FROM labs WHERE mrn = ? ORDER BY hours_elapsed ASC", conn, params=(p["mrn"],))
    img_df = pd.read_sql("SELECT * FROM imaging WHERE mrn = ?", conn, params=(p["mrn"],))
    rbs_df = pd.read_sql("SELECT * FROM rbs_logs WHERE mrn = ?", conn, params=(p["mrn"],))
    conn.close()
    
    ga_w = p["ga_weeks"] if p["ga_weeks"] is not None else 38
    ga_d = p["ga_days"] if p["ga_days"] is not None else 0
    
    patients_dict[p["mrn"]] = {
        "baby_name": p["baby_name"],
        "mrn": p["mrn"],
        "gestational_age": f"{ga_w} W + {ga_d} D",
        "ga_weeks": ga_w,
        "ga_days": ga_d,
        "birth_weight": f"{p['birth_weight']} kg",
        "birth_weight_val": p["birth_weight"],
        "birth_date": p["birth_datetime"],
        "gender": p["gender"],
        "mother_abo": p["mother_abo"] if p["mother_abo"] else "O",
        "mother_rh": p["mother_rh"] if p["mother_rh"] else "POS",
        "baby_abo": p["baby_abo"] if p["baby_abo"] else "A",
        "baby_rh": p["baby_rh"] if p["baby_rh"] else "POS",
        "dat": p["dat"] if p["dat"] else "Negative",
        "risk_factors": p["risk_factors"],
        "status": p["status"],
        "discharge_notes": p["discharge_notes"],
        "management_plan": p["management_plan"],
        "next_labs_due": p["next_labs_due"],
        "primary_physician": p["primary_physician"] if p["primary_physician"] else "Dr. Amany",
        "diagnosis": p["diagnosis"],
        "delivery_type": p["delivery_type"],
        "cchd_status": p["cchd_status"] if p["cchd_status"] else "Pending",
        "red_reflex_status": p["red_reflex_status"] if p["red_reflex_status"] else "Pending",
        "hearing_status": p["hearing_status"] if p["hearing_status"] else "Pending",
        "vit_k_status": p["vit_k_status"] if p["vit_k_status"] else "Given",
        "hepb_status": p["hepb_status"] if p["hepb_status"] else "Given",
        "rsv_status": p["rsv_status"] if p["rsv_status"] else "Not Given",
        "feeding_type": p["feeding_type"] if p["feeding_type"] else "Regular Formula",
        "prom_status": p["prom_status"] if p["prom_status"] else "No",
        "prom_hours": p["prom_hours"] if p["prom_hours"] else 0,
        "prom_mins": p["prom_mins"] if p["prom_mins"] else 0,
        "antibiotic_status": p["antibiotic_status"] if p["antibiotic_status"] else "No",
        "antibiotic_name": p["antibiotic_name"] if p["antibiotic_name"] else "",
        "antibiotic_doses": p["antibiotic_doses"] if p["antibiotic_doses"] else 0,
        "antibiotic_treated": p["antibiotic_treated"] if p["antibiotic_treated"] else "Treated",
        "pethidine_status": p["pethidine_status"] if p["pethidine_status"] else "No",
        "pethidine_details": p["pethidine_details"] if p["pethidine_details"] else "",
        "ctg_category": p["ctg_category"] if p["ctg_category"] else "Category A",
        "ctg_findings": p["ctg_findings"] if p["ctg_findings"] else "Reassuring",
        "hvs_status": p["hvs_status"] if p["hvs_status"] else "No",
        "hvs_organism": p["hvs_organism"] if p["hvs_organism"] else "",
        "hvs_treated": p["hvs_treated"] if p["hvs_treated"] else "",
        "gbs_status": p["gbs_status"] if p["gbs_status"] else "No",
        "gbs_site": p["gbs_site"] if p["gbs_site"] else "",
        "gbs_treated": p["gbs_treated"] if p["gbs_treated"] else "",
        "hypothyroid_status": p["hypothyroid_status"] if p["hypothyroid_status"] else "No",
        "thyroxine_status": p["thyroxine_status"] if p["thyroxine_status"] else "No",
        "thyroxine_dose": p["thyroxine_dose"] if p["thyroxine_dose"] else "",
        "dm_status": p["dm_status"] if p["dm_status"] else "No",
        "dm_treatment": p["dm_treatment"] if p["dm_treatment"] else "No treatment",
        "maternal_diseases": p["maternal_diseases"] if p["maternal_diseases"] else "",
        "gravida": p["gravida"] if p["gravida"] else 1,
        "para": p["para"] if p["para"] else 0,
        "abortion": p["abortion"] if p["abortion"] else 0,
        "obs_history": p["obs_history"] if p["obs_history"] else "",
        "family_history": p["family_history"] if p["family_history"] else "",
        "echo_status": p["echo_status"] if p["echo_status"] else "",
        "echo_result": p["echo_result"] if p["echo_result"] else "",
        "echo_followup_months": p["echo_followup_months"] if p["echo_followup_months"] else 0,
        "consultation_type": p["consultation_type"] if p["consultation_type"] else "",
        "labs": labs_df,
        "imaging": img_df,
        "rbs": rbs_df
    }

# --- Main Page: Add New Newborn (Manual Entry Hub) ---
st.markdown("---")
with st.expander("➕ **Add New Newborn (Manual Entry Hub)**", expanded=len(patients_dict) == 0 and "Actual" in mode_option):
    st.markdown("Enter new newborn details and maternal history:")
    
    col_input1, col_input2 = st.columns(2)
    with col_input1:
        new_mrn = st.text_input("Baby MRN", value="000000", key="main_new_mrn")
        new_name = st.text_input("Patient Full Name", value="SON OF ***", key="main_new_name")
        gender_val = st.selectbox("Gender", ["Male", "Female"], index=0, key="main_new_gender")
        
        st.markdown("Gestational Age")
        col_ga1, col_ga2 = st.columns(2)
        with col_ga1:
            new_ga_w = st.number_input("Weeks", min_value=24, max_value=44, value=38, key="main_new_gaw")
        with col_ga2:
            new_ga_d = st.number_input("Days", min_value=0, max_value=6, value=0, key="main_new_gad")
            
    with col_input2:
        new_wt = st.number_input("Birth Weight (kg)", value=2.500, key="main_new_wt")
        
        consultant_options = [
            "Dr. Amany", "Dr. Hosny", "Dr. Ibrahim BAHLAK",
            "Dr. Mahmoud El-Naggar", "Dr. NEMER", "Dr. Al-Thubaiti", "Other"
        ]
        selected_cons = st.selectbox("Treating Consultant", consultant_options, index=0, key="main_new_cons")
        new_physician = st.text_input("Custom Consultant Name", value="Dr. Amany", key="main_new_cname") if selected_cons == "Other" else selected_cons
        
        new_diagnosis = st.text_input("Diagnosis", value="", key="main_new_diag")
        new_delivery = st.selectbox("Delivery Type", ["SVD", "CS", "BBA", "Ventouse Delivery", "CS with Assisted Forceps"], index=0, key="main_new_del")

    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    with col_b1:
        m_abo = st.selectbox("Mother ABO", ["A", "B", "AB", "O"], index=3, key="main_mabo")
    with col_b2:
        m_rh = st.selectbox("Mother Rh", ["POS", "NEG"], index=0, key="main_mrh")
    with col_b3:
        b_abo = st.selectbox("Baby ABO", ["A", "B", "AB", "O"], index=0, key="main_babo")
    with col_b4:
        b_rh = st.selectbox("Baby Rh", ["POS", "NEG"], index=0, key="main_brh")

    dat_val = st.selectbox("DAT Test", ["Negative", "Positive"], index=0, key="main_dat")

    st.markdown("---")
    st.markdown("### 📋 Booking & Obstetric History")
    col_ob1, col_ob2, col_ob3 = st.columns(3)
    with col_ob1:
        new_gravida = st.number_input("Gravida (G)", min_value=1, value=1, key="main_gravida")
    with col_ob2:
        new_para = st.number_input("Para (P)", min_value=0, value=0, key="main_para")
    with col_ob3:
        new_abortion = st.number_input("Abortion (A)", min_value=0, value=0, key="main_abortion")
        
    new_obs_history = st.text_area("Previous Obstetric History (Stillbirth, Congenital anomalies, syndromes, neonatal death, IUFD)", value="", key="main_obs_hist")
    new_family_history = st.text_area("Family History", value="", key="main_fam_hist")

    st.markdown("---")
    st.markdown("### ⚠️ Detailed Risk Factors & Maternal History")
    
    col_rf1, col_rf2 = st.columns(2)
    with col_rf1:
        prom_status = st.selectbox("PROM", ["No", "Yes"], index=0, key="main_prom")
        prom_hours, prom_mins = 0, 0
        if prom_status == "Yes":
            ph_col, pm_col = st.columns(2)
            with ph_col:
                prom_hours = st.number_input("PROM Hours", min_value=0, value=0, key="main_prom_h")
            with pm_col:
                prom_mins = st.number_input("PROM Mins", min_value=0, max_value=59, value=0, key="main_prom_m")
                
        ab_status = st.selectbox("Mother Received Antibiotic", ["No", "Yes"], index=0, key="main_ab_status")
        ab_name, ab_doses, ab_treated = "", 1, "Treated"
        if ab_status == "Yes":
            ab_select = st.selectbox("Antibiotic Name", ["Ampicillin", "Clindamycin", "Other Med"], key="main_ab_sel")
            ab_name = st.text_input("Enter Antibiotic Name", value="Ampicillin", key="main_ab_txt") if ab_select == "Other Med" else ab_select
            ab_doses = st.number_input("Number of Doses", min_value=1, value=1, key="main_ab_doses")
            ab_treated = st.selectbox("Treatment Status", ["Treated", "Not Treated"], key="main_ab_treated")

        peth_status = st.selectbox("Mother Received Pethidine / Opioids during/before delivery", ["No", "Yes"], index=0, key="main_peth")
        peth_details = st.text_input("Pethidine Details (Dose & Timing)", value="", key="main_peth_det") if peth_status == "Yes" else ""

    with col_rf2:
        ctg_cat = st.selectbox("CTG Category", ["Category A", "Category B", "Category C", "Other Custom"], index=0, key="main_ctg_cat")
        ctg_cat_val = st.text_input("Enter Custom CTG Category", value="", key="main_ctg_cat_txt") if ctg_cat == "Other Custom" else ctg_cat
        
        ctg_find = st.selectbox("CTG Findings / Fetal Distress", ["Reassuring", "Fetal distress", "Fetal tachycardia", "Fetal bradycardia", "Variable decelerations", "Late decelerations", "Other Custom"], index=0, key="main_ctg_find")
        ctg_find_val = st.text_input("Enter Custom CTG Findings", value="", key="main_ctg_find_txt") if ctg_find == "Other Custom" else ctg_find

        hvs_status = st.selectbox("HVS Positive", ["No", "Yes"], index=0, key="main_hvs")
        hvs_org, hvs_treat = "", ""
        if hvs_status == "Yes":
            hvs_org = st.text_input("Organism Name", value="", key="main_hvs_org")
            hvs_treat = st.selectbox("HVS Treatment Status", ["Treated", "Non Treated"], key="main_hvs_treat")

        gbs_status = st.selectbox("GBS Positive", ["No", "Yes"], index=0, key="main_gbs")
        gbs_site, gbs_treat = "", ""
        if gbs_status == "Yes":
            gbs_site = st.selectbox("GBS Site", ["in urine", "vaginal"], key="main_gbs_site")
            gbs_treat = st.selectbox("GBS Treatment Status", ["Treated", "Non Treated"], key="main_gbs_treat")

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        hypo_status = st.selectbox("Hypothyroidism", ["No", "Yes"], index=0, key="main_hypo")
        thyrox_status, thyrox_dose = "No", ""
        if hypo_status == "Yes":
            thyrox_status = st.selectbox("Thyroxine Status", ["On Thyroxin", "Without treatment", "No treatment"], key="main_thyrox")
            thyroxine_dose = st.text_input("Thyroxine Dose (mg / mcg)", value="", key="main_thyrox_dose")
            
    with col_m2:
        dm_status = st.selectbox("Maternal / Gestational Diabetes Mellitus", ["No", "Gestational DM", "Pre-existing DM"], index=0, key="main_dm")
        dm_treat = "No treatment"
        if dm_status != "No":
            dm_treat_sel = st.selectbox("DM Treatment Type", ["diet control", "metformin", "insulin", "no treatment", "uncontrolled", "Other Custom"], key="main_dm_treat_sel")
            dm_treat = st.text_input("Enter Custom DM Treatment", value="", key="main_dm_treat_txt") if dm_treat_sel == "Other Custom" else dm_treat_sel

    mat_diseases = st.text_input("Other Maternal Diseases or Medications", value="", key="main_mat_dis")

    st.markdown("### 🍼 Feeding & Medications")
    new_feeding = st.selectbox("Feeding", ["Regular Formula", "AR Formula", "Exclusive Breastfeeding"], index=0, key="main_feed")

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

    mgmt_plan = st.text_area("Management Plan / Medications", value="", key="main_mgmt")
    next_labs = st.text_input("Next Labs Due", value="", key="main_nlabs")

    if st.button("Create Manual Newborn Record", key="main_create_pat_btn"):
        if new_mrn:
            conn = get_db_connection()
            conn.execute(
                "INSERT OR REPLACE INTO patients (mrn, baby_name, ga_weeks, ga_days, birth_weight, birth_datetime, gender, mother_abo, mother_rh, baby_abo, baby_rh, dat, risk_factors, status, discharge_notes, management_plan, next_labs_due, primary_physician, diagnosis, delivery_type, cchd_status, red_reflex_status, hearing_status, vit_k_status, hepb_status, rsv_status, feeding_type, prom_status, prom_hours, prom_mins, antibiotic_status, antibiotic_name, antibiotic_doses, antibiotic_treated, pethidine_status, pethidine_details, ctg_category, ctg_findings, hvs_status, hvs_organism, hvs_treated, gbs_status, gbs_site, gbs_treated, hypothyroid_status, thyroxine_status, thyroxine_dose, dm_status, dm_treatment, maternal_diseases, gravida, para, abortion, obs_history, family_history) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_mrn, new_name, new_ga_w, new_ga_d, new_wt, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), gender_val, m_abo, m_rh, b_abo, b_rh, dat_val, mat_diseases, "Still in Nursery", "", mgmt_plan, next_labs, new_physician, new_diagnosis, new_delivery, new_cchd, new_red_reflex, new_hearing, new_vit_k, new_hepb, new_rsv, new_feeding, prom_status, prom_hours, prom_mins, ab_status, ab_name, ab_doses, ab_treated, peth_status, peth_details, ctg_cat_val, ctg_find_val, hvs_status, hvs_org, hvs_treat, gbs_status, gbs_site, gbs_treat, hypo_status, thyrox_status, thyroxine_dose, dm_status, dm_treat, mat_diseases, new_gravida, new_para, new_abortion, new_obs_history, new_family_history)
            )
            conn.commit()
            conn.close()
            st.success("Patient successfully added!")
            st.rerun()
        else:
            st.error("Please enter Baby MRN.")

st.markdown("---")

# --- Census Overview Table & Quick Selection Cards ---
st.subheader("📊 Nursery Census Overview & Quick Patient Selection")
conn = get_db_connection()
census_df = pd.read_sql("SELECT mrn, baby_name, ga_weeks, ga_days, birth_weight, status, primary_physician FROM patients", conn)
conn.close()

if not census_df.empty:
    st.dataframe(census_df, use_container_width=True)
    
    st.markdown("### 🗂️ Quick Select Patient:")
    num_patients = len(patients_dict)
    if num_patients > 0:
        cols = st.columns(min(num_patients, 4))
        for idx, (mrn_val, p_data) in enumerate(patients_dict.items()):
            col_idx = idx % 4
            with cols[col_idx]:
                if st.button(f"👶 {p_data['baby_name']}\nMRN: {mrn_val}\n[{p_data['status']}]", key=f"btn_pat_{mrn_val}"):
                    st.session_state['active_mrn'] = mrn_val
else:
    st.info("No records found in this mode.")

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
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📋 Crib Card & Profile", 
    "⚠️ Risk Factors & History",
    "📈 Bilirubin Log", 
    "🧪 Cumulative Labs & Compare", 
    "📷 Ultrasound, X-Ray & Echo",
    "🩸 RBS Log",
    "📤 Shift Handover"
])

with tab1:
    st.subheader(f"Hospital Crib Card Format & Patient Editing: {current_patient['baby_name']}")
    
    with st.expander("✏️ Edit Patient Details & Vaccines", expanded=False):
        edit_name = st.text_input("Edit Patient Name", value=current_patient["baby_name"], key="tab1_edit_name")
        edit_diag = st.text_area("Edit Diagnosis", value=current_patient["diagnosis"], key="tab1_edit_diag")
        edit_mgmt = st.text_area("Edit Management Plan", value=current_patient["management_plan"], key="tab1_edit_mgmt")
        edit_labs = st.text_input("Edit Next Labs Due", value=current_patient["next_labs_due"], key="tab1_edit_labs")
        
        col_eb1, col_eb2, col_eb3, col_eb4 = st.columns(4)
        with col_eb1:
            edit_m_abo = st.selectbox("Mother ABO", ["A", "B", "AB", "O"], index=["A", "B", "AB", "O"].index(current_patient["mother_abo"]), key="tab1_em_abo")
        with col_eb2:
            edit_m_rh = st.selectbox("Mother Rh", ["POS", "NEG"], index=["POS", "NEG"].index(current_patient["mother_rh"]), key="tab1_em_rh")
        with col_eb3:
            edit_b_abo = st.selectbox("Baby ABO", ["A", "B", "AB", "O"], index=["A", "B", "AB", "O"].index(current_patient["baby_abo"]), key="tab1_eb_abo")
        with col_eb4:
            edit_b_rh = st.selectbox("Baby Rh", ["POS", "NEG"], index=["POS", "NEG"].index(current_patient["baby_rh"]), key="tab1_eb_rh")

        edit_dat = st.selectbox("DAT Test", ["Negative", "Positive"], index=["Negative", "Positive"].index(current_patient["dat"]), key="tab1_edat")
        
        feed_opt = ["Regular Formula", "AR Formula", "Exclusive Breastfeeding"]
        edit_feeding = st.selectbox("Feeding", feed_opt, index=feed_opt.index(current_patient["feeding_type"]) if current_patient["feeding_type"] in feed_opt else 0, key="tab1_edit_feed")

        v_opt = ["Given", "Not Given"]
        edit_vit_k = st.selectbox("Vitamin K", v_opt, index=v_opt.index(current_patient["vit_k_status"]) if current_patient["vit_k_status"] in v_opt else 0, key="tab1_edit_vitk")
        edit_hepb = st.selectbox("Hepatitis B Vaccine", v_opt, index=v_opt.index(current_patient["hepb_status"]) if current_patient["hepb_status"] in v_opt else 0, key="tab1_edit_hepb")
        edit_rsv = st.selectbox("RSV Vaccine / Prophylaxis", v_opt, index=v_opt.index(current_patient["rsv_status"]) if current_patient["rsv_status"] in v_opt else 1, key="tab1_edit_rsv")

        opt_list = ["Pending", "Pass", "Fail"]
        edit_cchd = st.selectbox("CCHD Status", opt_list, index=opt_list.index(current_patient["cchd_status"]) if current_patient["cchd_status"] in opt_list else 0, key="tab1_edit_cchd")
        edit_red = st.selectbox("Red Reflex Status", opt_list, index=opt_list.index(current_patient["red_reflex_status"]) if current_patient["red_reflex_status"] in opt_list else 0, key="tab1_edit_red")
        edit_hearing = st.selectbox("Hearing Screening Status", opt_list, index=opt_list.index(current_patient["hearing_status"]) if current_patient["hearing_status"] in opt_list else 0, key="tab1_edit_hearing")

        if st.button("Save Patient Updates", key="tab1_save_updates_btn"):
            conn = get_db_connection()
            conn.execute("UPDATE patients SET baby_name = ?, diagnosis = ?, management_plan = ?, next_labs_due = ?, mother_abo = ?, mother_rh = ?, baby_abo = ?, baby_rh = ?, dat = ?, cchd_status = ?, red_reflex_status = ?, hearing_status = ?, vit_k_status = ?, hepb_status = ?, rsv_status = ?, feeding_type = ? WHERE mrn = ?",
                         (edit_name, edit_diag, edit_mgmt, edit_labs, edit_m_abo, edit_m_rh, edit_b_abo, edit_b_rh, edit_dat, edit_cchd, edit_red, edit_hearing, edit_vit_k, edit_hepb, edit_rsv, edit_feeding, current_patient["mrn"]))
            conn.commit()
            conn.close()
            st.success("Patient details updated successfully!")
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
        conn.execute("DELETE FROM imaging WHERE mrn = ?", (current_patient["mrn"],))
        conn.execute("DELETE FROM rbs_logs WHERE mrn = ?", (current_patient["mrn"],))
        conn.execute("DELETE FROM patients WHERE mrn = ?", (current_patient["mrn"],))
        conn.commit()
        conn.close()
        st.warning("Patient record deleted.")
        if 'active_mrn' in st.session_state:
            del st.session_state['active_mrn']
        st.rerun()

    st.markdown("---")
    st.markdown("### 1. Identification & Situation")
    
    m_bg_display = f"{current_patient['mother_abo']} {current_patient['mother_rh']}"
    if current_patient['mother_abo'] == "O" or current_patient['mother_rh'] == "NEG":
        m_bg_html = f'<span class="pink-warning">{m_bg_display}</span>'
    else:
        m_bg_html = m_bg_display

    dat_display = current_patient['dat']
    if "POS" in dat_display.upper():
        dat_html = f'<span class="pink-warning">{dat_display}</span>'
    else:
        dat_html = dat_display

    col_id1, col_id2, col_id3 = st.columns(3)
    with col_id1:
        st.markdown(f"<div style='font-size:13px;'><b>MRN:</b> {current_patient['mrn']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'><b>Birth Date/Time:</b> {current_patient['birth_date']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'><b>Gender:</b> {current_patient['gender']}</div>", unsafe_allow_html=True)
    with col_id2:
        st.markdown(f"<div style='font-size:13px;'><b>Gestational Age:</b> {current_patient['gestational_age']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'><b>Birth Weight:</b> {current_patient['birth_weight']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'><b>Treating Consultant:</b> {current_patient['primary_physician']}</div>", unsafe_allow_html=True)
    with col_id3:
        st.markdown(f"<div style='font-size:13px;'><b>Mother Blood Group:</b> {m_bg_html}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'><b>Baby Blood Group:</b> {current_patient['baby_abo']} {current_patient['baby_rh']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:13px;'><b>DAT Test:</b> {dat_html}</div>", unsafe_allow_html=True)

    st.markdown("### 🍼 Feeding & Medications")
    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        st.markdown(f"<div style='font-size:12px;'><b>Feeding:</b> {current_patient['feeding_type']}</div>", unsafe_allow_html=True)
    with fc2:
        st.markdown(f"<div style='font-size:12px;'><b>Vit K:</b> {current_patient['vit_k_status']}</div>", unsafe_allow_html=True)
    with fc3:
        st.markdown(f"<div style='font-size:12px;'><b>Hep B:</b> {current_patient['hepb_status']}</div>", unsafe_allow_html=True)
    with fc4:
        st.markdown(f"<div style='font-size:12px;'><b>RSV:</b> {current_patient['rsv_status']}</div>", unsafe_allow_html=True)

    st.markdown("### 🔍 Screening Tests")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.markdown(f"<div style='font-size:12px;'><b>CCHD:</b> {current_patient['cchd_status']}</div>", unsafe_allow_html=True)
    with sc2:
        st.markdown(f"<div style='font-size:12px;'><b>Red Reflex:</b> {current_patient['red_reflex_status']}</div>", unsafe_allow_html=True)
    with sc3:
        st.markdown(f"<div style='font-size:12px;'><b>Hearing:</b> {current_patient['hearing_status']}</div>", unsafe_allow_html=True)

    st.markdown("### 2. Background & Assessment")
    st.info(f"📝 **Diagnosis ({current_patient['delivery_type']}):**\n\n{current_patient['diagnosis']}\n\n**Management Plan:**\n{current_patient['management_plan']}")
    st.warning(f"⏰ **Next Labs Due:**\n\n{current_patient['next_labs_due']}")

with tab2:
    st.subheader("⚠️ Risk Factors, Obstetric & Maternal History")
    
    with st.form("edit_risk_history_form"):
        e_gravida = st.number_input("Gravida (G)", min_value=1, value=int(current_patient["gravida"]), key="eh_g")
        e_para = st.number_input("Para (P)", min_value=0, value=int(current_patient["para"]), key="eh_p")
        e_abortion = st.number_input("Abortion (A)", min_value=0, value=int(current_patient["abortion"]), key="eh_a")
        
        e_obs_hist = st.text_area("Previous Obstetric History", value=current_patient["obs_history"], key="eh_obs")
        e_fam_hist = st.text_area("Family History", value=current_patient["family_history"], key="eh_fam")

        st.markdown("---")
        e_prom = st.selectbox("PROM", ["No", "Yes"], index=["No", "Yes"].index(current_patient["prom_status"]), key="eh_prom")
        e_prom_h = st.number_input("PROM Hours", min_value=0, value=int(current_patient["prom_hours"]), key="eh_prom_h")
        e_prom_m = st.number_input("PROM Mins", min_value=0, max_value=59, value=int(current_patient["prom_mins"]), key="eh_prom_m")

        e_ab_stat = st.selectbox("Mother Received Antibiotic", ["No", "Yes"], index=["No", "Yes"].index(current_patient["antibiotic_status"]), key="eh_ab")
        e_ab_name = st.text_input("Antibiotic Name", value=current_patient["antibiotic_name"], key="eh_ab_name")
        e_ab_doses = st.number_input("Antibiotic Doses", min_value=1, value=int(current_patient["antibiotic_doses"] or 1), key="eh_ab_doses")
        e_ab_treated = st.selectbox("Antibiotic Treatment Status", ["Treated", "Not Treated"], index=0 if current_patient["antibiotic_treated"]=="Treated" else 1, key="eh_ab_tr")

        e_peth = st.selectbox("Mother Received Pethidine / Opioids", ["No", "Yes"], index=["No", "Yes"].index(current_patient["pethidine_status"]), key="eh_peth")
        e_peth_det = st.text_input("Pethidine Details", value=current_patient["pethidine_details"], key="eh_peth_det")

        e_ctg_cat = st.text_input("CTG Category", value=current_patient["ctg_category"], key="eh_ctg_cat")
        e_ctg_find = st.text_input("CTG Findings", value=current_patient["ctg_findings"], key="eh_ctg_find")

        e_hvs = st.selectbox("HVS Positive", ["No", "Yes"], index=["No", "Yes"].index(current_patient["hvs_status"]), key="eh_hvs")
        e_hvs_org = st.text_input("HVS Organism", value=current_patient["hvs_organism"], key="eh_hvs_org")
        e_hvs_tr = st.text_input("HVS Treatment Status", value=current_patient["hvs_treated"], key="eh_hvs_tr")

        e_gbs = st.selectbox("GBS Positive", ["No", "Yes"], index=["No", "Yes"].index(current_patient["gbs_status"]), key="eh_gbs")
        e_gbs_site = st.selectbox("GBS Site", ["", "in urine", "vaginal"], index=["", "in urine", "vaginal"].index(current_patient["gbs_site"]) if current_patient["gbs_site"] in ["", "in urine", "vaginal"] else 0, key="eh_gbs_site")
        e_gbs_tr = st.text_input("GBS Treatment Status", value=current_patient["gbs_treated"], key="eh_gbs_tr")

        e_hypo = st.selectbox("Hypothyroidism", ["No", "Yes"], index=["No", "Yes"].index(current_patient["hypothyroid_status"]), key="eh_hypo")
        e_thy_st = st.text_input("Thyroxine Status", value=current_patient["thyroxine_status"], key="eh_thy_st")
        e_thy_dose = st.text_input("Thyroxine Dose", value=current_patient["thyroxine_dose"], key="eh_thy_dose")

        e_dm = st.selectbox("Diabetes Mellitus", ["No", "Gestational DM", "Pre-existing DM"], index=0 if current_patient["dm_status"]=="No" else (1 if current_patient["dm_status"]=="Gestational DM" else 2), key="eh_dm")
        e_dm_tr = st.text_input("DM Treatment", value=current_patient["dm_treatment"], key="eh_dm_tr")

        e_mat_dis = st.text_input("Other Maternal Diseases", value=current_patient["maternal_diseases"], key="eh_mat_dis")

        submit_risk_edit = st.form_submit_button("Save Risk & History Changes")
        if submit_risk_edit:
            conn = get_db_connection()
            conn.execute("""UPDATE patients SET gravida=?, para=?, abortion=?, obs_history=?, family_history=?, prom_status=?, prom_hours=?, prom_mins=?, antibiotic_status=?, antibiotic_name=?, antibiotic_doses=?, antibiotic_treated=?, pethidine_status=?, pethidine_details=?, ctg_category=?, ctg_findings=?, hvs_status=?, hvs_organism=?, hvs_treated=?, gbs_status=?, gbs_site=?, gbs_treated=?, hypothyroid_status=?, thyroxine_status=?, thyroxine_dose=?, dm_status=?, dm_treatment=?, maternal_diseases=? WHERE mrn=?""",
                         (e_gravida, e_para, e_abortion, e_obs_hist, e_fam_hist, e_prom, e_prom_h, e_prom_m, e_ab_stat, e_ab_name, e_ab_doses, e_ab_treated, e_peth, e_peth_det, e_ctg_cat, e_ctg_find, e_hvs, e_hvs_org, e_hvs_tr, e_gbs, e_gbs_site, e_gbs_tr, e_hypo, e_thy_st, e_thy_dose, e_dm, e_dm_tr, e_mat_dis, current_patient["mrn"]))
            conn.commit()
            conn.close()
            st.success("Risk factors and history updated successfully!")
            st.rerun()

with tab3:
    st.subheader("📈 Bilirubin Log")

    with st.expander("➕ Add New SBR Result"):
        sample_date = st.date_input("Sample Date", value=datetime.date.today(), key="tab3_sbr_date")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            sample_hour = st.number_input("Hour (0-23)", min_value=0, max_value=23, value=12, key="tab3_sbr_hr")
        with col_t2:
            sample_min = st.number_input("Minute (0-59)", min_value=0, max_value=59, value=0, key="tab3_sbr_min")
            
        col_a, col_b = st.columns(2)
        with col_a:
            sbr_val = st.number_input("Total Bilirubin Result", min_value=0.0, max_value=800.0, value=200.0, key="tab3_sbr_val")
        with col_b:
            sbr_unit = st.selectbox("Unit", ["umol/L", "mg/dL"], index=0, key="tab3_sbr_unit")
        
        if st.button("Add SBR Reading", key="tab3_add_sbr_btn"):
            val_umol = convert_to_umol(sbr_val, sbr_unit)
            computed_hours = calculate_hours_from_parts(current_patient["birth_date"], sample_date, sample_hour, sample_min)
            sample_dt_str = f"{sample_date} {str(sample_hour).zfill(2)}:{str(sample_min).zfill(2)}"
            
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, sample_datetime, hours_elapsed, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)",
                         (current_patient["mrn"], sample_dt_str, computed_hours, "SBR", val_umol, "umol/L"))
            conn.commit()
            conn.close()
            st.success(f"SBR Reading added successfully! (Hours of Life: {computed_hours}h)")
            st.rerun()

    labs_df = current_patient["labs"]
    if not labs_df.empty:
        bili_trend_df = labs_df[labs_df["test_name"].str.upper().isin(["SBR", "TOTAL BILIRUBIN", "BILIRUBIN"])]
        if not bili_trend_df.empty:
            st.markdown("### 🔵 Patient Bilirubin Log Table")
            for idx, row in bili_trend_df.iterrows():
                col_info, col_del = st.columns([5, 1])
                with col_info:
                    st.text(f"ID: {row['id']} | Time: {row['sample_datetime']} | Age: {row['hours_elapsed']}h | Value: {row['test_value']} {row['unit']}")
                with col_del:
                    if st.button("🗑️ Delete", key=f"del_sbr_{row['id']}"):
                        conn = get_db_connection()
                        conn.execute("DELETE FROM labs WHERE id = ?", (row['id'],))
                        conn.commit()
                        conn.close()
                        st.success("Bilirubin reading deleted successfully!")
                        st.rerun()
        else:
            st.info("No Bilirubin readings recorded yet.")

with tab4:
    st.subheader("🧪 Cumulative Laboratory Results & Compare")
    
    with st.expander("➕ Add Any Laboratory Test"):
        sample_date_gen = st.date_input("Sample Date", value=datetime.date.today(), key="tab4_gen_date")
        col_gt1, col_gt2 = st.columns(2)
        with col_gt1:
            sample_hour_gen = st.number_input("Hour (0-23)", min_value=0, max_value=23, value=12, key="tab4_gen_hr")
        with col_gt2:
            sample_min_gen = st.number_input("Minute (0-59)", min_value=0, max_value=59, value=0, key="tab4_gen_min")

        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            test_category = st.selectbox("Test Category", ["SBR (Bilirubin)", "CRP", "Calcium", "Creatinine", "CBC", "Thyroid (TSH)", "Electrolytes"], key="tab4_t_cat")
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
                custom_test_name = st.selectbox("Select Test", ["Cord TSH", "Baby TSH", "Free T4"], key="tab4_t_tsh")
            elif test_category == "Electrolytes":
                custom_test_name = st.selectbox("Select Test", ["Sodium (Na)", "Potassium (K)"], key="tab4_t_elec")
            else:
                custom_test_name = st.text_input("Enter Custom Lab Name", value="WBC", key="tab4_t_custom")
        with col_t3:
            test_val = st.number_input("Test Value", value=1.9, key="tab4_t_val")
            test_unit = st.text_input("Unit", value="mg/L", key="tab4_t_unit")

        if st.button("Save Lab Result", key="tab4_save_lab_btn"):
            computed_hours = calculate_hours_from_parts(current_patient["birth_date"], sample_date_gen, sample_hour_gen, sample_min_gen)
            sample_dt_str = f"{sample_date_gen} {str(sample_hour_gen).zfill(2)}:{str(sample_min_gen).zfill(2)}"
            
            conn = get_db_connection()
            conn.execute("INSERT INTO labs (mrn, sample_datetime, hours_elapsed, test_name, test_value, unit) VALUES (?, ?, ?, ?, ?, ?)",
                         (current_patient["mrn"], sample_dt_str, computed_hours, custom_test_name, test_val, test_unit))
            conn.commit()
            conn.close()
            st.success(f"Lab result saved successfully! (Hours of Life: {computed_hours}h)")
            st.rerun()

    if st.button("📊 Compare Repeated Labs Side-by-Side", key="compare_labs_btn"):
        raw_labs_df = current_patient["labs"]
        if not raw_labs_df.empty:
            st.markdown("### 📈 Repeated Labs Comparison Report")
            counts = raw_labs_df["test_name"].value_counts()
            repeated_tests = counts[counts > 1].index.tolist()
            if repeated_tests:
                for t_name in repeated_tests:
                    st.markdown(f"**🔬 Test: `{t_name}` (Repeated {counts[t_name]} times)**")
                    t_sub = raw_labs_df[raw_labs_df["test_name"] == t_name].sort_values("hours_elapsed")
                    comparison_list = []
                    prev_v = None
                    for idx, r in t_sub.iterrows():
                        curr_v = r["test_value"]
                        if prev_v is None:
                            trend = "Baseline"
                        elif curr_v > prev_v:
                            trend = "📈 Increased"
                        elif curr_v < prev_v:
                            trend = "📉 Decreased"
                        else:
                            trend = "➡️ Stable"
                        comparison_list.append({
                            "Sample Time": r["sample_datetime"],
                            "Hours of Life": f"{r['hours_elapsed']}h",
                            "Value": f"{curr_v} {r['unit']}",
                            "Trend vs Previous": trend
                        })
                        prev_v = curr_v
                    st.dataframe(pd.DataFrame(comparison_list), use_container_width=True)
            else:
                st.info("No repeated laboratory tests found.")
        else:
            st.info("No laboratory records found.")
            
    st.markdown("### 📋 Cumulative Lab Records & Delete Option")
    raw_labs_df = current_patient["labs"]
    if not raw_labs_df.empty:
        for idx, row in raw_labs_df.iterrows():
            col_l1, col_l2 = st.columns([5, 1])
            with col_l1:
                st.text(f"ID: {row['id']} | Test: {row['test_name']} | Val: {row['test_value']} {row['unit']} | Time: {row['sample_datetime']} ({row['hours_elapsed']}h)")
            with col_l2:
                if st.button("🗑️ Delete", key=f"del_lab_{row['id']}"):
                    conn = get_db_connection()
                    conn.execute("DELETE FROM labs WHERE id = ?", (row['id'],))
                    conn.commit()
                    conn.close()
                    st.success("Lab record deleted successfully!")
                    st.rerun()
    else:
        st.info("No lab records found.")

with tab5:
    st.subheader("📷 Ultrasound, X-Ray & Echo Results")

    with st.expander("➕ Add New Imaging / Echo Result"):
        img_category = st.selectbox("Category", ["Ultrasound", "X-Ray", "Echocardiography"], key="img_cat")
        if img_category == "Ultrasound":
            img_name = st.selectbox("Select US Type", ["Cranial Ultrasound", "Abdomen Ultrasound", "Hip Ultrasound", "Scrotal Ultrasound", "Sacral Ultrasound", "Other US"], key="us_name")
        elif img_category == "X-Ray":
            img_name = st.selectbox("Select X-Ray Type", ["X-Ray Clavicles", "Chest X-Ray", "Chest and Abdomen X-Ray", "Other X-Ray"], key="xr_name")
        else:
            img_name = "Echocardiography"
            
        img_date = st.date_input("Date", value=datetime.date.today(), key="img_date")
        img_result = st.text_area("Result / Findings", value="", key="img_res")
        
        if st.button("Save Imaging Result", key="save_img_btn"):
            if img_result:
                conn = get_db_connection()
                conn.execute("INSERT INTO imaging (mrn, img_type, img_name, img_result, img_date) VALUES (?, ?, ?, ?, ?)",
                             (current_patient["mrn"], img_category, img_name, img_result, str(img_date)))
                conn.commit()
                conn.close()
                st.success("Imaging report saved successfully!")
                st.rerun()
            else:
                st.error("Please enter the result description.")

    with st.expander("💓 Edit Echocardiography Details", expanded=False):
        e_echo_options = ["", "Not requested", "Requested as routine OPD", "Requested before discharge"]
        e_echo_idx = e_echo_options.index(current_patient["echo_status"]) if current_patient["echo_status"] in e_echo_options else 0
        up_echo_st = st.selectbox("Echocardiography Status", e_echo_options, index=e_echo_idx, key="up_ech_st")
        up_echo_res = st.text_area("Echo Result", value=current_patient["echo_result"], key="up_ech_res")
        up_echo_fu = st.number_input("Follow-up Echo (months)", min_value=0, value=int(current_patient["echo_followup_months"]), key="up_ech_fu")
        
        if st.button("Save Echo Details"):
            conn = get_db_connection()
            conn.execute("UPDATE patients SET echo_status=?, echo_result=?, echo_followup_months=? WHERE mrn=?", (up_echo_st, up_echo_res, up_echo_fu, current_patient["mrn"]))
            conn.commit()
            conn.close()
            st.success("Echocardiography details updated successfully!")
            st.rerun()

    img_df = current_patient["imaging"]
    if not img_df.empty:
        st.markdown("### Recorded Imaging & Echo Reports:")
        for idx, row in img_df.iterrows():
            col_i1, col_i2 = st.columns([5, 1])
            with col_i1:
                st.markdown(f"**[{row['img_type']}] {row['img_name']}** ({row['img_date']})\n> {row['img_result']}")
            with col_i2:
                if st.button("🗑️ Delete", key=f"del_img_{row['id']}"):
                    conn = get_db_connection()
                    conn.execute("DELETE FROM imaging WHERE id = ?", (row['id'],))
                    conn.commit()
                    conn.close()
                    st.success("Imaging record deleted successfully!")
                    st.rerun()
    else:
        st.info("No imaging or echo records found.")

with tab6:
    st.subheader("🩸 RBS Tracking")

    with st.expander("➕ Add RBS Measurement"):
        rbs_val = st.number_input("RBS Value (mmol/L or mg/dL)", min_value=0.0, max_value=30.0, value=4.5, key="rbs_val_input")
        rbs_date = st.date_input("Date", value=datetime.date.today(), key="rbs_date")
        rbs_hr = st.number_input("Hour (0-23)", min_value=0, max_value=23, value=12, key="rbs_hr")
        rbs_min = st.number_input("Minute (0-59)", min_value=0, max_value=59, value=0, key="rbs_min")
        
        if st.button("Save RBS Reading", key="save_rbs_btn"):
            rbs_time_str = f"{rbs_date} {str(rbs_hr).zfill(2)}:{str(rbs_min).zfill(2)}"
            conn = get_db_connection()
            conn.execute("INSERT INTO rbs_logs (mrn, rbs_val, rbs_time) VALUES (?, ?, ?)",
                         (current_patient["mrn"], rbs_val, rbs_time_str))
            conn.commit()
            conn.close()
            st.success("RBS reading recorded successfully!")
            st.rerun()

    rbs_df = current_patient["rbs"]
    if not rbs_df.empty:
        st.markdown("### Recorded RBS Logs:")
        for idx, row in rbs_df.iterrows():
            col_r1, col_r2 = st.columns([5, 1])
            with col_r1:
                st.text(f"ID: {row['id']} | Time: {row['rbs_time']} | Value: {row['rbs_val']}")
            with col_r2:
                if st.button("🗑️ Delete", key=f"del_rbs_{row['id']}"):
                    conn = get_db_connection()
                    conn.execute("DELETE FROM rbs_logs WHERE id = ?", (row['id'],))
                    conn.commit()
                    conn.close()
                    st.success("RBS record deleted successfully!")
                    st.rerun()
    else:
        st.info("No RBS records found.")

with tab7:
    st.subheader("📤 Shift Handover (Professional Confidential Medical Form)")
    
    anonymize_flag = st.checkbox("🔒 Anonymize Patient Identity", value=False, key="tab7_anon_checkbox")
    
    p_name = "[ANONYMIZED PATIENT]" if anonymize_flag else current_patient['baby_name']
    p_mrn = "[HIDDEN MRN]" if anonymize_flag else current_patient['mrn']
    
    labs_rows = ""
    if not current_patient["labs"].empty:
        for idx, r in current_patient["labs"].iterrows():
            labs_rows += f"<tr><td>{r['sample_datetime']} ({r['hours_elapsed']}h)</td><td>{r['test_name']}</td><td>{r['test_value']} {r['unit']}</td></tr>"
    else:
        labs_rows = "<tr><td colspan='3'>No labs recorded.</td></tr>"

    img_rows = ""
    if not current_patient["imaging"].empty:
        for idx, r in current_patient["imaging"].iterrows():
            img_rows += f"<tr><td>{r['img_date']}</td><td>{r['img_type']} - {r['img_name']}</td><td>{r['img_result']}</td></tr>"
    else:
        img_rows = "<tr><td colspan='3'>No imaging or echo recorded.</td></tr>"

    html_handover_report = f"""
    <div id="printable-handover-area" style="background-color: #ffffff; padding: 20px; border: 2px solid #000; color: #000;">
        <h3 style="text-align: center; margin-bottom: 5px;">NURSERY DEPARTMENT - SHIFT HANDOVER REPORT</h3>
        <p style="text-align: center; font-size: 11px; margin-top: 0;">Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | Unit: NURSERY</p>
        
        <table class="handover-table">
            <tr>
                <th colspan="4" style="background-color: #e6e6e6;">1. IDENTIFICATION & SITUATION</th>
            </tr>
            <tr>
                <td><b>Patient Name:</b> {p_name}</td>
                <td><b>MRN:</b> {p_mrn}</td>
                <td><b>Gender:</b> {current_patient['gender']}</td>
                <td><b>Gestational Age:</b> {current_patient['gestational_age']}</td>
            </tr>
            <tr>
                <td><b>Birth Weight:</b> {current_patient['birth_weight']}</td>
                <td><b>Birth Date/Time:</b> {current_patient['birth_date']}</td>
                <td><b>Patient Status:</b> {current_patient['status']}</td>
                <td><b>Consultant:</b> {current_patient['primary_physician']}</td>
            </tr>
            <tr>
                <td colspan="2"><b>Diagnosis & Delivery:</b> {current_patient['diagnosis']} ({current_patient['delivery_type']})</td>
                <td colspan="2"><b>Blood Groups:</b> Mother [{current_patient['mother_abo']} {current_patient['mother_rh']}] | Baby [{current_patient['baby_abo']} {current_patient['baby_rh']}] | DAT: [{current_patient['dat']}]</td>
            </tr>
        </table>

        <table class="handover-table">
            <tr>
                <th colspan="2" style="background-color: #e6e6e6;">2. BACKGROUND & MATERNAL HISTORY</th>
            </tr>
            <tr>
                <td><b>Booking & Obstetric:</b></td>
                <td>Gravida [{current_patient['gravida']}], Para [{current_patient['para']}], Abortion [{current_patient['abortion']}]</td>
            </tr>
            <tr>
                <td><b>Obstetric History:</b></td>
                <td>{current_patient['obs_history'] or 'None'}</td>
            </tr>
            <tr>
                <td><b>Family History:</b></td>
                <td>{current_patient['family_history'] or 'None'}</td>
            </tr>
            <tr>
                <td><b>Risk Factors:</b></td>
                <td>
                    - PROM: {current_patient['prom_status']} ({current_patient['prom_hours']}h {current_patient['prom_mins']}m)<br>
                    - Antibiotic: {current_patient['antibiotic_status']} - {current_patient['antibiotic_name']} ({current_patient['antibiotic_doses']} doses, {current_patient['antibiotic_treated']})<br>
                    - Pethidine: {current_patient['pethidine_status']} ({current_patient['pethidine_details']})<br>
                    - CTG: {current_patient['ctg_category']} - {current_patient['ctg_findings']}<br>
                    - HVS: {current_patient['hvs_status']} ({current_patient['hvs_organism']}, {current_patient['hvs_treated']})<br>
                    - GBS: {current_patient['gbs_status']} ({current_patient['gbs_site']}, {current_patient['gbs_treated']})<br>
                    - Hypothyroidism: {current_patient['hypothyroid_status']} ({current_patient['thyroxine_status']}, {current_patient['thyroxine_dose']})<br>
                    - Diabetes Mellitus: {current_patient['dm_status']} ({current_patient['dm_treatment']})<br>
                    - Other Maternal Diseases: {current_patient['maternal_diseases'] or 'None'}
                </td>
            </tr>
        </table>

        <table class="handover-table">
            <tr>
                <th colspan="2" style="background-color: #e6e6e6;">3. ASSESSMENT, FEEDING & MEDICATIONS</th>
            </tr>
            <tr>
                <td><b>Feeding Type:</b></td>
                <td>{current_patient['feeding_type']}</td>
            </tr>
            <tr>
                <td><b>Medications & Vaccines:</b></td>
                <td>Vit K [{current_patient['vit_k_status']}] | Hep B [{current_patient['hepb_status']}] | RSV [{current_patient['rsv_status']}]</td>
            </tr>
            <tr>
                <td><b>Screening Tests:</b></td>
                <td>CCHD [{current_patient['cchd_status']}] | Red Reflex [{current_patient['red_reflex_status']}] | Hearing [{current_patient['hearing_status']}]</td>
            </tr>
            <tr>
                <td><b>Management Plan:</b></td>
                <td>{current_patient['management_plan']}</td>
            </tr>
        </table>

        <table class="handover-table">
            <tr>
                <th colspan="3" style="background-color: #e6e6e6;">4. CUMULATIVE LABORATORY RESULTS</th>
            </tr>
            <tr>
                <th>Sample Time</th>
                <th>Test Name</th>
                <th>Result & Unit</th>
            </tr>
            {labs_rows}
        </table>

        <table class="handover-table">
            <tr>
                <th colspan="3" style="background-color: #e6e6e6;">5. RADIOLOGY, ULTRASOUND & ECHOCARDIOGRAPHY</th>
            </tr>
            <tr>
                <td colspan="3"><b>Echocardiography Status:</b> {current_patient['echo_status'] or 'Not requested'}<br>
                <b>Echo Result:</b> {current_patient['echo_result'] or 'N/A'} (Follow-up: {current_patient['echo_followup_months']} months)<br>
                <b>Consultations:</b> {current_patient['consultation_type'] or 'None'}</td>
            </tr>
            <tr>
                <th>Date</th>
                <th>Imaging Type</th>
                <th>Findings / Result</th>
            </tr>
            {img_rows}
        </table>

        <table class="handover-table">
            <tr>
                <th>6. NEXT LABS DUE</th>
            </tr>
            <tr>
                <td>{current_patient['next_labs_due']}</td>
            </tr>
        </table>
    </div>
    """

    st.markdown("### Report Preview (Professional Form Format):")
    # تم التعديل هنا لعرض الـ HTML بشكل صحيح ومقروء وليس ككود نصي
    st.markdown(html_handover_report, unsafe_allow_html=True)
    
    st.markdown("---")
    if st.button("🖨️ Print Report / Save as PDF securely", key="tab7_print_btn"):
        st.markdown("<script>window.print();</script>", unsafe_allow_html=True)
        st.info("Click your browser or tablet print option and select 'Save as PDF' to securely save the formatted handover report.")
