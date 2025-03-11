import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
import numpy as np
from datetime import datetime

# Load environment variables
load_dotenv()

# Configure page
st.set_page_config(page_title="SPP Ingredients Allocation App", layout="wide")

# Custom CSS for styling
st.markdown("""
<style>
    .main-header {text-align: center; color: #FFC300; margin-bottom: 20px;}
    .sub-header {margin-top: 15px; margin-bottom: 10px;}
    .highlight {background-color: #f0f2f6; padding: 10px; border-radius: 5px;}
    .footer {text-align: center; color: #888; font-size: 0.8em;}
</style>
""", unsafe_allow_html=True)

# Function to validate Google credentials
def validate_google_credentials():
    required_env_vars = [
        "GOOGLE_PROJECT_ID", "GOOGLE_PRIVATE_KEY_ID", "GOOGLE_PRIVATE_KEY",
        "GOOGLE_CLIENT_EMAIL", "GOOGLE_CLIENT_ID", "GOOGLE_AUTH_URI", 
        "GOOGLE_TOKEN_URI", "GOOGLE_AUTH_PROVIDER_X509_CERT_URL", "GOOGLE_CLIENT_X509_CERT_URL"
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        st.error(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        return False
    return True

# Cache function for Google Sheets connection
@st.cache_data(ttl=3600)
def load_data_from_google_sheet():
    if not validate_google_credentials():
        return pd.DataFrame()
        
    try:
        scope = ["https://spreadsheets.google.com/feeds", 
                'https://www.googleapis.com/auth/spreadsheets',
                "https://www.googleapis.com/auth/drive.file", 
                "https://www.googleapis.com/auth/drive"]
        
        credentials = {
            "type": "service_account",
            "project_id": os.getenv("GOOGLE_PROJECT_ID"),
            "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
            "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
        }

        client_credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials, scope)
        client = gspread.authorize(client_credentials)
        worksheet = client.open("BROWNS STOCK MANAGEMENT").worksheet("CHECK_OUT")
        
        data = worksheet.get_all_records()
        if not data:
            st.warning("⚠️ No data found in the spreadsheet!")
            return pd.DataFrame()
            
        df = pd.DataFrame(data)

        # Define expected columns
        expected_columns = ["DATE", "ITEM_SERIAL", "ITEM NAME", "Department", "ISSUED_TO", "QUANTITY", 
                            "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                            "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"]
        
        # Rename columns for consistency
        column_mapping = {
            "DEPARTMENT": "Department",
            "ISSUED_TO": "Sub_Department"
        }
        df.rename(columns=column_mapping, inplace=True)

        # Ensure all expected columns exist
        missing_columns = [col for col in expected_columns if col not in df.columns]
        for col in missing_columns:
            df[col] = np.nan  # Add missing columns with NaN

        # Reorder columns
        df = df[expected_columns]

        # Convert DATE column to datetime
        df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")

        # Convert QUANTITY to numeric and drop NaNs
        df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce")
        df.dropna(subset=["QUANTITY"], inplace=True)

        # Fill missing department and category fields
        df["Department"].fillna("Unspecified", inplace=True)
        df["DEPARTMENT_CAT"].fillna(df["Department"], inplace=True)
        df["ISSUED_TO"].fillna("Unspecified", inplace=True)

        # Add quarter and year columns
        df["QUARTER"] = df["DATE"].dt.to_period("Q")
        df["YEAR"] = df["DATE"].dt.year
        
        return df
        
    except Exception as e:
        st.error(f"❌ Error loading data: {str(e)}")
        return pd.DataFrame()

# Function to filter data by date
def filter_data_by_date_range(df, start_date, end_date):
    if df.empty:
        return df
        
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date) + pd.DateOffset(days=1) - pd.DateOffset(seconds=1)
    
    return df[(df["DATE"] >= start_date) & (df["DATE"] <= end_date)]

# Sidebar filters
st.sidebar.header("Filter Options")
start_date = st.sidebar.date_input("Start Date", value=datetime.today() - timedelta(days=30))
end_date = st.sidebar.date_input("End Date", value=datetime.today())

# Load data
df = load_data_from_google_sheet()

if df.empty:
    st.warning("⚠️ No data available to display!")
else:
    filtered_df = filter_data_by_date_range(df, start_date, end_date)

    # Display data in table format
    st.subheader("Filtered Data")
    st.dataframe(filtered_df)

    # Form for new entries
    with st.form("entry_form"):
        st.subheader("Add New Item Entry")
        col1, col2, col3 = st.columns(3)
        with col1:
            item_serial = st.text_input("Item Serial", "")
        with col2:
            item_name = st.text_input("Item Name", "")
        with col3:
            department = st.selectbox("Department", df["Department"].unique())

        col4, col5, col6 = st.columns(3)
        with col4:
            quantity = st.number_input("Quantity", min_value=1, step=1)
        with col5:
            unit_of_measure = st.selectbox("Unit of Measure", df["UNIT_OF_MEASURE"].unique())
        with col6:
            issued_to = st.text_input("Issued To", "")

        submit_button = st.form_submit_button("Submit Entry")

    if submit_button:
        if item_serial and item_name and quantity and issued_to:
            new_entry = {
                "DATE": datetime.today().strftime("%Y-%m-%d"),
                "ITEM_SERIAL": item_serial,
                "ITEM NAME": item_name,
                "Department": department,
                "ISSUED_TO": issued_to,
                "QUANTITY": quantity,
                "UNIT_OF_MEASURE": unit_of_measure
            }
            st.success("✅ New entry added successfully!")
        else:
            st.error("❌ Please fill in all required fields.")

# Footer
st.markdown('<p class="footer">SPP Ingredients Allocation App © 2024</p>', unsafe_allow_html=True)
