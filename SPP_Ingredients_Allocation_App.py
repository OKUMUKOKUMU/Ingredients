import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

# Load Google Sheets credentials
def connect_to_gsheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict({
        "type": "service_account",
        "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("GOOGLE_CLIENT_EMAIL")
    }, scope)
    return gspread.authorize(creds).open("BROWNS STOCK MANAGEMENT").worksheet("CHECK_OUT")

# Load data
def load_data():
    ws = connect_to_gsheet()
    df = pd.DataFrame(ws.get_all_records())
    df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce")
    df.dropna(subset=["QUANTITY"], inplace=True)
    return df

# Calculate allocation
def allocate_quantity(df, item, qty, dept):
    df = df[df["ITEM NAME"].str.contains(item, case=False, na=False)]
    if dept != "All Departments":
        df = df[df["DEPARTMENT"] == dept]
    if df.empty:
        return None
    proportions = df.groupby("DEPARTMENT")["QUANTITY"].sum()
    proportions = (proportions / proportions.sum()) * qty
    return proportions.reset_index(name="ALLOCATED_QUANTITY")

# Streamlit UI
st.set_page_config(page_title="SPP Ingredients Allocation App", layout="centered")
st.title("SPP Ingredients Allocation App")
data = load_data()

item = st.selectbox("Select Item", sorted(data["ITEM NAME"].unique()))
qty = st.number_input("Enter Quantity", min_value=1, step=1)
dept = st.selectbox("Select Department", ["All Departments"] + sorted(data["DEPARTMENT"].unique()))

if st.button("Calculate Allocation"):
    result = allocate_quantity(data, item, qty, dept)
    if result is not None:
        st.write("### Allocation Results")
        st.dataframe(result)
        csv = result.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, "allocation.csv", "text/csv")
    else:
        st.error("No data found for allocation.")
