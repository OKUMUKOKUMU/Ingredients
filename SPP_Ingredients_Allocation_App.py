import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def connect_to_gsheet(creds_file, spreadsheet_name, sheet_name):
    """
    Authenticate and connect to Google Sheets.
    """
    scope = ["https://spreadsheets.google.com/feeds", 
             'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", 
             "https://www.googleapis.com/auth/drive"]
    
    credentials = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
    client = gspread.authorize(credentials)
    spreadsheet = client.open(spreadsheet_name)  
    return spreadsheet.worksheet(sheet_name)  # Access specific sheet by name

def load_data_from_google_sheet():
    """
    Load data from Google Sheets.
    """
    worksheet = connect_to_gsheet(CREDENTIALS_FILE, SPREADSHEET_NAME, SHEET_NAME)
    
    data = worksheet.get_all_records()

    df = pd.DataFrame(data)
    df.columns = ["DATE", "ITEM_SERIAL", "ITEM NAME", "ISSUED_TO", "QUANTITY", 
                  "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                  "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"]
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce")
    df.dropna(subset=["QUANTITY"], inplace=True)
    df["QUARTER"] = df["DATE"].dt.to_period("Q")

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

    allocated_sum = proportions["Allocated Quantity"].sum()
    if allocated_sum != available_quantity:
        difference = available_quantity - allocated_sum
        index_max = proportions["Allocated Quantity"].idxmax()
        proportions.at[index_max, "Allocated Quantity"] += difference

    proportions["Allocated Quantity"] = proportions["Allocated Quantity"].round(0)

    return proportions

st.markdown("""
    <style>
    .title {
        text-align: center;
        font-size: 46px;
        font-weight: bold;
        color: #FFC300; /* Cheese color */
        font-family: 'Amasis MT Pro', Arial, sans-serif;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='title'> SPP Ingredients Allocation App </h1>", unsafe_allow_html=True)

SPREADSHEET_NAME = 'BROWNS STOCK MANAGEMENT'
SHEET_NAME = 'CHECK_OUT'
CREDENTIALS_FILE = 'credentials.json'

data = load_data_from_google_sheet()

unique_item_names = data["ITEM NAME"].unique().tolist()
identifier = st.selectbox("Enter Item Serial or Name:", unique_item_names)
available_quantity = st.number_input("Enter Available Quantity:", min_value=0.0, step=0.1)

if st.button("Calculate Allocation"):
    if identifier and available_quantity > 0:
        result = allocate_quantity(data, identifier, available_quantity)
        if result is not None:
            st.markdown("<div style='text-align: center;'><h3>Allocation Per Department</h3></div>", unsafe_allow_html=True)
            st.dataframe(result.rename(columns={"DEPARTMENT_CAT": "Department", "QUANTITY": "Proportion (%)"}), use_container_width=True)
        else:
            st.error("Item not found in historical data!")
    else:
        st.warning("Please enter a valid item serial/name and quantity.")

st.markdown("<p style='text-align: center; font-size: 14px;'> Developed by Brown's Data Team,©2025 </p>", unsafe_allow_html=True)
