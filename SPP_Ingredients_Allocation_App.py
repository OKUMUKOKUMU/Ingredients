import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

def get_gsheet_client():
    """
    Authenticate and return the Google Sheets client.
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
    return gspread.authorize(client_credentials)

def connect_to_gsheet(client, spreadsheet_name, sheet_name):
    """
    Connect to a specific Google Sheet by name.
    """
    try:
        spreadsheet = client.open(spreadsheet_name)
        return spreadsheet.worksheet(sheet_name)
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None

@st.cache_data(ttl=300)
def load_data_from_google_sheet(client, spreadsheet_name, sheet_name):
    """
    Load data from Google Sheets and cache it for 1 hour.
    """
    try:
        worksheet = connect_to_gsheet(client, spreadsheet_name, sheet_name)
        if worksheet is None:
            return None
        
        data = worksheet.get_all_records()
        if not data:
            st.error("No data found in the Google Sheet.")
            return None

        df = pd.DataFrame(data)
        df.columns = ["DATE", "ITEM_SERIAL", "ITEM NAME", "DEPARTMENT", "ISSUED_TO", "QUANTITY", 
                      "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                      "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"]

        df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
        df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce")
        df.dropna(subset=["QUANTITY"], inplace=True)
        df["QUARTER"] = df["DATE"].dt.to_period("Q")

        current_year = datetime.now().year
        df = df[df["DATE"].dt.year >= current_year - 1]

        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None

def calculate_proportion(df, identifier, department=None):
    """
    Calculate department-wise usage proportion and subdepartment proportions within departments.
    """
    if df is None:
        return None
    
    try:
        filtered_df = df[df["ITEM NAME"].str.lower() == identifier.lower()] if not identifier.isnumeric() else df[df["ITEM_SERIAL"].astype(str).str.lower() == identifier.lower()]
        if filtered_df.empty:
            return None

        if department and department != "All Departments":
            filtered_df = filtered_df[filtered_df["DEPARTMENT"] == department]
            if filtered_df.empty:
                return None

        dept_usage = filtered_df.groupby("DEPARTMENT")["QUANTITY"].sum().reset_index()
        total_usage = dept_usage["QUANTITY"].sum()
        if total_usage == 0:
            return None
            
        dept_usage["DEPT_PROPORTION"] = (dept_usage["QUANTITY"] / total_usage) * 100
        dept_proportions = dict(zip(dept_usage["DEPARTMENT"], dept_usage["DEPT_PROPORTION"]))
        
        detailed_usage = filtered_df.groupby(["DEPARTMENT", "DEPARTMENT_CAT", "ISSUED_TO"])["QUANTITY"].sum().reset_index()
        detailed_usage["DEPT_PROPORTION"] = detailed_usage["DEPARTMENT"].map(dept_proportions)
        detailed_usage["PROPORTION"] = detailed_usage.groupby("DEPARTMENT")["QUANTITY"].transform(lambda x: (x / x.sum()) * 100)

        detailed_usage.sort_values(by=["DEPT_PROPORTION", "PROPORTION"], ascending=[False, False], inplace=True)
        
        return detailed_usage
    except Exception as e:
        st.error(f"Error calculating proportions: {e}")
        return None

def allocate_quantity(df, identifier, available_quantity, department=None):
    """
    Allocate quantity based on historical proportions.
    Drop departments with less than 1% proportion and redistribute their quantities.
    """
    proportions = calculate_proportion(df, identifier, department)
    if proportions is None:
        return None

    significant_proportions = proportions[proportions["DEPT_PROPORTION"].abs() >= 1.0]
    if significant_proportions.empty:
        significant_proportions = proportions.nlargest(1, "DEPT_PROPORTION")
    
    dept_sum = significant_proportions.groupby("DEPARTMENT")["DEPT_PROPORTION"].first().sum()
    if dept_sum > 0:
        normalize_factor = 100 / dept_sum
        significant_proportions["DEPT_PROPORTION_NORMALIZED"] = significant_proportions["DEPT_PROPORTION"] * normalize_factor
    else:
        significant_proportions["DEPT_PROPORTION_NORMALIZED"] = 0
    
    dept_allocation = significant_proportions.groupby("DEPARTMENT").agg({"DEPT_PROPORTION_NORMALIZED": "first"}).reset_index()
    dept_allocation["ALLOCATED_QUANTITY"] = (dept_allocation["DEPT_PROPORTION_NORMALIZED"] / 100) * available_quantity
    dept_allocations = dict(zip(dept_allocation["DEPARTMENT"], dept_allocation["ALLOCATED_QUANTITY"]))
    
    final_result = []
    for dept, group in significant_proportions.groupby("DEPARTMENT"):
        if dept in dept_allocations:
            dept_total_quantity = dept_allocations[dept]
            group["PROPORTION_NORMALIZED"] = group["PROPORTION"] / group["PROPORTION"].sum() * 100
            group["ALLOCATED_QUANTITY"] = (group["PROPORTION_NORMALIZED"] / 100) * dept_total_quantity
            final_result.append(group)
    
    if not final_result:
        return None
    
    final_result_df = pd.concat(final_result)
    final_result_df["ALLOCATED_QUANTITY"] = final_result_df["ALLOCATED_QUANTITY"].round(0).astype(int)
    
    total_allocated = final_result_df["ALLOCATED_QUANTITY"].sum()
    if total_allocated != available_quantity and len(final_result_df) > 0:
        difference = int(available_quantity - total_allocated)
        if difference != 0:
            index_max = final_result_df["ALLOCATED_QUANTITY"].idxmax()
            final_result_df.at[index_max, "ALLOCATED_QUANTITY"] += difference
    
    return final_result_df

# Streamlit UI
st.set_page_config(
    page_title="SPP Ingredients Allocation App", 
    layout="centered",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .title {
        text-align: center;
        font-size: 32px;
        font-weight: bold;
        color: #FFC300;
        font-family: 'Amasis MT Pro', Arial, sans-serif;
        margin-bottom: 5px;
    }
    .subtitle {
        text-align: center;
        font-size: 16px;
        color: #6c757d;
        margin-bottom: 20px;
    }
    .footer {
        text-align: center;
        font-size: 12px;
        color: #888888;
        margin-top: 30px;
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
        padding: 8px;
        border-radius: 5px;
        margin-bottom: 8px;
    }
    .card {
        background-color: #ffffff;
        border-radius: 10px;
        padding: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("<h2 class='title'>SPP Ingredients Allocation</h2>", unsafe_allow_html=True)
    st.markdown("<p class='subtitle'>Allocation Settings</p>", unsafe_allow_html=True)
    
    SPREADSHEET_NAME = 'BROWNS STOCK MANAGEMENT'
    SHEET_NAME = 'CHECK_OUT'
    
    client = get_gsheet_client()
    data = load_data_from_google_sheet(client, SPREADSHEET_NAME, SHEET_NAME)
    
    if data is None:
        st.error("Failed to load data from Google Sheets. Please check your connection and credentials.")
        st.stop()
    
    unique_item_names = sorted(data["ITEM NAME"].unique().tolist())
    unique_departments = sorted(["All Departments"] + data["DEPARTMENT"].unique().tolist())
    
    st.markdown("### Quick Stats")
    st.metric("Total Items", f"{len(unique_item_names)}")
    st.metric("Total Departments", f"{len(unique_departments) - 1}")
    
    st.markdown("---")
    st.markdown("### View Options")
    view_mode = st.radio("Select View", ["Allocation Calculator", "Data Overview"])
    
    st.markdown("### Display Options")
    sub_dept_source = st.radio("Sub-Department Source", ["DEPARTMENT_CAT", "ISSUED_TO"])
    
    st.markdown("---")
    st.markdown("<p class='footer'>Developed by Brown's Data Team, ©2025</p>", unsafe_allow_html=True)

# Main content
st.markdown("<h1 class='title'>SPP Ingredients Allocation App</h1>", unsafe_allow_html=True)

if view_mode == "Allocation Calculator":
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### Enter Items and Quantities")
    
    with st.form("allocation_form"):
        num_items = st.number_input("Number of items to allocate", min_value=1, max_value=10, step=1, value=1)
        
        selected_department = st.selectbox("Filter by Department (optional)", unique_departments)

        entries = []
        for i in range(num_items):
            st.markdown(f"**Item {i+1}**")
            col1, col2 = st.columns([2, 1])
            with col1:
                identifier = st.selectbox(f"Select item {i+1}", unique_item_names, key=f"item_{i}")
            with col2:
                available_quantity = st.number_input(f"Quantity:", min_value=0.1, step=0.1, key=f"qty_{i}")

            if identifier and available_quantity > 0:
                entries.append((identifier, available_quantity))

        submitted = st.form_submit_button("Calculate Allocation")
    st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        if not entries:
            st.warning("Please enter at least one valid item and quantity!")
        else:
            for identifier, available_quantity in entries:
                result = allocate_quantity(data, identifier, available_quantity, selected_department)
                if result is not None:
                    st.markdown("<div class='card'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-header'><h3 style='color: #2E86C1;'>Allocation for {identifier}</h3></div>", unsafe_allow_html=True)
                    
                    total_allocated = result["ALLOCATED_QUANTITY"].sum()
                    st.markdown(f"**Total Allocated: {total_allocated:.0f}** (Input: {available_quantity:.0f})")
                    
                    sub_dept_col = sub_dept_source
                    formatted_result = result[["DEPARTMENT", sub_dept_col, "PROPORTION_NORMALIZED", "ALLOCATED_QUANTITY"]].copy()
                    formatted_result = formatted_result.rename(columns={
                        "DEPARTMENT": "Department", 
                        sub_dept_col: "Sub Department", 
                        "PROPORTION_NORMALIZED": "Proportion (%)",
                        "ALLOCATED_QUANTITY": "Allocated Quantity"
                    })
                    
                    formatted_result["Proportion (%)"] = formatted_result["Proportion (%)"].round(2)
                    st.dataframe(formatted_result, use_container_width=True)
                    
                    st.markdown("#### Allocation Summary")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Allocated", f"{formatted_result['Allocated Quantity'].sum():,.0f}")
                    with col2:
                        st.metric("Departments", f"{formatted_result['Department'].nunique()}")
                    with col3:
                        st.metric("Sub-Departments", f"{formatted_result['Sub Department'].nunique()}")
                    
                    csv = formatted_result.to_csv(index=False)
                    st.download_button(
                        label="Download Allocation as CSV",
                        data=csv,
                        file_name=f"{identifier}_allocation.csv",
                        mime="text/csv",
                    )
                    
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.error(f"Item {identifier} not found in historical data or has no usage data for the selected department!")

elif view_mode == "Data Overview":
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### Data Overview")
    
    col1, col2 = st.columns(2)
    with col1:
        selected_items = st.multiselect("Filter by Items", unique_item_names, default=[])
    with col2:
        selected_overview_dept = st.multiselect("Filter by Departments", unique_departments[1:], default=[])
    
    filtered_data = data.copy()
    if selected_items:
        filtered_data = filtered_data[filtered_data["ITEM NAME"].isin(selected_items)]
    if selected_overview_dept:
        filtered_data = filtered_data[filtered_data["DEPARTMENT"].isin(selected_overview_dept)]
    
    sub_dept_col = sub_dept_source
    st.markdown("#### Filtered Data Preview")
    display_columns = ["DATE", "ITEM NAME", "DEPARTMENT", sub_dept_col, "QUANTITY", "UNIT_OF_MEASURE"]
    st.dataframe(filtered_data[display_columns].head(100), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='card'>", unsafe_allow_html=True)
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
    
    st.markdown("</div>", unsafe_allow_html=True)
