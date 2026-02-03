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
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "").replace("\\n", "\n"),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
        }

        client_credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials, scope)
        client = gspread.authorize(client_credentials)
        spreadsheet = client.open('BROWNS STOCK MANAGEMENT')  
        return spreadsheet.worksheet('CHECK_OUT')
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None

def load_data_from_google_sheet():
    """
    Load data from Google Sheets - corrected version.
    """
    with st.spinner("Loading data from Google Sheets..."):
        try:
            worksheet = connect_to_gsheet()
            if worksheet is None:
                return None
            
            # Get all data
            all_values = worksheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                st.error("No data found in the Google Sheet.")
                return None
            
            # Get headers and data
            headers = all_values[0]
            data_rows = all_values[1:]
            
            # Create DataFrame
            df = pd.DataFrame(data_rows, columns=headers)
            
            # Debug: Show data info
            st.sidebar.write(f"📊 Raw data loaded: {len(df)} rows")
            
            # Clean and convert data
            # Convert DATE - handle YYYY-MM-DD format (as seen in your data)
            df["DATE"] = pd.to_datetime(df["DATE"], errors='coerce')
            
            # Clean QUANTITY - remove non-numeric characters
            df["QUANTITY"] = pd.to_numeric(
                df["QUANTITY"].astype(str).str.replace(r'[^\d.-]', '', regex=True), 
                errors='coerce'
            )
            
            # Clean text columns
            text_columns = ["ITEM_NAME", "DEPARTMENT", "ITEM_SERIAL", "ISSUED_TO", 
                          "UNIT_OF_MEASURE", "ITEM_CATEGORY", "DEPARTMENT_CAT", "STORE"]
            for col in text_columns:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.strip()
            
            # Remove rows with invalid quantities or dates
            initial_count = len(df)
            df = df.dropna(subset=["QUANTITY"])
            df = df[df["QUANTITY"] > 0]  # Only keep positive quantities
            filtered_count = len(df)
            
            st.sidebar.write(f"✅ Cleaned data: {filtered_count} rows (removed {initial_count - filtered_count} invalid rows)")
            
            # Check if we have valid dates
            valid_dates = df["DATE"].notna().sum()
            st.sidebar.write(f"📅 Valid dates: {valid_dates} rows")
            
            # Add quarter info for rows with valid dates
            df["QUARTER"] = df["DATE"].dt.to_period("Q")
            
            # Filter for recent data (last 2 years)
            if not df.empty:
                current_year = datetime.now().year
                df = df[df["DATE"].dt.year >= current_year - 1]
                
                if not df.empty:
                    # Show date range safely
                    min_date = df["DATE"].min()
                    max_date = df["DATE"].max()
                    if pd.notna(min_date) and pd.notna(max_date):
                        st.sidebar.info(f"Date range: {min_date.strftime('%d/%m/%Y')} to {max_date.strftime('%d/%m/%Y')}")
                    else:
                        st.sidebar.warning("Some dates are invalid")
                    
                    st.sidebar.success(f"🎯 Final dataset: {len(df)} records")
                else:
                    st.sidebar.warning("No data after filtering for recent years")
            
            return df
            
        except Exception as e:
            st.error(f"Error loading data: {str(e)}")
            import traceback
            st.error(f"Detailed error: {traceback.format_exc()}")
            return None

@st.cache_data(ttl=3600)
def get_cached_data():
    return load_data_from_google_sheet()

