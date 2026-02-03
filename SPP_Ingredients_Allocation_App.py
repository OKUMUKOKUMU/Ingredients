import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime
import plotly.express as px
from collections import Counter

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
    Load data from Google Sheets with exact header matching.
    """
    with st.spinner("Loading data from Google Sheets..."):
        try:
            worksheet = connect_to_gsheet(SPREADSHEET_NAME, SHEET_NAME)
            if worksheet is None:
                return None
            
            # Get all values from the Google Sheet
            all_values = worksheet.get_all_values()
            
            if not all_values or len(all_values) <= 1:  # Only headers or empty
                st.error("No data found in the Google Sheet.")
                return None
            
            # Get headers (first row)
            headers = all_values[0]
            
            # Debug: Show what headers we found
            st.sidebar.info(f"Found {len(headers)} columns in Google Sheet")
            
            # Make headers unique if there are duplicates
            seen = Counter()
            unique_headers = []
            for header in headers:
                clean_header = header.strip()
                if not clean_header:  # Skip empty headers
                    clean_header = f"Empty_Column_{len(unique_headers) + 1}"
                
                if clean_header in seen:
                    seen[clean_header] += 1
                    unique_headers.append(f"{clean_header}_{seen[clean_header]}")
                else:
                    seen[clean_header] = 1
                    unique_headers.append(clean_header)
            
            # Create DataFrame with unique headers
            data_rows = all_values[1:]
            df = pd.DataFrame(data_rows, columns=unique_headers)
            
            # Debug: Show column mapping
            st.sidebar.write("Column mapping:")
            for i, col in enumerate(unique_headers, 1):
                st.sidebar.write(f"{i}. '{col}'")
            
            # Map to your expected column names - based on your exact headers
            column_mapping = {}
            
            # Based on your headers: DATE, ITEM_SERIAL, ITEM_NAME, DEPARTMENT, ISSUED_TO, QUANTITY, UNIT_OF_MEASURE, ITEM_CATEGORY, WEEK, REFERENCE, DEPARTMENT_CAT, BATCH NO., STORE, RECEIVED BY
            
            # Create mapping based on exact or similar names
            expected_columns = [
                "DATE", "ITEM_SERIAL", "ITEM_NAME", "DEPARTMENT", "ISSUED_TO", 
                "QUANTITY", "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"
            ]
            
            # Try to find each expected column
            found_columns = []
            for expected in expected_columns:
                found = False
                
                # Try exact match first
                for actual in unique_headers:
                    if actual.strip() == expected.strip():
                        column_mapping[actual] = expected
                        found_columns.append(expected)
                        found = True
                        break
                
                # Try case-insensitive match
                if not found:
                    for actual in unique_headers:
                        if actual.strip().lower() == expected.strip().lower():
                            column_mapping[actual] = expected
                            found_columns.append(expected)
                            found = True
                            break
                
                # Try removing underscores and spaces
                if not found:
                    clean_expected = expected.replace("_", " ").replace(".", "").strip().lower()
                    for actual in unique_headers:
                        clean_actual = actual.replace("_", " ").replace(".", "").strip().lower()
                        if clean_actual == clean_expected:
                            column_mapping[actual] = expected
                            found_columns.append(expected)
                            found = True
                            break
                
                # If still not found, check for partial match
                if not found:
                    for actual in unique_headers:
                        if expected.lower() in actual.lower() or actual.lower() in expected.lower():
                            column_mapping[actual] = expected
                            found_columns.append(expected)
                            found = True
                            break
                
                # If column not found at all, create empty column
                if not found:
                    st.warning(f"Column '{expected}' not found. Creating empty column.")
                    df[expected] = None
                    found_columns.append(expected)
            
            # Rename columns based on mapping
            if column_mapping:
                df = df.rename(columns=column_mapping)
            
            # Ensure we have all expected columns
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = None
            
            # Clean the data
            # Convert DATE column
            df["DATE"] = pd.to_datetime(df["DATE"], format='%d/%m/%Y', errors='coerce')
            
            # Clean QUANTITY column - remove any non-numeric characters
            df["QUANTITY"] = pd.to_numeric(df["QUANTITY"].astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce')
            
            # Remove rows with invalid quantities
            df = df.dropna(subset=["QUANTITY"])
            
            # Clean ITEM_NAME column
            df["ITEM_NAME"] = df["ITEM_NAME"].astype(str).str.strip()
            
            # Clean DEPARTMENT column
            df["DEPARTMENT"] = df["DEPARTMENT"].astype(str).str.strip()
            
            # Extract quarter information
            df["QUARTER"] = df["DATE"].dt.to_period("Q")
            
            # Filter data for current and previous year
            current_year = datetime.now().year
            df = df[df["DATE"].dt.year >= current_year - 1]
            
            # Show summary in sidebar
            st.sidebar.success(f"✅ Loaded {len(df)} records")
            st.sidebar.info(f"📅 Date range: {df['DATE'].min().strftime('%d/%m/%Y')} to {df['DATE'].max().strftime('%d/%m/%Y')}")
            
            return df
            
        except Exception as e:
            st.error(f"Error loading data: {str(e)}")
            # Show more detailed error
            import traceback
            st.error(f"Traceback: {traceback.format_exc()}")
            return None

@st.cache_data(ttl=3600)  # Cache data for 1 hour
def get_cached_data():
    return load_data_from_google_sheet()

def calculate_proportion(df, identifier, department=None, min_proportion=1.0):
    """
    Calculate department-wise usage proportion without subdepartment details.
    Ensures all departments sum to 100%.
    Filters out departments with proportions less than min_proportion.
    """
    if df is None:
        return None
    
    try:
        # Try matching by ITEM_SERIAL first (numeric check)
        if identifier.isnumeric():
            filtered_df = df[df["ITEM_SERIAL"].astype(str).str.lower().str.contains(identifier.lower())]
        else:
            # Try matching by ITEM_NAME
            filtered_df = df[df["ITEM_NAME"].str.lower().str.contains(identifier.lower())]
        
        if filtered_df.empty:
            # Try more flexible matching
            filtered_df = df[df["ITEM_NAME"].str.lower().str.contains(identifier.lower(), na=False)]
        
        if filtered_df.empty:
            return None

        # If department is specified, filter by department
        if department and department != "All Departments":
            filtered_df = filtered_df[filtered_df["DEPARTMENT"] == department]
            if filtered_df.empty:
                return None

        # Calculate department-level proportions only
        dept_usage = filtered_df.groupby("DEPARTMENT")["QUANTITY"].sum().reset_index()
        
        # Calculate total across all departments
        total_usage = dept_usage["QUANTITY"].sum()
        
        if total_usage == 0:
            return None
            
        # Calculate each department's proportion of the total
        dept_usage["PROPORTION"] = (dept_usage["QUANTITY"] / total_usage) * 100
        
        # Filter out departments with proportions less than min_proportion
        significant_depts = dept_usage[dept_usage["PROPORTION"] >= min_proportion].copy()
        
        # If no departments meet the threshold, return the one with the highest proportion
        if significant_depts.empty and not dept_usage.empty:
            significant_depts = pd.DataFrame([dept_usage.iloc[dept_usage["PROPORTION"].idxmax()]])
        
        # Recalculate proportions to ensure they sum to 100%
        total_proportion = significant_depts["PROPORTION"].sum()
        significant_depts["PROPORTION"] = (significant_depts["PROPORTION"] / total_proportion) * 100
        
        # Calculate relative weights for sorting
        significant_depts["QUANTITY_ABS"] = significant_depts["QUANTITY"].abs()
        significant_depts["INTERNAL_WEIGHT"] = significant_depts["QUANTITY_ABS"] / significant_depts["QUANTITY_ABS"].sum()
        
        # Sort by proportion (descending)
        significant_depts.sort_values(by=["PROPORTION"], ascending=[False], inplace=True)
        
        return significant_depts
    except Exception as e:
        st.error(f"Error calculating proportions: {e}")
        return None

def allocate_quantity(df, identifier, available_quantity, department=None):
    """
    Allocate quantity based on historical proportions at department level only.
    Filters out departments with less than 1% proportion.
    Ensures total allocation exactly matches available quantity.
    """
    proportions = calculate_proportion(df, identifier, department, min_proportion=1.0)
    if proportions is None:
        return None
    
    # Calculate allocated quantity for each department based on their proportion
    proportions["ALLOCATED_QUANTITY"] = (proportions["PROPORTION"] / 100) * available_quantity
    
    # First calculate the sum of the non-rounded values
    total_unrounded = proportions["ALLOCATED_QUANTITY"].sum()
    
    # Round allocated quantities to integers
    proportions["ALLOCATED_QUANTITY"] = proportions["ALLOCATED_QUANTITY"].round(0).astype(int)
    
    # Get the total after rounding
    allocated_sum = proportions["ALLOCATED_QUANTITY"].sum()
    
    # Adjust to ensure we match exactly the available quantity
    if allocated_sum != available_quantity:
        difference = int(available_quantity - allocated_sum)
        
        if difference > 0:
            # Need to add some units - add to departments with largest fractional parts
            # Sort by fractional part (descending)
            fractional_parts = (proportions["PROPORTION"] / 100) * available_quantity - proportions["ALLOCATED_QUANTITY"]
            indices = fractional_parts.sort_values(ascending=False).index[:difference].tolist()
            for idx in indices:
                proportions.at[idx, "ALLOCATED_QUANTITY"] += 1
        elif difference < 0:
            # Need to subtract some units - remove from departments with smallest fractional parts
            # Sort by fractional part (ascending)
            fractional_parts = (proportions["PROPORTION"] / 100) * available_quantity - (proportions["ALLOCATED_QUANTITY"] - 1)
            indices = fractional_parts.sort_values(ascending=True).index[:-difference].tolist()
            for idx in indices:
                proportions.at[idx, "ALLOCATED_QUANTITY"] -= 1
    
    # Verify once more that the sum matches the available quantity exactly
    final_sum = proportions["ALLOCATED_QUANTITY"].sum()
    assert final_sum == available_quantity, f"Allocation error: {final_sum} != {available_quantity}"
    
    return proportions

def generate_allocation_chart(result_df, item_name):
    """
    Generate a bar chart for allocation results.
    """
    # Create a bar chart
    fig = px.bar(
        result_df, 
        x="DEPARTMENT", 
        y="ALLOCATED_QUANTITY",
        text="ALLOCATED_QUANTITY",
        title=f"Allocation for {item_name} by Department",
        labels={
            "DEPARTMENT": "Department",
            "ALLOCATED_QUANTITY": "Allocated Quantity"
        },
        height=400,
        color_discrete_sequence=px.colors.qualitative.Vivid
    )
    
    # Customize the layout
    fig.update_layout(
        xaxis_title="Department",
        yaxis_title="Allocated Quantity",
        xaxis_tickangle=-45
    )
    
    return fig

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
    .debug-info {
        background-color: #f0f0f0;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
        font-size: 12px;
    }
    </style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("<h2 class='title'>SPP Ingredients Allocation</h2>", unsafe_allow_html=True)
    st.markdown("<p class='subtitle'>Allocation Settings</p>", unsafe_allow_html=True)
    
    # Google Sheet credentials and details
    SPREADSHEET_NAME = 'BROWNS STOCK MANAGEMENT'
    SHEET_NAME = 'CHECK_OUT'
    
    # Load the data
    if "data" not in st.session_state:
        st.session_state.data = get_cached_data()
    
    data = st.session_state.data
    
    if data is None:
        st.error("Failed to load data from Google Sheets.")
        
        # Try to debug
        if st.button("Debug Connection"):
            try:
                worksheet = connect_to_gsheet(SPREADSHEET_NAME, SHEET_NAME)
                if worksheet:
                    all_values = worksheet.get_all_values()
                    if all_values:
                        st.write("### Sheet Preview")
                        st.write(f"Total rows: {len(all_values)}")
                        st.write(f"Total columns: {len(all_values[0])}")
                        
                        st.write("**Headers:**")
                        headers = all_values[0]
                        for i, header in enumerate(headers, 1):
                            st.write(f"{i}. '{header}'")
                        
                        # Check for duplicates
                        dup_counts = Counter(headers)
                        duplicates = {k: v for k, v in dup_counts.items() if v > 1}
                        if duplicates:
                            st.warning(f"Duplicate headers found: {duplicates}")
                        
                        if len(all_values) > 1:
                            st.write("**First data row:**")
                            first_row = all_values[1]
                            for i, value in enumerate(first_row, 1):
                                st.write(f"{i}. '{value}'")
            except Exception as e:
                st.error(f"Debug error: {e}")
        
        st.stop()
    
    # Extract unique item names and departments for auto-suggestions
    unique_item_names = sorted(data["ITEM_NAME"].dropna().unique().tolist())
    unique_departments = sorted(["All Departments"] + data["DEPARTMENT"].dropna().unique().tolist())
    
    st.markdown("### Quick Stats")
    st.metric("Total Items", f"{len(unique_item_names)}")
    st.metric("Total Departments", f"{len(unique_departments) - 1}")  # Exclude "All Departments"
    
    # Refresh data button
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.session_state.data = load_data_from_google_sheet()
        st.rerun()
    
    st.markdown("---")
    st.markdown("### View Options")
    view_mode = st.radio("Select View", ["Allocation Calculator", "Data Overview"])
    
    st.markdown("---")
    st.markdown("<p class='footer'>Developed by Brown's Data Team, ©2025</p>", unsafe_allow_html=True)

# Main content
st.markdown("<h1 class='title'>SPP Ingredients Allocation App</h1>", unsafe_allow_html=True)

if view_mode == "Allocation Calculator":
    # Form Layout for Better UX
    st.markdown("<div class='card'>", unsafe_allow_html=True)
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
                available_quantity = st.number_input(f"Quantity:", min_value=0.1, step=0.1, value=1.0, key=f"qty_{i}")

            if identifier and available_quantity > 0:
                entries.append((identifier, available_quantity))

        submitted = st.form_submit_button("Calculate Allocation")
    st.markdown("</div>", unsafe_allow_html=True)

    # Processing Allocation
    if submitted:
        if not entries:
            st.warning("Please enter at least one valid item and quantity!")
        else:
            for identifier, available_quantity in entries:
                result = allocate_quantity(data, identifier, available_quantity, selected_department)
                if result is not None:
                    st.markdown("<div class='card'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-header'><h3 style='color: #2E86C1;'>Allocation for {identifier}</h3></div>", unsafe_allow_html=True)
                    
                    # Format the output for better readability
                    formatted_result = result[["DEPARTMENT", "PROPORTION", "ALLOCATED_QUANTITY"]].copy()
                    formatted_result = formatted_result.rename(columns={
                        "DEPARTMENT": "Department",
                        "PROPORTION": "Proportion (%)",
                        "ALLOCATED_QUANTITY": "Allocated Quantity"
                    })
                    
                    # Format numeric columns
                    formatted_result["Proportion (%)"] = formatted_result["Proportion (%)"].round(2)
                    formatted_result["Allocated Quantity"] = formatted_result["Allocated Quantity"].astype(int)
                    
                    # Display the result
                    st.dataframe(formatted_result, use_container_width=True)
                    
                    # Summary statistics
                    st.markdown("#### Allocation Summary")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total Allocated", f"{formatted_result['Allocated Quantity'].sum():,.0f}")
                    with col2:
                        st.metric("Departments", f"{formatted_result['Department'].nunique()}")
                    
                    # Add a download button for the result
                    csv = formatted_result.to_csv(index=False)
                    st.download_button(
                        label="Download Allocation as CSV",
                        data=csv,
                        file_name=f"{identifier}_allocation.csv",
                        mime="text/csv",
                    )
                    
                    # Show visualization
                    chart = generate_allocation_chart(result, identifier)
                    st.plotly_chart(chart, use_container_width=True)
                    
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.error(f"Item '{identifier}' not found in historical data or has no usage data for the selected department!")

elif view_mode == "Data Overview":
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### Data Overview")
    
    # Show data statistics
    st.markdown("#### Dataset Statistics")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Records", f"{len(data):,}")
    with col2:
        st.metric("Unique Items", f"{data['ITEM_NAME'].nunique():,}")
    with col3:
        st.metric("Date Range", f"{data['DATE'].min().strftime('%d/%m/%Y')} to {data['DATE'].max().strftime('%d/%m/%Y')}")
    
    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        selected_items = st.multiselect("Filter by Items", unique_item_names, default=[])
    with col2:
        selected_overview_dept = st.multiselect("Filter by Departments", unique_departments[1:], default=[])
    
    # Apply filters
    filtered_data = data.copy()
    if selected_items:
        filtered_data = filtered_data[filtered_data["ITEM_NAME"].isin(selected_items)]
    if selected_overview_dept:
        filtered_data = filtered_data[filtered_data["DEPARTMENT"].isin(selected_overview_dept)]
    
    # Show filtered data
    st.markdown(f"#### Filtered Data ({len(filtered_data)} records)")
    display_columns = ["DATE", "ITEM_NAME", "DEPARTMENT", "QUANTITY", "UNIT_OF_MEASURE"]
    st.dataframe(filtered_data[display_columns].head(100), use_container_width=True)
    
    # Show top items
    st.markdown("#### Top 10 Items by Usage")
    top_items = data.groupby("ITEM_NAME")["QUANTITY"].sum().nlargest(10).reset_index()
    st.dataframe(top_items, use_container_width=True)
    
    # Show department distribution
    st.markdown("#### Department Distribution")
    dept_usage = data.groupby("DEPARTMENT")["QUANTITY"].sum().reset_index()
    dept_usage = dept_usage.sort_values("QUANTITY", ascending=False)
    
    fig1 = px.bar(
        dept_usage.head(10),
        x="DEPARTMENT",
        y="QUANTITY",
        title="Top 10 Departments by Usage",
        color="QUANTITY",
        color_continuous_scale="Viridis"
    )
    st.plotly_chart(fig1, use_container_width=True)
    
    fig2 = px.pie(
        dept_usage,
        values="QUANTITY",
        names="DEPARTMENT",
        title="Usage Distribution by Department",
        hole=0.3
    )
    st.plotly_chart(fig2, use_container_width=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
