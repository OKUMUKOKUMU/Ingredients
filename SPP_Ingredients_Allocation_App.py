import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime
import plotly.express as px

# Load environment variables
load_dotenv()

def connect_to_gsheet():
    """
    Simple connection to Google Sheets.
    """
    scope = ["https://spreadsheets.google.com/feeds", 
             "https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive.file", 
             "https://www.googleapis.com/auth/drive"]
    
    try:
        # Get credentials from environment variables
        credentials_dict = {
            "type": "service_account",
            "project_id": os.getenv("GOOGLE_PROJECT_ID"),
            "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "").replace("\\n", "\n"),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
        }
        
        # Check if private key is loaded
        if not credentials_dict["private_key"]:
            st.error("GOOGLE_PRIVATE_KEY environment variable is not set or empty")
            return None
        
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
        client = gspread.authorize(credentials)
        
        # Open the spreadsheet
        spreadsheet = client.open('BROWNS STOCK MANAGEMENT')
        
        # Access the specific sheet
        worksheet = spreadsheet.worksheet('CHECK_OUT')
        
        return worksheet
        
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {str(e)}")
        return None

def load_data_simple():
    """
    Simple data loading with manual header handling.
    """
    with st.spinner("Loading data from Google Sheets..."):
        try:
            worksheet = connect_to_gsheet()
            if worksheet is None:
                return None
            
            # Get ALL data from the worksheet
            all_values = worksheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                st.error("Sheet is empty or has no data")
                return None
            
            # Show what we found for debugging
            st.sidebar.write(f"Total rows: {len(all_values)}")
            st.sidebar.write(f"First row (headers): {all_values[0]}")
            
            # Define EXACT headers from your sheet
            expected_headers = [
                "DATE", "ITEM_SERIAL", "ITEM_NAME", "DEPARTMENT", "ISSUED_TO", 
                "QUANTITY", "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"
            ]
            
            # Create DataFrame with expected headers
            # If there are more columns in the sheet than expected, we'll handle it
            data_rows = all_values[1:]  # Skip header row
            
            # Create DataFrame
            df = pd.DataFrame(data_rows)
            
            # If we have more columns than expected, truncate or expand
            if len(df.columns) > len(expected_headers):
                df = df.iloc[:, :len(expected_headers)]  # Take only first N columns
            elif len(df.columns) < len(expected_headers):
                # Add missing columns as empty
                for i in range(len(df.columns), len(expected_headers)):
                    df[i] = None
            
            # Set column names
            df.columns = expected_headers
            
            # Clean and convert data
            # Convert DATE - handle dd/mm/yyyy format
            df["DATE"] = pd.to_datetime(df["DATE"], format='%d/%m/%Y', errors='coerce')
            
            # Clean QUANTITY - remove any non-numeric characters
            df["QUANTITY"] = pd.to_numeric(
                df["QUANTITY"].astype(str).str.replace(r'[^\d.-]', '', regex=True), 
                errors='coerce'
            )
            
            # Clean text columns
            df["ITEM_NAME"] = df["ITEM_NAME"].astype(str).str.strip()
            df["DEPARTMENT"] = df["DEPARTMENT"].astype(str).str.strip()
            df["ITEM_SERIAL"] = df["ITEM_SERIAL"].astype(str).str.strip()
            
            # Remove rows with invalid quantities or dates
            df = df.dropna(subset=["QUANTITY", "DATE"])
            
            # Add quarter info
            df["QUARTER"] = df["DATE"].dt.to_period("Q")
            
            # Filter for recent data (last 2 years)
            current_year = datetime.now().year
            df = df[df["DATE"].dt.year >= current_year - 1]
            
            st.sidebar.success(f"✅ Successfully loaded {len(df)} records")
            st.sidebar.info(f"Date range: {df['DATE'].min().strftime('%d/%m/%Y')} to {df['DATE'].max().strftime('%d/%m/%Y')}")
            
            return df
            
        except Exception as e:
            st.error(f"Error loading data: {str(e)}")
            # Try to show more info
            try:
                if worksheet:
                    st.sidebar.write("First few rows of raw data:")
                    for i, row in enumerate(all_values[:5]):
                        st.sidebar.write(f"Row {i}: {row}")
            except:
                pass
            return None

