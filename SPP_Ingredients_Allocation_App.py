import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
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

def load_all_data_from_google_sheet():
    """
    Load ALL data from Google Sheets without date filtering.
    """
    with st.spinner("Loading all data from Google Sheets..."):
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
            
            # Convert DATE - handle YYYY-MM-DD format
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
            df = df.dropna(subset=["QUANTITY"])
            df = df[df["QUANTITY"] > 0]  # Only keep positive quantities
            
            # Add quarter info for rows with valid dates
            df["QUARTER"] = df["DATE"].dt.to_period("Q")
            
            return df
            
        except Exception as e:
            st.error(f"Error loading data: {str(e)}")
            import traceback
            st.error(f"Detailed error: {traceback.format_exc()}")
            return None

def filter_data_by_date_range(df, start_date=None, end_date=None, default_range="last_2_years"):
    """
    Filter data by date range with multiple options.
    
    Parameters:
    - df: DataFrame with DATE column
    - start_date: Specific start date (datetime)
    - end_date: Specific end date (datetime)
    - default_range: One of ["last_2_years", "last_year", "last_6_months", "last_3_months", "all_time"]
    """
    if df is None or df.empty:
        return df
    
    filtered_df = df.copy()
    
    # If specific dates are provided, use them
    if start_date is not None and end_date is not None:
        filtered_df = filtered_df[
            (filtered_df["DATE"] >= pd.Timestamp(start_date)) & 
            (filtered_df["DATE"] <= pd.Timestamp(end_date))
        ]
    else:
        # Use default range
        today = datetime.now().date()
        
        if default_range == "last_2_years":
            start_date = pd.Timestamp(today - timedelta(days=2*365))
        elif default_range == "last_year":
            start_date = pd.Timestamp(today - timedelta(days=365))
        elif default_range == "last_6_months":
            start_date = pd.Timestamp(today - timedelta(days=6*30))
        elif default_range == "last_3_months":
            start_date = pd.Timestamp(today - timedelta(days=3*30))
        elif default_range == "all_time":
            start_date = pd.Timestamp.min
        else:
            # Default to last 2 years
            start_date = pd.Timestamp(today - timedelta(days=2*365))
        
        end_date = pd.Timestamp(today)
        
        filtered_df = filtered_df[
            (filtered_df["DATE"] >= start_date) & 
            (filtered_df["DATE"] <= end_date)
        ]
    
    return filtered_df