def calculate_proportion(df, identifier, department=None, min_proportion=1.0):
    """
    Calculate department-wise usage proportion.
    """
    if df is None or df.empty:
        return None
    
    try:
        # Try to find item by name (case-insensitive)
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
        
        if dept_usage.empty:
            return None
        
        total_usage = dept_usage["QUANTITY"].sum()
        if total_usage <= 0:
            return None
        
        # Calculate proportions
        dept_usage["PROPORTION"] = (dept_usage["QUANTITY"] / total_usage) * 100
        
        # Filter by minimum proportion
        significant = dept_usage[dept_usage["PROPORTION"] >= min_proportion].copy()
        
        if significant.empty and not dept_usage.empty:
            # Return the department with highest proportion
            significant = pd.DataFrame([dept_usage.loc[dept_usage["PROPORTION"].idxmax()]])
        
        # Normalize to 100%
        total_prop = significant["PROPORTION"].sum()
        if total_prop > 0:
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
    }
    .data-warning {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        color: #856404;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("## 🧮 SPP Ingredients Allocation")
    st.markdown("---")
    
    # Load data
    if "data" not in st.session_state:
        with st.spinner("Loading data..."):
            st.session_state.data = get_cached_data()
    
    data = st.session_state.data
    
    if data is None or data.empty:
        st.error("⚠️ Failed to load data or data is empty")
        
        # Debug options
        with st.expander("🔧 Debug Options"):
            if st.button("Test Connection"):
                try:
                    worksheet = connect_to_gsheet()
                    if worksheet:
                        st.success("✓ Connection successful!")
                        all_values = worksheet.get_all_values()
                        if all_values:
                            st.write(f"Sheet size: {len(all_values)} rows")
                            st.write("First few headers:", all_values[0][:5])
                            
                            # Show sample data
                            if len(all_values) > 1:
                                st.write("First data row:", all_values[1])
                except Exception as e:
                    st.error(f"✗ Connection failed: {e}")
            
            if st.button("Reload Data"):
                st.cache_data.clear()
                st.session_state.data = load_data_from_google_sheet()
                st.rerun()
        
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
    
    if not data.empty:
        # Safely display date range
        if "DATE" in data.columns and data["DATE"].notna().any():
            min_date = data["DATE"].min()
            max_date = data["DATE"].max()
            if pd.notna(min_date) and pd.notna(max_date):
                st.write(f"**Date Range:** {min_date.strftime('%d/%m/%Y')} to {max_date.strftime('%d/%m/%Y')}")
    
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        with st.spinner("Refreshing..."):
            st.session_state.data = load_data_from_google_sheet()
        st.rerun()
    
    st.markdown("---")
    view_mode = st.radio("**View Mode:**", ["Allocation Calculator", "Data Overview"])
    
    st.markdown("---")
    st.caption("Developed by Brown's Data Team")

# Main Content
st.markdown('<div class="main-title"><h1>🧪 SPP Ingredients Allocation System</h1></div>', unsafe_allow_html=True)

# Data quality warning
if data is not None and data.empty:
    st.markdown('<div class="data-warning">⚠️ No valid data available after cleaning. Check your Google Sheet for data quality issues.</div>', unsafe_allow_html=True)
elif data is not None and "DATE" in data.columns:
    invalid_dates = data["DATE"].isna().sum()
    if invalid_dates > 0:
        st.warning(f"⚠️ {invalid_dates} rows have invalid dates")

if view_mode == "Allocation Calculator":
    if data is not None and not data.empty:
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
                        help="Select an item from your inventory"
                    )
                with col2:
                    qty = st.number_input(
                        "Quantity",
                        min_value=0.1,
                        value=1.0,
                        step=0.1,
                        key=f"qty_input_{i}",
                        help="Enter quantity to allocate"
                    )
                
                if item and qty > 0:
                    entries.append((item, qty))
            
            submitted = st.form_submit_button("🚀 Calculate Allocation", type="primary")
        
        st.markdown("</div>")
        
        # Process Allocation
        if submitted and entries:
            for idx, (item, qty) in enumerate(entries):
                with st.spinner(f"Calculating allocation for {item}..."):
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
    else:
        st.warning("No data available for allocation. Please check your data connection.")

elif view_mode == "Data Overview":
    if data is not None and not data.empty:
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
        
        if len(filtered_data) > 100:
            st.info(f"Showing 100 of {len(filtered_data)} records. Use filters to narrow down.")
        
        # Top Items Chart
        st.markdown("#### 🏆 Top 10 Items by Usage")
        top_items = data.groupby("ITEM_NAME")["QUANTITY"].sum().nlargest(10).reset_index()
        if not top_items.empty:
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
        if not dept_dist.empty and len(dept_dist) > 1:
            fig2 = px.pie(
                dept_dist,
                values="QUANTITY",
                names="DEPARTMENT",
                title="Quantity Distribution by Department",
                hole=0.3
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        st.markdown("</div>")
    else:
        st.warning("No data available for overview.")

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666; font-size: 0.9em;'>
        <p>SPP Ingredients Allocation System | Version 2.0 | Last Updated: March 2024</p>
        <p>For support, contact the Data Team</p>
    </div>
    """,
    unsafe_allow_html=True
)