@st.cache_data(ttl=3600)
def get_cached_data():
    return load_data_simple()

def calculate_proportion(df, identifier, department=None, min_proportion=1.0):
    """
    Calculate department-wise usage proportion.
    """
    if df is None or df.empty:
        return None
    
    try:
        # Filter by item name (case-insensitive)
        filtered_df = df[df["ITEM_NAME"].str.lower().str.contains(identifier.lower(), na=False)]
        
        if filtered_df.empty:
            return None
        
        # Filter by department if specified
        if department and department != "All Departments":
            filtered_df = filtered_df[filtered_df["DEPARTMENT"] == department]
            if filtered_df.empty:
                return None
        
        # Group by department
        dept_usage = filtered_df.groupby("DEPARTMENT")["QUANTITY"].sum().reset_index()
        
        total_usage = dept_usage["QUANTITY"].sum()
        if total_usage == 0:
            return None
        
        # Calculate proportions
        dept_usage["PROPORTION"] = (dept_usage["QUANTITY"] / total_usage) * 100
        
        # Filter by minimum proportion
        significant = dept_usage[dept_usage["PROPORTION"] >= min_proportion].copy()
        
        if significant.empty and not dept_usage.empty:
            # Return the top department
            significant = pd.DataFrame([dept_usage.iloc[dept_usage["PROPORTION"].idxmax()]])
        
        # Normalize to 100%
        total_prop = significant["PROPORTION"].sum()
        significant["PROPORTION"] = (significant["PROPORTION"] / total_prop) * 100
        
        # Sort
        significant = significant.sort_values("PROPORTION", ascending=False)
        
        return significant
        
    except Exception as e:
        st.error(f"Error calculating proportions: {e}")
        return None

def allocate_quantity(df, identifier, available_quantity, department=None):
    """
    Allocate quantity based on historical proportions.
    """
    proportions = calculate_proportion(df, identifier, department, min_proportion=1.0)
    
    if proportions is None:
        return None
    
    # Calculate allocation
    proportions["ALLOCATED_QUANTITY"] = (proportions["PROPORTION"] / 100) * available_quantity
    
    # Round to integers
    proportions["ALLOCATED_QUANTITY"] = proportions["ALLOCATED_QUANTITY"].round().astype(int)
    
    # Adjust to match total
    allocated_sum = proportions["ALLOCATED_QUANTITY"].sum()
    difference = int(available_quantity - allocated_sum)
    
    if difference > 0:
        # Add to departments with largest fractional parts
        fractional = (proportions["PROPORTION"] / 100) * available_quantity - proportions["ALLOCATED_QUANTITY"]
        indices = fractional.nlargest(difference).index
        for idx in indices:
            proportions.at[idx, "ALLOCATED_QUANTITY"] += 1
    elif difference < 0:
        # Subtract from departments with smallest fractional parts
        fractional = (proportions["PROPORTION"] / 100) * available_quantity - (proportions["ALLOCATED_QUANTITY"] - 1)
        indices = fractional.nsmallest(-difference).index
        for idx in indices:
            proportions.at[idx, "ALLOCATED_QUANTITY"] -= 1
    
    return proportions

def generate_allocation_chart(result_df, item_name):
    """
    Generate allocation chart.
    """
    fig = px.bar(
        result_df,
        x="DEPARTMENT",
        y="ALLOCATED_QUANTITY",
        text="ALLOCATED_QUANTITY",
        title=f"Allocation for {item_name}",
        color="ALLOCATED_QUANTITY",
        color_continuous_scale="Viridis"
    )
    
    fig.update_layout(
        xaxis_title="Department",
        yaxis_title="Allocated Quantity",
        xaxis_tickangle=-45
    )
    
    return fig

