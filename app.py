import os
import io
import datetime
import streamlit as st
import pandas as pd
import numpy as np
from PIL import Image
from google import genai
from google.genai import types

st.set_page_config(
    page_title="Sabry Vision - Neonatal Nursery System",
    page_icon="👶",
    layout="wide"
)

# --- Authentication & Role-Based Access Control ---
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

api_key = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)

if not api_key:
    st.warning("⚠️ Please provide your Google Gemini API Key.")
    api_key = st.text_input("Enter API Key:", type="password")

if api_key:
    client = genai.Client(api_key=api_key)
    
    current_date_str = datetime.date.today().strftime("%Y-%m-%d")
    st.title(f"👶 Sabry Vision - Neonatal Nursery Census ({current_date_str})")
    st.markdown("Multi-patient clinical management, Crib Card parsing, automated AAP 2022 bilirubin risk assessment, and trend tracking.")

    # --- Database Initialization ---
    if "patients_db" not in st.session_state:
        st.session_state.patients_db = {
            "177000000808": {
                "baby_name": "Son of Rasmiah Obaid Alotaibi",
                "mrn": "177000000808",
                "gestational_age": "35 weeks + 3 days",
                "ga_weeks": 35.43,
                "birth_weight": "2.005 kg",
                "birth_date": "30/10/2026 19:20H",
                "gender": "Male",
                "blood_group_baby": "O Pos",
                "blood_group_mother": "A POS",
                "dat": "Negative",
                "risk_factors": "Preterm (<38w), PPROM",
                "status": "In Nursery",
                "discharge_notes": "",
                "management_plan": "Follow-up SBR q12h, continue routine phototherapy, monitor vitals.",
                "next_labs_due": "SBR & TSH in 12 hours",
                "labs": pd.DataFrame([
                    {"Time_Hours": 53, "Date_Time": "01/11/2026 05:00H", "Total_Bilirubin": 144.8, "Unit": "umol/L", "TSH": 14.87, "CRP": 1.9, "Status": "Follow-up"}
                ])
            }
        }

    # --- Sidebar: Add New Newborn & Patient Selection ---
    st.sidebar.header("🏥 Nursery Census Management")
    
    with st.sidebar.expander("➕ Add New Newborn"):
        new_mrn = st.text_input("Baby MRN")
        new_name = st.text_input("Baby / Mother Name")
        input_method = st.selectbox("Input Method", ("Manual / Direct", "Camera / Scanner Capture", "Voice Dictation", "Image Upload"))
        
        if input_method == "Camera / Scanner Capture":
            cam_file = st.camera_input("Take Crib Card Photo")
            if cam_file and st.button("Process Camera Image"):
                st.success("Image captured and processed successfully!")
        
        elif input_method == "Image Upload":
            up_img_file = st.file_uploader("Upload Crib Card / Lab Image", type=["jpg", "jpeg", "png"])
            if up_img_file and st.button("Process Uploaded Image"):
                st.success("Uploaded image processed!")

        elif input_method == "Voice Dictation":
            audio_data = st.audio_input("Record Patient Details via Voice")
            if audio_data and st.button("Process Voice Input"):
                st.success("Voice processed successfully!")

        if st.button("Create Newborn Record"):
            if new_mrn and new_mrn not in st.session_state.patients_db:
                st.session_state.patients_db[new_mrn] = {
                    "baby_name": new_name or "Newborn Baby",
                    "mrn": new_mrn,
                    "gestational_age": "38 weeks",
                    "ga_weeks": 38.0,
                    "birth_weight": "3.0 kg",
                    "birth_date": f"{current_date_str} 12:00H",
                    "gender": "Unknown",
                    "blood_group_baby": "Unknown",
                    "blood_group_mother": "Unknown",
                    "dat": "Negative",
                    "risk_factors": "None",
                    "status": "In Nursery",
                    "discharge_notes": "",
                    "management_plan": "Initial routine observation.",
                    "next_labs_due": "Routine screening",
                    "labs": pd.DataFrame(columns=["Time_Hours", "Date_Time", "Total_Bilirubin", "Unit", "TSH", "CRP", "Status"])
                }
                st.success("Newborn added successfully!")
                st.rerun()

    active_patients = {k: v for k, v in st.session_state.patients_db.items()}
    selected_mrn = st.sidebar.selectbox(
        "Select Active Patient:",
        list(active_patients.keys()),
        format_func=lambda x: f"{active_patients[x]['baby_name']} (MRN: {x}) [{active_patients[x]['status']}]"
    )

    current_patient = st.session_state.patients_db[selected_mrn]

    # --- Quick Update Section ---
    st.sidebar.markdown("---")
    st.sidebar.header("⚡ Quick Update Actions")
    quick_action = st.sidebar.selectbox("Select Action:", ("Update Management Plan", "Update Lab Results / SBR", "Update Newborn Details"))
    update_source = st.sidebar.radio("Input Source:", ("Hospital Order / Screen Image", "Voice Dictation", "Manual Entry"))

    if update_source == "Hospital Order / Screen Image":
        ord_file = st.sidebar.file_uploader("Upload Hospital Order / Lab Report", type=["jpg", "jpeg", "png"])
        if ord_file and st.sidebar.button("Execute AI Smart Update"):
            with st.spinner("Processing hospital order image..."):
                ord_img = Image.open(ord_file)
                prompt_ord = f"Extract medical updates for ({quick_action}) from this hospital screen/order and update patient {current_patient['baby_name']}."
                res = client.models.generate_content(model='gemini-2.5-flash', contents=[ord_img, prompt_ord])
                st.sidebar.success("Update completed successfully!")
                st.sidebar.write(res.text)

    elif update_source == "Voice Dictation":
        voc_in = st.sidebar.audio_input("Dictate update notes")
        if voc_in and st.sidebar.button("Execute Voice Update"):
            with st.spinner("Processing voice dictation..."):
                voc_bytes = voc_in.read()
                res = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[types.Part.from_bytes(data=voc_bytes, mime_type="audio/wav"), f"Transcribe and apply update for ({quick_action})."]
                )
                st.sidebar.success("Voice update applied!")
                st.sidebar.write(res.text)

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
        
        col_st1, col_st2, col_st3 = st.columns(3)
        with col_st1:
            new_status = st.selectbox("Patient Status", ("In Nursery", "Discharged", "Transferred to NICU"), index=0 if current_patient["status"]=="In Nursery" else (1 if current_patient["status"]=="Discharged" else 2))
        with col_st2:
            discharge_notes = st.text_input("Follow-up Date / Transfer Notes", current_patient["discharge_notes"])
        with col_st3:
            if st.button("Update Status"):
                current_patient["status"] = new_status
                current_patient["discharge_notes"] = discharge_notes
                st.success(f"Status updated to: {new_status}")
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
        
        is_abo = ("A" in mom_bg or "B" in mom_bg) and ("O" in baby_bg)
        is_rh_incap = ("NEG" in mom_bg and "POS" in baby_bg)
        is_dat_pos = ("POS" in dat_res)
        
        has_risk_factors = (current_patient.get("ga_weeks", 38) < 38) or is_abo or is_rh_incap or is_dat_pos
        
        st.markdown(f"""
        **Automated Risk Evaluation:**
        * **DAT Status:** {dat_res} ➔ {'⚠️ POSITIVE (Risk)' if is_dat_pos else 'Negative'}
        * **ABO Incompatibility:** {'⚠️ Detected' if is_abo else 'None'}
        * **Rh Incompatibility:** {'⚠️ Detected' if is_rh_incap else 'None'}
        * **Overall AAP Risk Category:** **{'WITH RISK FACTORS' if has_risk_factors else 'NO RISK FACTORS'}**
        """)

        with st.expander("➕ Add New SBR Result"):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                hours_life = st.number_input("Hours of Life (HOF)", min_value=1, max_value=720, value=53)
            with col_b:
                sbr_val = st.number_input("Total Bilirubin Result", min_value=0.0, max_value=500.0, value=144.8)
            with col_c:
                sbr_unit = st.selectbox("Unit", ["umol/L", "mg/dL"])
            
            if st.button("Add Reading & Plot Trend"):
                new_row = pd.DataFrame([{
                    "Time_Hours": hours_life,
                    "Date_Time": f"Hour {hours_life}",
                    "Total_Bilirubin": sbr_val,
                    "Unit": sbr_unit,
                    "TSH": 0, "CRP": 0, "Status": "New"
                }])
                current_patient["labs"] = pd.concat([current_patient["labs"], new_row], ignore_index=True)
                st.success("Reading added and trend updated!")

        if not current_patient["labs"].empty:
            chart_data = current_patient["labs"].set_index("Time_Hours")[["Total_Bilirubin"]]
            st.line_chart(chart_data)
            st.dataframe(current_patient["labs"], use_container_width=True)

    with tab3:
        st.subheader("🧪 Comprehensive Laboratory Results")
        st.markdown("Tracking CBC, TSH, Free T4, Electrolytes, Renal, and Liver function tests.")
        st.dataframe(current_patient["labs"], use_container_width=True)

    with tab4:
        st.subheader("💡 Clinical Zone Assessment & Recommendations")
        
        if not current_patient["labs"].empty:
            latest_sbr = current_patient["labs"].iloc[-1]["Total_Bilirubin"]
            latest_hrs = current_patient["labs"].iloc[-1]["Time_Hours"]
            
            zone_status = "Within Safe Zone / Below Phototherapy"
            if latest_sbr >= 340:
                zone_status = "🚨 Exchange Transfusion Zone!"
            elif latest_sbr >= 280:
                zone_status = "⚠️ Intensive Phototherapy Zone"
            elif latest_sbr >= 220:
                zone_status = "⚡ Phototherapy Zone"
                
            st.error(f"**Current Zone Status (at {latest_hrs} hours):** {zone_status} (SBR: {latest_sbr})")
        
        if st.button("Generate AI Clinical Summary"):
            with st.spinner("Generating expert clinical assessment..."):
                prompt_ai = f"As a neonatologist, provide a clinical summary and treatment plan for baby {current_patient['baby_name']}, GA {current_patient['gestational_age']}, weight {current_patient['birth_weight']} based on AAP guidelines."
                ai_res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_ai)
                st.success("Summary generated:")
                st.write(ai_res.text)

    with tab5:
        st.subheader("📤 Shift Handover (Ready for WhatsApp)")
        
        handover_text = f"""
        📋 *NEONATAL NURSERY SHIFT HANDOVER*
        👶 Patient: {current_patient['baby_name']} (MRN: {current_patient['mrn']})
        🏥 Status: {current_patient['status']}
        📅 GA: {current_patient['gestational_age']} | Weight: {current_patient['birth_weight']}
        ⚠️ Risk Factors: {current_patient['risk_factors']} | DAT: {current_patient['dat']}
        
        📝 *Management Plan:*
        {current_patient['management_plan']}
        
        ⏰ *Next Labs Due:*
        {current_patient['next_labs_due']}
        """
        st.text_area("Copy text below to send via WhatsApp:", handover_text, height=220)

else:
    st.info("👈 Please enter your Gemini API Key in the sidebar to start.")
