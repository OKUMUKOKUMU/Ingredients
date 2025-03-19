import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

def connect_to_gsheet(spreadsheet_name, sheet_name):
    """
    Authenticate and connect to Google Sheets.
    """
    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive.file", 
             "https://www.googleapis.com/auth/drive"]
    
    try:
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
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None

def load_data_from_google_sheet():
    """
    Load data from Google Sheets.
    """
    with st.spinner("Loading data from Google Sheets..."):
        try:
            worksheet = connect_to_gsheet(SPREADSHEET_NAME, SHEET_NAME)
            if worksheet is None:
                return None
            
            # Get all records from the Google Sheet
            data = worksheet.get_all_records()
            
            if not data:
                st.error("No data found in the Google Sheet.")
                return None

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
            current_year = datetime.now().year
            df = df[df["DATE"].dt.year >= current_year - 1]  # Data from last year onwards

            return df
        except Exception as e:
            st.error(f"Error loading data: {e}")
            return None

@st.cache_data(ttl=3600)  # Cache data for 1 hour
def get_cached_data():
    return load_data_from_google_sheet()

def calculate_proportion(df, identifier, department=None):
    """
    Calculate department-wise usage proportion.
    """
    if df is None:
        return None
    
    try:
        if identifier.isnumeric():
            filtered_df = df[df["ITEM_SERIAL"].astype(str).str.lower() == identifier.lower()]
        else:
            filtered_df = df[df["ITEM NAME"].str.lower() == identifier.lower()]

        if filtered_df.empty:
            return None

        # If department is specified, filter by department
        if department and department != "All Departments":
            filtered_df = filtered_df[filtered_df["DEPARTMENT"] == department]
            if filtered_df.empty:
                return None

        usage_summary = filtered_df.groupby("DEPARTMENT")["QUANTITY"].sum()
        total_usage = usage_summary.sum()
        
        if total_usage == 0:
            return None
            
        proportions = (usage_summary / total_usage) * 100
        proportions.sort_values(ascending=False, inplace=True)

        return proportions.reset_index()
    except Exception as e:
        st.error(f"Error calculating proportions: {e}")
        return None

def allocate_quantity(df, identifier, available_quantity, department=None):
    """
    Allocate quantity based on historical proportions.
    """
    proportions = calculate_proportion(df, identifier, department)
    if proportions is None:
        return None

    proportions["Allocated Quantity"] = (proportions["QUANTITY"] / 100) * available_quantity

    # Adjust to ensure the sum matches the input quantity
    allocated_sum = proportions["Allocated Quantity"].sum()
    if allocated_sum != available_quantity and len(proportions) > 0:
        difference = available_quantity - allocated_sum
        index_max = proportions["Allocated Quantity"].idxmax()
        proportions.at[index_max, "Allocated Quantity"] += difference

    proportions["Allocated Quantity"] = proportions["Allocated Quantity"].round(0)

    return proportions

# Streamlit UI
st.set_page_config(page_title="SPP Ingredients Allocation App", layout="wide")

st.markdown("""
    <style>
    .title {
        text-align: center;
        font-size: 46px;
        font-weight: bold;
        color: #FFC300;
        font-family: 'Amasis MT Pro', Arial, sans-serif;
        margin-bottom: 10px;
    }
    .subtitle {
        text-align: center;
        font-size: 18px;
        color: #6c757d;
        margin-bottom: 30px;
    }
    .footer {
        text-align: center;
        font-size: 14px;
        color: #888888;
        margin-top: 40px;
    }
    .stButton button {
        background-color: #FFC300;
        color: white;
        font-weight: bold;
    }
    .stButton button:hover {
        background-color: #E6B000;
    }
    .result-header {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='title'>SPP Ingredients Allocation App</h1>", unsafe_allow_html=True)
st.markdown("<p class='subtitle'>Efficiently allocate ingredient stock across departments based on historical usage</p>", unsafe_allow_html=True)

# Google Sheet credentials and details
SPREADSHEET_NAME = 'BROWNS STOCK MANAGEMENT'
SHEET_NAME = 'CHECK_OUT'

# Load the data
data = get_cached_data()

if data is None:
    st.error("Failed to load data from Google Sheets. Please check your connection and credentials.")
    st.stop()

# Extract unique item names and departments for auto-suggestions
unique_item_names = sorted(data["ITEM NAME"].unique().tolist())
unique_departments = sorted(["All Departments"] + data["DEPARTMENT"].unique().tolist())

# Create tabs for different functionalities
tab1, tab2 = st.tabs(["Allocation Calculator", "Data Overview"])

with tab1:
    # Form Layout for Better UX
    st.markdown("### Enter Items and Quantities")
    with st.form("allocation_form"):
        num_items = st.number_input("Number of items to allocate", min_value=1, max_value=10, step=1, value=1)
        
        # Department selection
        selected_department = st.selectbox("Filter by Department (optional)", unique_departments)

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
                result = allocate_quantity(data, identifier, available_quantity, selected_department)
                if result is not None:
                    st.markdown(f"<div class='result-header'><h3 style='color: #2E86C1;'>Allocation for {identifier}</h3></div>", unsafe_allow_html=True)
                    
                    # Format the output for better readability
                    formatted_result = result.rename(columns={"DEPARTMENT": "Department", "QUANTITY": "Proportion (%)"})
                    formatted_result["Proportion (%)"] = formatted_result["Proportion (%)"].round(2)
                    
                    # Display the result
                    st.dataframe(formatted_result, use_container_width=True)
                    
                    # Add a download button for the result
                    csv = formatted_result.to_csv(index=False)
                    st.download_button(
                        label="Download Allocation as CSV",
                        data=csv,
                        file_name=f"{identifier}_allocation.csv",
                        mime="text/csv",
                    )
                else:
                    st.error(f"Item {identifier} not found in historical data or has no usage data for the selected department!")

with tab2:
    st.markdown("### Data Overview")
    
    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        selected_items = st.multiselect("Filter by Items", unique_item_names, default=[])
    with col2:
        selected_overview_dept = st.multiselect("Filter by Departments", unique_departments[1:], default=[])  # Exclude "All Departments"
    
    # Apply filters
    filtered_data = data.copy()
    if selected_items:
        filtered_data = filtered_data[filtered_data["ITEM NAME"].isin(selected_items)]
    if selected_overview_dept:
        filtered_data = filtered_data[filtered_data["DEPARTMENT"].isin(selected_overview_dept)]
    
    # Show data overview
    st.markdown("#### Filtered Data Preview")
    st.dataframe(filtered_data[["DATE", "ITEM NAME", "DEPARTMENT", "QUANTITY", "UNIT_OF_MEASURE"]].head(100), use_container_width=True)
    
    # Simple statistics
    st.markdown("#### Usage Statistics")
    total_usage = filtered_data["QUANTITY"].sum()
    unique_items_count = filtered_data["ITEM NAME"].nunique()
    
    stat_col1, stat_col2, stat_col3 = st.columns(3)
    with stat_col1:
        st.metric("Total Quantity Used", f"{total_usage:,.2f}")
    with stat_col2:
        st.metric("Unique Items", f"{unique_items_count}")
    with stat_col3:
        st.metric("Total Transactions", f"{len(filtered_data):,}")

# Footnote
st.markdown("<p class='footer'> Developed by Brown's Data Team, ©2025 </p>", unsafe_allow_html=True)