# Streamlit App
st.set_page_config(
    page_title="SPP Ingredients Allocation",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-title {
        text-align: center;
        color: #1E3A8A;
        padding: 20px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        margin-bottom: 30px;
    }
    .card {
        background: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 20px;
    }
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 10px 20px;
        border-radius: 5px;
        font-weight: bold;
        width: 100%;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("## SPP Ingredients Allocation")
    st.markdown("---")
    
    # Load data
    if "data" not in st.session_state:
        st.session_state.data = get_cached_data()
    
    data = st.session_state.data
    
    if data is None:
        st.error("⚠️ Failed to load data")
        
        # Debug section
        with st.expander("Debug Info"):
            st.write("Check your environment variables:")
            st.write(f"GOOGLE_PROJECT_ID: {'Set' if os.getenv('GOOGLE_PROJECT_ID') else 'Not set'}")
            st.write(f"GOOGLE_CLIENT_EMAIL: {'Set' if os.getenv('GOOGLE_CLIENT_EMAIL') else 'Not set'}")
            
            if st.button("Test Connection"):
                try:
                    worksheet = connect_to_gsheet()
                    if worksheet:
                        st.success("✓ Connection successful!")
                        # Show sheet info
                        all_values = worksheet.get_all_values()
                        if all_values:
                            st.write(f"Sheet dimensions: {len(all_values)} rows x {len(all_values[0])} columns")
                            st.write("Headers:", all_values[0])
                    else:
                        st.error("✗ Connection failed")
                except Exception as e:
                    st.error(f"Error: {e}")
        
        st.stop()
    
    # Get unique values
    unique_items = sorted(data["ITEM_NAME"].dropna().unique().tolist())
    unique_depts = sorted(["All Departments"] + data["DEPARTMENT"].dropna().unique().tolist())
    
    st.markdown("### 📊 Data Summary")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Items", len(unique_items))
    with col2:
        st.metric("Departments", len(unique_depts) - 1)
    
    st.write(f"**Total Records:** {len(data):,}")
    
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.session_state.data = load_data_simple()
        st.rerun()
    
    st.markdown("---")
    view_mode = st.radio("**View Mode:**", ["Allocation Calculator", "Data Overview"])
    
    st.markdown("---")
    st.caption("Developed by Brown's Data Team")

# Main Content
st.markdown('<div class="main-title"><h1>SPP Ingredients Allocation System</h1></div>', unsafe_allow_html=True)

if view_mode == "Allocation Calculator":
    # Calculator Interface
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 🧮 Allocation Calculator")
    
    with st.form("calculator_form"):
        col1, col2 = st.columns(2)
        with col1:
            num_items = st.number_input("Number of Items", min_value=1, max_value=10, value=1)
        with col2:
            selected_dept = st.selectbox("Department Filter", unique_depts)
        
        st.markdown("---")
        
        entries = []
        for i in range(num_items):
            st.markdown(f"**Item {i+1}**")
            col1, col2 = st.columns([3, 1])
            with col1:
                item = st.selectbox(
                    f"Select item {i+1}", 
                    unique_items, 
                    key=f"item_select_{i}",
                    help="Select an item from the list"
                )
            with col2:
                qty = st.number_input(
                    "Quantity",
                    min_value=0.1,
                    value=1.0,
                    step=0.1,
                    key=f"qty_input_{i}",
                    help="Enter the quantity to allocate"
                )
            
            if item and qty > 0:
                entries.append((item, qty))
        
        submitted = st.form_submit_button("🚀 Calculate Allocation", type="primary")
    
    st.markdown("</div>")
    
    # Process Allocation
    if submitted and entries:
        for idx, (item, qty) in enumerate(entries):
            result = allocate_quantity(data, item, qty, selected_dept)
            
            if result is not None and not result.empty:
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown(f"### 📋 Allocation Results for: **{item}**")
                
                # Create display dataframe
                display_df = result[["DEPARTMENT", "PROPORTION", "ALLOCATED_QUANTITY"]].copy()
                display_df.columns = ["Department", "Proportion (%)", "Allocated Quantity"]
                display_df["Proportion (%)"] = display_df["Proportion (%)"].round(2)
                
                # Display table
                st.dataframe(display_df, use_container_width=True)
                
                # Summary metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Allocated", f"{display_df['Allocated Quantity'].sum():.0f}")
                with col2:
                    st.metric("Departments", len(display_df))
                with col3:
                    st.metric("Available Qty", f"{qty:.1f}")
                
                # Chart
                st.markdown("#### 📊 Allocation Visualization")
                chart = generate_allocation_chart(result, item)
                st.plotly_chart(chart, use_container_width=True)
                
                # Download option
                csv = display_df.to_csv(index=False)
                st.download_button(
                    label="💾 Download CSV",
                    data=csv,
                    file_name=f"{item.replace('/', '_').replace(' ', '_')}_allocation.csv",
                    mime="text/csv"
                )
                
                st.markdown("</div>")
            else:
                st.error(f"❌ No historical data found for: {item}")
                st.info(f"Try selecting a different item or check the data overview for available items.")

elif view_mode == "Data Overview":
    # Data Overview Interface
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### 📈 Data Overview")
    
    # Filters
    col1, col2 = st.columns(2)
    with col1:
        filter_items = st.multiselect("Filter by Items", unique_items)
    with col2:
        filter_depts = st.multiselect("Filter by Departments", unique_depts[1:])
    
    # Apply filters
    filtered_data = data.copy()
    if filter_items:
        filtered_data = filtered_data[filtered_data["ITEM_NAME"].isin(filter_items)]
    if filter_depts:
        filtered_data = filtered_data[filtered_data["DEPARTMENT"].isin(filter_depts)]
    
    # Statistics
    st.markdown("#### 📊 Statistics")
    cols = st.columns(4)
    with cols[0]:
        st.metric("Filtered Records", f"{len(filtered_data):,}")
    with cols[1]:
        st.metric("Total Quantity", f"{filtered_data['QUANTITY'].sum():,.0f}")
    with cols[2]:
        st.metric("Unique Items", filtered_data["ITEM_NAME"].nunique())
    with cols[3]:
        st.metric("Active Departments", filtered_data["DEPARTMENT"].nunique())
    
    # Data Preview
    st.markdown("#### 👁️ Data Preview")
    preview_cols = ["DATE", "ITEM_NAME", "DEPARTMENT", "QUANTITY", "UNIT_OF_MEASURE"]
    st.dataframe(
        filtered_data[preview_cols].head(100),
        use_container_width=True,
        hide_index=True
    )
    
    # Show more data if needed
    if len(filtered_data) > 100:
        st.info(f"Showing 100 of {len(filtered_data)} records. Use filters to narrow down.")
    
    # Top Items Chart
    st.markdown("#### 🏆 Top 10 Items by Usage")
    top_items = data.groupby("ITEM_NAME")["QUANTITY"].sum().nlargest(10).reset_index()
    fig1 = px.bar(
        top_items,
        x="ITEM_NAME",
        y="QUANTITY",
        title="Most Used Items",
        color="QUANTITY",
        color_continuous_scale="Viridis"
    )
    fig1.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig1, use_container_width=True)
    
    # Department Distribution
    st.markdown("#### 🏢 Department Distribution")
    dept_dist = data.groupby("DEPARTMENT")["QUANTITY"].sum().reset_index()
    fig2 = px.pie(
        dept_dist,
        values="QUANTITY",
        names="DEPARTMENT",
        title="Quantity Distribution by Department",
        hole=0.3
    )
    st.plotly_chart(fig2, use_container_width=True)
    
    # Time Series Analysis
    st.markdown("#### 📅 Monthly Usage Trend")
    monthly_data = data.copy()
    monthly_data["MONTH"] = monthly_data["DATE"].dt.to_period("M").astype(str)
    monthly_trend = monthly_data.groupby("MONTH")["QUANTITY"].sum().reset_index()
    
    fig3 = px.line(
        monthly_trend,
        x="MONTH",
        y="QUANTITY",
        title="Monthly Usage Trend",
        markers=True
    )
    fig3.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig3, use_container_width=True)
    
    st.markdown("</div>")

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666; font-size: 0.9em;'>
        <p>SPP Ingredients Allocation System | Version 1.0 | Last Updated: March 2024</p>
        <p>For support, contact the Data Team</p>
    </div>
    """,
    unsafe_allow_html=True
)
