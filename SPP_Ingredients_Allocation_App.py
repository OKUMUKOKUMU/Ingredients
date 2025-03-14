import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def connect_to_gsheet(creds_file, spreadsheet_name, sheet_name):
    """
    Authenticate and connect to Google Sheets.
    """
    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/spreadsheets",
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
    spreadsheet = client.open(spreadsheet_name)  
    return spreadsheet.worksheet(sheet_name)  # Access specific sheet by name

def load_data_from_google_sheet():
    """
    Load data from Google Sheets.
    """
    worksheet = connect_to_gsheet(CREDENTIALS_FILE, SPREADSHEET_NAME, SHEET_NAME)
    
    # Get all records from the Google Sheet
    data = worksheet.get_all_records()

    # Convert data to DataFrame
    df = pd.DataFrame(data)

    # Ensure columns match the updated Google Sheets structure
    df.columns = ["DATE", "ITEM_SERIAL", "ITEM NAME", "DEPARTMENT", "ISSUED_TO", "QUANTITY", 
                  "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                  "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"]

    # Convert date and numeric columns
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce")
    df.dropna(subset=["QUANTITY"], inplace=True)
    
    # Extract quarter information
    df["QUARTER"] = df["DATE"].dt.to_period("Q")

    # Filter data for 2024 onwards
    df = df[df["DATE"].dt.year >= 2024]

    return df

def calculate_proportion(df, identifier):
    """
    Calculate department-wise usage proportion.
    """
    if identifier.isnumeric():
        filtered_df = df[df["ITEM_SERIAL"].astype(str).str.lower() == identifier.lower()]
    else:
        filtered_df = df[df["ITEM NAME"].str.lower() == identifier.lower()]

    if filtered_df.empty:
        return None

    usage_summary = filtered_df.groupby("DEPARTMENT_CAT")["QUANTITY"].sum()
    total_usage = usage_summary.sum()
    proportions = (usage_summary / total_usage) * 100
    proportions.sort_values(ascending=False, inplace=True)

    return proportions.reset_index()

def allocate_quantity(df, identifier, available_quantity):
    """
    Allocate quantity based on historical proportions.
    """
    proportions = calculate_proportion(df, identifier)
    if proportions is None:
        return None

    proportions["Allocated Quantity"] = (proportions["QUANTITY"] / 100) * available_quantity

    # Adjust to ensure the sum matches the input quantity
    allocated_sum = proportions["Allocated Quantity"].sum()
    if allocated_sum != available_quantity:
        difference = available_quantity - allocated_sum
        index_max = proportions["Allocated Quantity"].idxmax()
        proportions.at[index_max, "Allocated Quantity"] += difference

    proportions["Allocated Quantity"] = proportions["Allocated Quantity"].round(0)

    return proportions

# Streamlit UI
st.markdown("""
    <style>
    .title {
        text-align: center;
        font-size: 46px;
        font-weight: bold;
        color: #FFC300;
        font-family: 'Amasis MT Pro', Arial, sans-serif;
    }
    .subtitle {
        text-align: center;
        font-size: 18px;
        color: #6c757d;
    }
    .footer {
        text-align: center;
        font-size: 14px;
        color: #888888;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='title'>SPP Ingredients Allocation App</h1>", unsafe_allow_html=True)
st.markdown("<p class='subtitle'>Efficiently allocate ingredient stock across departments based on historical usage</p>", unsafe_allow_html=True)

# Google Sheet credentials and details
SPREADSHEET_NAME = 'BROWNS STOCK MANAGEMENT'
SHEET_NAME = 'CHECK_OUT'
CREDENTIALS_FILE = 'credentials.json'

# Load the data
data = load_data_from_google_sheet()

# Extract unique item names for auto-suggestions
unique_item_names = data["ITEM NAME"].unique().tolist()

# Form Layout for Better UX
st.markdown("### Enter Items and Quantities")
with st.form("allocation_form"):
    num_items = st.number_input("Number of items to allocate", min_value=1, max_value=10, step=1, value=1)

    entries = []
    for i in range(num_items):
        st.markdown(f"**Item {i+1}**")
        col1, col2 = st.columns([2, 1])
        with col1:
            identifier = st.selectbox(f"Select item {i+1}", unique_item_names, key=f"item_{i}")
        with col2:
            available_quantity = st.number_input(f"Quantity for {identifier}:", min_value=0.1, step=0.1, key=f"qty_{i}")

        if identifier and available_quantity > 0:
            entries.append((identifier, available_quantity))

    submitted = st.form_submit_button("Calculate Allocation")

# Processing Allocation
if submitted:
    if not entries:
        st.warning("Please enter at least one valid item and quantity!")
    else:
        for identifier, available_quantity in entries:
            result = allocate_quantity(data, identifier, available_quantity)
            if result is not None:
                st.markdown(f"<h3 style='color: #2E86C1;'>Allocation for {identifier}</h3>", unsafe_allow_html=True)
                st.dataframe(result.rename(columns={"DEPARTMENT_CAT": "Department", "QUANTITY": "Proportion (%)"}), use_container_width=True)
            else:
                st.error(f"Item {identifier} not found in historical data!")

# Footnote
st.markdown("<p class='footer'> Developed by Brown's Data Team, ©2025 </p>", unsafe_allow_html=True)