@st.cache_data(ttl=3600)
def get_all_cached_data():
    return load_all_data_from_google_sheet()

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
        if department and department != "All Production Areas":
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
    Generate allocation chart with lighter cheese theme colors.
    """
    # Lighter, more appetizing cheese color palette
    cheese_colors = ['#FFE4B5', '#FFDAB9', '#FFE4C4', '#FAEBD7', '#F5F5DC', '#FFF8DC']
    
    fig = px.bar(
        result_df,
        x="DEPARTMENT",
        y="ALLOCATED_QUANTITY",
        text="ALLOCATED_QUANTITY",
        title=f"🧀 Allocation for {item_name}",
        color="ALLOCATED_QUANTITY",
        color_continuous_scale=cheese_colors
    )
    
    fig.update_layout(
        xaxis_title="Production Area",
        yaxis_title="Allocated Quantity",
        xaxis_tickangle=-45,
        plot_bgcolor='#FFFDF6',
        paper_bgcolor='#FFFDF6',
        font=dict(color='#6B4226', family='Arial')
    )
    
    return fig

# Streamlit App with Date Range Selector
st.set_page_config(
    page_title="Brown's Cheese - Ingredients Allocation",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🧀"
)

# Custom CSS with Lighter, Softer Cheese/Dairy Theme
st.markdown("""
<style>
    /* Lighter, softer color palette */
    :root {
        --cream-yellow: #FFF8E1;
        --light-cheese: #FFE4B5;
        --soft-gold: #FFDAB9;
        --warm-beige: #FAEBD7;
        --ivory: #F5F5DC;
        --light-brown: #D2B48C;
        --medium-brown: #8B7355;
        --soft-brown: #A67B5B;
        --milk-white: #FFFDF6;
        --off-white: #FAF9F6;
    }
    
    .main-title {
        text-align: center;
        color: var(--medium-brown);
        padding: 25px;
        background: linear-gradient(135deg, var(--light-cheese) 0%, var(--soft-gold) 100%);
        border-radius: 15px;
        margin-bottom: 30px;
        border: 2px solid var(--light-brown);
        font-family: 'Georgia', serif;
        box-shadow: 0 4px 12px rgba(139, 115, 85, 0.1);
    }
    
    .main-title h1 {
        font-size: 38px;
        font-weight: bold;
        text-shadow: 1px 1px 2px rgba(255, 255, 255, 0.8);
        margin-bottom: 10px;
        color: var(--medium-brown);
    }
    
    .main-title p {
        font-size: 16px;
        color: var(--soft-brown);
        font-weight: 500;
    }
    
    .card {
        background: var(--milk-white);
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 4px 8px rgba(210, 180, 140, 0.1);
        margin-bottom: 25px;
        border: 1px solid var(--warm-beige);
        font-family: 'Arial', sans-serif;
    }
    
    .card h3 {
        color: var(--medium-brown);
        border-bottom: 1px solid var(--light-cheese);
        padding-bottom: 10px;
        margin-bottom: 20px;
        font-family: 'Georgia', serif;
        font-weight: 600;
    }
    
    .stButton>button {
        background: linear-gradient(135deg, var(--light-cheese) 0%, var(--soft-gold) 100%);
        color: var(--medium-brown) !important;
        border: 1px solid var(--light-brown);
        padding: 10px 20px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        background: linear-gradient(135deg, var(--soft-gold) 0%, var(--light-brown) 100%);
        color: var(--medium-brown) !important;
        border-color: var(--soft-brown);
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(139, 115, 85, 0.15);
    }
    
    .sidebar-header {
        background: linear-gradient(135deg, var(--light-cheese) 0%, var(--warm-beige) 100%);
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        text-align: center;
        border: 1px solid var(--soft-gold);
    }
    
    .sidebar-header h2 {
        color: var(--medium-brown);
        margin: 0;
        font-family: 'Georgia', serif;
        font-size: 22px;
    }
    
    .metric-card {
        background: var(--off-white);
        padding: 12px;
        border-radius: 8px;
        border: 1px solid var(--warm-beige);
        margin-bottom: 8px;
        font-size: 14px;
    }
    
    .stMetric {
        background: var(--off-white);
        padding: 12px;
        border-radius: 8px;
        border: 1px solid var(--warm-beige);
    }
    
    [data-testid="stMetricValue"] {
        color: var(--medium-brown) !important;
        font-weight: 600;
    }
    
    [data-testid="stMetricLabel"] {
        color: var(--soft-brown) !important;
    }
    
    .data-warning {
        background-color: #FFF3CD;
        border: 1px solid var(--soft-gold);
        color: #856404;
        padding: 12px;
        border-radius: 8px;
        margin: 10px 0;
        font-size: 14px;
    }
    
    /* Input field styling */
    .stSelectbox div[data-baseweb="select"] > div,
    .stNumberInput input,
    .stMultiselect div[data-baseweb="select"] > div,
    .stDateInput input {
        background-color: var(--off-white) !important;
        border-color: var(--warm-beige) !important;
        border-radius: 6px !important;
    }
    
    /* Custom scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: var(--off-white);
    }
    
    ::-webkit-scrollbar-thumb {
        background: var(--light-brown);
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: var(--soft-brown);
    }
    
    /* Footer styling */
    .footer {
        text-align: center;
        color: var(--medium-brown);
        padding: 20px;
        margin-top: 30px;
        border-top: 1px solid var(--light-cheese);
        background: var(--off-white);
        border-radius: 10px;
        font-family: 'Georgia', serif;
    }
    
    /* Cheese icon */
    .cheese-icon {
        color: var(--medium-brown);
    }
    
    /* Success messages */
    .stSuccess {
        background-color: #F0F9EB !important;
        border-color: #B7EB8F !important;
        color: #52C41A !important;
    }
    
    /* Info messages */
    .stInfo {
        background-color: #E6F7FF !important;
        border-color: #91D5FF !important;
        color: #1890FF !important;
    }
    
    /* Warning messages */
    .stWarning {
        background-color: #FFFBE6 !important;
        border-color: #FFE58F !important;
        color: #FAAD14 !important;
    }
    
    /* Error messages */
    .stError {
        background-color: #FFF2F0 !important;
        border-color: #FFCCC7 !important;
        color: #FF4D4F !important;
    }
    
    /* App background */
    .stApp {
        background: linear-gradient(180deg, var(--milk-white) 0%, var(--off-white) 100%);
    }
    
    /* Radio button styling */
    .stRadio > div {
        background: var(--off-white);
        padding: 10px;
        border-radius: 8px;
        border: 1px solid var(--warm-beige);
    }
    
    /* Dataframe styling */
    .dataframe {
        border: 1px solid var(--warm-beige) !important;
        border-radius: 8px !important;
    }
    
    /* Make text more readable */
    p, li, span, div {
        color: var(--medium-brown);
    }
    
    /* Table headers */
    th {
        background-color: var(--warm-beige) !important;
        color: var(--medium-brown) !important;
    }
    
    /* Table rows */
    tr:nth-child(even) {
        background-color: var(--off-white) !important;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar with Date Range Selector
with st.sidebar:
    st.markdown("""
        <div class="sidebar-header">
            <h2>🧀 Brown's Cheese</h2>
            <p style="color: var(--soft-brown); margin: 5px 0 0 0; font-size: 14px;">Ingredients Allocation</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Date Range Selector
    st.markdown("### 📅 Date Range Selection")
    
    date_range_option = st.radio(
        "Select Date Range:",
        ["📊 Default (Last 2 Years)", "🗓️ Custom Range", "📈 All Time Data"],
        index=0,
        key="date_range_option"
    )
    
    custom_start_date = None
    custom_end_date = None
    
    if date_range_option == "🗓️ Custom Range":
        # Calculate min and max dates from data
        if "all_data" not in st.session_state:
            st.session_state.all_data = get_all_cached_data()
        
        if st.session_state.all_data is not None and not st.session_state.all_data.empty:
            min_date_all = st.session_state.all_data["DATE"].min().date()
            max_date_all = st.session_state.all_data["DATE"].max().date()
            
            # Default to last 3 months
            default_start = max(min_date_all, (datetime.now() - timedelta(days=90)).date())
            default_end = max_date_all
            
            col1, col2 = st.columns(2)
            with col1:
                custom_start_date = st.date_input(
                    "Start Date",
                    value=default_start,
                    min_value=min_date_all,
                    max_value=max_date_all,
                    key="custom_start"
                )
            with col2:
                custom_end_date = st.date_input(
                    "End Date",
                    value=default_end,
                    min_value=min_date_all,
                    max_value=max_date_all,
                    key="custom_end"
                )
            
            if custom_start_date > custom_end_date:
                st.error("⚠️ Start date must be before end date")
                custom_start_date = None
                custom_end_date = None
        else:
            st.info("Load data first to select custom date range")
    
    # Convert date range option to parameter for filter function
    if date_range_option == "📊 Default (Last 2 Years)":
        default_range = "last_2_years"
    elif date_range_option == "🗓️ Custom Range":
        default_range = "custom"
    else:  # "📈 All Time Data"
        default_range = "all_time"
    
    st.markdown("---")
    
    # Load data with selected date range
    if "all_data" not in st.session_state:
        with st.spinner("Loading production data..."):
            st.session_state.all_data = get_all_cached_data()
    
    all_data = st.session_state.all_data
    
    if all_data is None or all_data.empty:
        st.error("⚠️ Failed to load data")
        
        with st.expander("Technical Support"):
            if st.button("Test Connection"):
                try:
                    worksheet = connect_to_gsheet()
                    if worksheet:
                        st.success("✓ Connection successful!")
                except Exception as e:
                    st.error(f"✗ Error: {e}")
            
            if st.button("Reload Data"):
                st.cache_data.clear()
                st.session_state.all_data = get_all_cached_data()
                st.rerun()
        
        st.stop()
    
    # Filter data based on selected date range
    with st.spinner("Applying date filter..."):
        if default_range == "custom" and custom_start_date and custom_end_date:
            data = filter_data_by_date_range(
                all_data, 
                start_date=custom_start_date, 
                end_date=custom_end_date
            )
            date_info = f"Custom: {custom_start_date.strftime('%d %b %Y')} to {custom_end_date.strftime('%d %b %Y')}"
        elif default_range == "all_time":
            data = all_data.copy()
            date_info = "All Time Data"
        else:
            data = filter_data_by_date_range(all_data, default_range=default_range)
            if default_range == "last_2_years":
                date_info = "Last 2 Years"
            elif default_range == "last_year":
                date_info = "Last Year"
            elif default_range == "last_6_months":
                date_info = "Last 6 Months"
            elif default_range == "last_3_months":
                date_info = "Last 3 Months"
    
    # Store filtered data in session state
    st.session_state.filtered_data = data
    
    # Get unique values from filtered data
    unique_items = sorted(data["ITEM_NAME"].dropna().unique().tolist())
    unique_depts = sorted(["All Production Areas"] + data["DEPARTMENT"].dropna().unique().tolist())
    
    st.markdown("### 📊 Production Overview")
    
    # Display date range info
    st.info(f"**Date Range:** {date_info}")
    
    if not data.empty and "DATE" in data.columns and data["DATE"].notna().any():
        min_date = data["DATE"].min().date()
        max_date = data["DATE"].max().date()
        st.info(f"**Available Data:** {min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("🧀 Ingredients", len(unique_items))
    with col2:
        st.metric("🏭 Areas", len(unique_depts) - 1)
    
    st.markdown(f"""
    <div class="metric-card">
        <strong>Total Records:</strong> {len(data):,}<br>
        <strong>Total Quantity:</strong> {data['QUANTITY'].sum():,.0f}
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🔄 Refresh & Apply Filter", use_container_width=True):
        st.cache_data.clear()
        with st.spinner("Updating..."):
            st.session_state.all_data = get_all_cached_data()
        st.rerun()
    
    st.markdown("---")
    
    st.markdown("### 📋 Navigation")
    view_mode = st.radio(
        "Select View:",
        ["🧮 Allocation Calculator", "📈 Production Analytics"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    st.markdown("""
    <div style="text-align: center; padding: 12px; background: var(--off-white); border-radius: 8px; border: 1px solid var(--warm-beige);">
        <p style="color: var(--medium-brown); margin: 0; font-size: 13px; font-weight: 600;">Brown's Cheese Co.</p>
        <p style="color: var(--soft-brown); margin: 3px 0; font-size: 11px;">Artisan Cheese Makers</p>
    </div>
    """, unsafe_allow_html=True)

# Main Content
st.markdown("""
    <div class="main-title">
        <h1><span class="cheese-icon">🧀</span> Brown's Cheese Ingredients Allocation</h1>
        <p>Optimizing Ingredient Distribution Across Production</p>
    </div>
""", unsafe_allow_html=True)

# Data status
data = st.session_state.filtered_data

if data is not None and not data.empty:
    latest_date = data["DATE"].max()
    days_since_update = (datetime.now().date() - latest_date.date()).days
    
    if days_since_update <= 1:
        st.success(f"✅ Data updated today - {latest_date.strftime('%d %b %Y')}")
    elif days_since_update <= 7:
        st.info(f"📋 Data from {days_since_update} days ago - {latest_date.strftime('%d %b %Y')}")
    else:
        st.warning(f"⚠️ Data is {days_since_update} days old - Last update: {latest_date.strftime('%d %b %Y')}")

if data is not None and data.empty:
    st.markdown("""
        <div class="data-warning">
            ⚠️ No data available for the selected date range. Try adjusting your date filter.
        </div>
    """, unsafe_allow_html=True)

# Extract view mode
if "Allocation Calculator" in view_mode:
    view_mode_clean = "Allocation Calculator"
else:
    view_mode_clean = "Data Overview"

if view_mode_clean == "Allocation Calculator":
    if data is not None and not data.empty:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 🧮 Production Allocation")
        
        # Show current date range
        if not data.empty and "DATE" in data.columns and data["DATE"].notna().any():
            min_date = data["DATE"].min().date()
            max_date = data["DATE"].max().date()
            st.info(f"**Using data from:** {min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}")
        
        with st.form("calculator_form"):
            col1, col2 = st.columns(2)
            with col1:
                num_items = st.number_input(
                    "Number of Ingredients", 
                    min_value=1, 
                    max_value=10, 
                    value=1
                )
            with col2:
                selected_dept = st.selectbox(
                    "Production Area", 
                    unique_depts
                )
            
            st.markdown("---")
            
            entries = []
            for i in range(num_items):
                st.markdown(f"**Ingredient {i+1}**")
                col1, col2 = st.columns([3, 1])
                with col1:
                    item = st.selectbox(
                        f"Select ingredient {i+1}", 
                        unique_items, 
                        key=f"item_select_{i}"
                    )
                with col2:
                    qty = st.number_input(
                        "Quantity",
                        min_value=0.1,
                        value=1.0,
                        step=0.1,
                        key=f"qty_input_{i}"
                    )
                
                if item and qty > 0:
                    entries.append((item, qty))
            
            submitted = st.form_submit_button(
                "🧀 Calculate Allocation", 
                type="primary",
                use_container_width=True
            )
        
        st.markdown("</div>")
        
        if submitted and entries:
            for idx, (item, qty) in enumerate(entries):
                with st.spinner(f"Calculating allocation for {item}..."):
                    result = allocate_quantity(data, item, qty, selected_dept)
                
                if result is not None and not result.empty:
                    st.markdown('<div class="card">', unsafe_allow_html=True)
                    st.markdown(f"### 📋 Allocation for: **{item}**")
                    
                    # Show date range used for calculation
                    if not data.empty and "DATE" in data.columns:
                        calc_min_date = data["DATE"].min().date()
                        calc_max_date = data["DATE"].max().date()
                        st.caption(f"*Based on data from {calc_min_date.strftime('%d %b %Y')} to {calc_max_date.strftime('%d %b %Y')}*")
                    
                    display_df = result[["DEPARTMENT", "PROPORTION", "ALLOCATED_QUANTITY"]].copy()
                    display_df.columns = ["Production Area", "Usage %", "Allocated Quantity"]
                    display_df["Usage %"] = display_df["Usage %"].round(2)
                    
                    st.markdown("#### 📊 Allocation Summary")
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        column_config={
                            "Usage %": st.column_config.ProgressColumn(
                                format="%.1f%%",
                                min_value=0,
                                max_value=100
                            )
                        }
                    )
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Allocated", f"{display_df['Allocated Quantity'].sum():.0f}")
                    with col2:
                        st.metric("Production Areas", len(display_df))
                    with col3:
                        st.metric("Batch Size", f"{qty:.1f}")
                    
                    st.markdown("#### 📈 Visualization")
                    chart = generate_allocation_chart(result, item)
                    st.plotly_chart(chart, use_container_width=True)
                    
                    csv = display_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Report",
                        data=csv,
                        file_name=f"allocation_{item.replace('/', '_')[:20]}_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    st.markdown("</div>")
                else:
                    st.error(f"❌ No data found for: {item}")
                    st.info("Try adjusting the date range or select a different ingredient.")
    else:
        st.warning("🧀 No data available for allocation. Please adjust your date filter.")

elif view_mode_clean == "Data Overview":
    if data is not None and not data.empty:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 📈 Production Analytics")
        
        # Show current date range
        if not data.empty and "DATE" in data.columns and data["DATE"].notna().any():
            min_date = data["DATE"].min().date()
            max_date = data["DATE"].max().date()
            st.info(f"**Viewing data from:** {min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}")
        
        col1, col2 = st.columns(2)
        with col1:
            filter_items = st.multiselect("Filter by Ingredients", unique_items, default=[])
        with col2:
            filter_depts = st.multiselect("Filter by Areas", unique_depts[1:], default=[])
        
        filtered_data = data.copy()
        if filter_items:
            filtered_data = filtered_data[filtered_data["ITEM_NAME"].isin(filter_items)]
        if filter_depts:
            filtered_data = filtered_data[filtered_data["DEPARTMENT"].isin(filter_depts)]
        
        st.markdown("#### 📊 Statistics")
        cols = st.columns(4)
        with cols[0]:
            st.metric("Records", f"{len(filtered_data):,}")
        with cols[1]:
            st.metric("Total Quantity", f"{filtered_data['QUANTITY'].sum():,.0f}")
        with cols[2]:
            st.metric("Ingredients", filtered_data["ITEM_NAME"].nunique())
        with cols[3]:
            st.metric("Areas", filtered_data["DEPARTMENT"].nunique())
        
        st.markdown("#### 👁️ Data Preview")
        preview_cols = ["DATE", "ITEM_NAME", "DEPARTMENT", "QUANTITY", "UNIT_OF_MEASURE"]
        preview_data = filtered_data[preview_cols].head(100).copy()
        preview_data["DATE"] = preview_data["DATE"].dt.strftime('%d %b %Y')
        
        st.dataframe(
            preview_data,
            use_container_width=True,
            hide_index=True
        )
        
        if len(filtered_data) > 100:
            st.info(f"Showing 100 of {len(filtered_data)} records")
        
        st.markdown("#### 🏆 Top Ingredients (Selected Date Range)")
        top_items = filtered_data.groupby("ITEM_NAME")["QUANTITY"].sum().nlargest(10).reset_index()
        if not top_items.empty:
            fig1 = px.bar(
                top_items,
                x="ITEM_NAME",
                y="QUANTITY",
                color="QUANTITY",
                color_continuous_scale=['#FFE4B5', '#FFDAB9', '#FAEBD7'],
                labels={"ITEM_NAME": "Ingredient", "QUANTITY": "Total Usage"}
            )
            fig1.update_layout(
                xaxis_tickangle=-45,
                plot_bgcolor='#FFFDF6',
                paper_bgcolor='#FFFDF6',
                font=dict(color='#6B4226'),
                title=f"Top 10 Ingredients ({min_date.strftime('%b %Y')} to {max_date.strftime('%b %Y')})"
            )
            st.plotly_chart(fig1, use_container_width=True)
        
        # Monthly trend for selected date range
        st.markdown("#### 📅 Monthly Usage Trend")
        monthly_data = filtered_data.copy()
        monthly_data["MONTH"] = monthly_data["DATE"].dt.to_period("M").astype(str)
        monthly_trend = monthly_data.groupby("MONTH")["QUANTITY"].sum().reset_index()
        
        if not monthly_trend.empty and len(monthly_trend) > 1:
            fig2 = px.line(
                monthly_trend,
                x="MONTH",
                y="QUANTITY",
                markers=True,
                line_shape="spline",
                color_discrete_sequence=['#8B7355']
            )
            fig2.update_layout(
                xaxis_title="Month",
                yaxis_title="Total Quantity",
                xaxis_tickangle=-45,
                plot_bgcolor='#FFFDF6',
                paper_bgcolor='#FFFDF6',
                font=dict(color='#6B4226'),
                title=f"Monthly Trend ({min_date.strftime('%b %Y')} to {max_date.strftime('%b %Y')})"
            )
            fig2.update_traces(line=dict(width=3))
            st.plotly_chart(fig2, use_container_width=True)
        
        st.markdown("</div>")

# Footer
st.markdown("""
    <div class="footer">
        <p style="margin: 10px 0; color: var(--medium-brown); font-weight: 600;">
            Brown's Cheese Company • Ingredients Allocation System
        </p>
        <p style="font-size: 12px; color: var(--soft-brown); margin: 5px 0;">
            © 2024 Brown's Cheese Company • Date Range Filter Enabled
        </p>
    </div>
""", unsafe_allow_html=True)

# Decorative emojis
st.markdown("""
    <div style="text-align: center; margin: 20px 0; opacity: 0.7;">
        <span style="font-size: 20px;">🧀 🐄 🥛 📊 📈 📅</span>
    </div>
""", unsafe_allow_html=True)
