import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

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
    Generate allocation chart with cheese theme colors.
    """
    # Cheese-inspired color palette
    cheese_colors = ['#FFD700', '#F4A460', '#DAA520', '#CD853F', '#8B4513', '#A0522D']
    
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
        xaxis_title="Department",
        yaxis_title="Allocated Quantity",
        xaxis_tickangle=-45,
        plot_bgcolor='#FFF8E7',
        paper_bgcolor='#FFF8E7',
        font=dict(color='#5D4037')
    )
    
    return fig

# Streamlit App with Cheese Manufacturing Theme
st.set_page_config(
    page_title="Brown's Cheese - Ingredients Allocation",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🧀"
)

# Custom CSS with Cheese/Dairy Theme
st.markdown("""
<style>
    /* Main theme colors */
    :root {
        --primary-yellow: #FFD700;
        --cheese-yellow: #F4A460;
        --golden-brown: #DAA520;
        --cheese-orange: #CD853F;
        --brown: #8B4513;
        --dark-brown: #5D4037;
        --cream: #FFF8E7;
        --light-cream: #FFFDF6;
        --milk-white: #F8F4E9;
    }
    
    .main-title {
        text-align: center;
        color: var(--dark-brown);
        padding: 25px;
        background: linear-gradient(135deg, var(--cheese-yellow) 0%, var(--cheese-orange) 100%);
        border-radius: 15px;
        margin-bottom: 30px;
        border: 3px solid var(--golden-brown);
        font-family: 'Georgia', serif;
    }
    
    .main-title h1 {
        font-size: 42px;
        font-weight: bold;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        margin-bottom: 10px;
    }
    
    .main-title p {
        font-size: 18px;
        color: var(--dark-brown);
        font-weight: 500;
    }
    
    .card {
        background: var(--light-cream);
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 6px 12px rgba(139, 69, 19, 0.1);
        margin-bottom: 25px;
        border: 2px solid var(--cheese-yellow);
        font-family: 'Arial', sans-serif;
    }
    
    .card h3 {
        color: var(--brown);
        border-bottom: 2px solid var(--cheese-yellow);
        padding-bottom: 10px;
        margin-bottom: 20px;
        font-family: 'Georgia', serif;
    }
    
    .stButton>button {
        background: linear-gradient(135deg, var(--cheese-yellow) 0%, var(--cheese-orange) 100%);
        color: var(--dark-brown) !important;
        border: 2px solid var(--golden-brown);
        padding: 12px 24px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 16px;
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        background: linear-gradient(135deg, var(--golden-brown) 0%, var(--brown) 100%);
        color: white !important;
        border-color: var(--dark-brown);
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(139, 69, 19, 0.2);
    }
    
    .sidebar-header {
        background: linear-gradient(135deg, var(--cheese-yellow) 0%, var(--cheese-orange) 100%);
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        text-align: center;
        border: 2px solid var(--golden-brown);
    }
    
    .sidebar-header h2 {
        color: var(--dark-brown);
        margin: 0;
        font-family: 'Georgia', serif;
    }
    
    .metric-card {
        background: var(--cream);
        padding: 15px;
        border-radius: 10px;
        border: 1px solid var(--cheese-yellow);
        margin-bottom: 10px;
    }
    
    .stMetric {
        background: var(--milk-white);
        padding: 15px;
        border-radius: 10px;
        border: 1px solid var(--cheese-yellow);
    }
    
    .data-warning {
        background-color: #FFF3CD;
        border: 2px solid #FFD700;
        color: #856404;
        padding: 15px;
        border-radius: 10px;
        margin: 15px 0;
        font-weight: bold;
    }
    
    .stSelectbox, .stNumberInput, .stMultiselect, .stDateInput {
        background-color: var(--cream);
        border-radius: 8px;
    }
    
    /* Custom scrollbar */
    ::-webkit-scrollbar {
        width: 10px;
    }
    
    ::-webkit-scrollbar-track {
        background: var(--cream);
    }
    
    ::-webkit-scrollbar-thumb {
        background: var(--cheese-yellow);
        border-radius: 5px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: var(--golden-brown);
    }
    
    /* Footer styling */
    .footer {
        text-align: center;
        color: var(--dark-brown);
        padding: 20px;
        margin-top: 40px;
        border-top: 2px solid var(--cheese-yellow);
        background: var(--cream);
        border-radius: 10px;
        font-family: 'Georgia', serif;
    }
    
    /* Cheese icon animations */
    @keyframes cheeseSpin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    .cheese-icon {
        animation: cheeseSpin 20s linear infinite;
        display: inline-block;
    }
    
    /* Success messages */
    .stSuccess {
        background-color: #E8F5E9;
        border-color: #4CAF50;
    }
    
    /* Info messages */
    .stInfo {
        background-color: #E3F2FD;
        border-color: #2196F3;
    }
    
    /* Cheese pattern background */
    .stApp {
        background: linear-gradient(135deg, var(--milk-white) 0%, var(--cream) 100%);
    }
</style>
""", unsafe_allow_html=True)

# Sidebar with Cheese Theme
with st.sidebar:
    st.markdown("""
        <div class="sidebar-header">
            <h2>🧀 Brown's Cheese</h2>
            <p style="color: var(--dark-brown); margin: 5px 0 0 0; font-weight: bold;">Ingredients Allocation System</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Load data
    if "data" not in st.session_state:
        with st.spinner("Loading cheese production data..."):
            st.session_state.data = get_cached_data()
    
    data = st.session_state.data
    
    if data is None or data.empty:
        st.error("⚠️ Failed to load production data")
        
        # Debug options
        with st.expander("🔧 Technical Diagnostics"):
            if st.button("🧀 Test Cheese Database Connection"):
                try:
                    worksheet = connect_to_gsheet()
                    if worksheet:
                        st.success("✓ Connection to Production Database Successful!")
                        all_values = worksheet.get_all_values()
                        if all_values:
                            st.write(f"🧾 Total Records: {len(all_values)}")
                            st.write(f"🏭 Departments Tracked: {len(set([row[3] for row in all_values[1:10] if len(row) > 3]))}")
                except Exception as e:
                    st.error(f"✗ Connection Error: {e}")
            
            if st.button("🔄 Reload Production Data"):
                st.cache_data.clear()
                st.session_state.data = load_data_from_google_sheet()
                st.rerun()
        
        st.stop()
    
    # Get unique values
    unique_items = sorted(data["ITEM_NAME"].dropna().unique().tolist())
    unique_depts = sorted(["All Production Areas"] + data["DEPARTMENT"].dropna().unique().tolist())
    
    st.markdown("### 🏭 Production Overview")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("🧀 Ingredients", len(unique_items))
    with col2:
        st.metric("🏗️ Production Areas", len(unique_depts) - 1)
    
    st.markdown(f"""
    <div class="metric-card">
        <strong>📊 Total Transactions:</strong> {len(data):,}<br>
        <strong>⚖️ Total Quantity Used:</strong> {data['QUANTITY'].sum():,.0f} units
    </div>
    """, unsafe_allow_html=True)
    
    if not data.empty:
        # Safely display date range
        if "DATE" in data.columns and data["DATE"].notna().any():
            min_date = data["DATE"].min()
            max_date = data["DATE"].max()
            if pd.notna(min_date) and pd.notna(max_date):
                st.info(f"**📅 Data Range:** {min_date.strftime('%d %b %Y')} to {max_date.strftime('%d %b %Y')}")
    
    # Refresh button with cheese theme
    if st.button("🔄 Refresh Production Data", use_container_width=True):
        st.cache_data.clear()
        with st.spinner("Updating from cheese production database..."):
            st.session_state.data = load_data_from_google_sheet()
        st.success("Production data refreshed!")
        st.rerun()
    
    st.markdown("---")
    
    # View mode with custom styling
    st.markdown("### 📋 Navigation")
    view_mode = st.radio(
        "Select View:",
        ["🧮 Allocation Calculator", "📈 Production Analytics"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # Company branding
    st.markdown("""
    <div style="text-align: center; padding: 15px; background: var(--cream); border-radius: 10px; border: 1px solid var(--cheese-yellow);">
        <h4 style="color: var(--dark-brown); margin: 0;">Brown's Cheese Co.</h4>
        <p style="color: var(--brown); margin: 5px 0; font-size: 12px;">Est. 1979 • Artisan Cheese Makers</p>
        <p style="color: var(--brown); margin: 5px 0; font-size: 11px;">Premium Dairy Products</p>
    </div>
    """, unsafe_allow_html=True)

# Main Content with Cheese Manufacturing Theme
st.markdown("""
    <div class="main-title">
        <h1><span class="cheese-icon">🧀</span> Brown's Cheese Ingredients Allocation</h1>
        <p>Optimizing Ingredient Distribution Across Cheese Production Facilities</p>
    </div>
""", unsafe_allow_html=True)

# Production status indicator
if data is not None and not data.empty:
    latest_date = data["DATE"].max()
    days_since_update = (datetime.now().date() - latest_date.date()).days
    
    if days_since_update <= 1:
        st.success(f"✅ Production data updated today - {latest_date.strftime('%d %b %Y')}")
    elif days_since_update <= 7:
        st.info(f"📋 Production data from {days_since_update} days ago - {latest_date.strftime('%d %b %Y')}")
    else:
        st.warning(f"⚠️ Production data is {days_since_update} days old - Last update: {latest_date.strftime('%d %b %Y')}")

# Data quality warning
if data is not None and data.empty:
    st.markdown("""
        <div class="data-warning">
            ⚠️ No valid production data available. Please check:
            1. Production database connection
            2. Ingredient tracking sheets
            3. Data entry in cheese production logs
        </div>
    """, unsafe_allow_html=True)
elif data is not None and "DATE" in data.columns:
    invalid_dates = data["DATE"].isna().sum()
    if invalid_dates > 0:
        st.warning(f"⚠️ {invalid_dates} production records have invalid dates")

# Extract view mode from radio selection
if "Allocation Calculator" in view_mode:
    view_mode_clean = "Allocation Calculator"
else:
    view_mode_clean = "Data Overview"

if view_mode_clean == "Allocation Calculator":
    if data is not None and not data.empty:
        # Calculator Interface
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 🧮 Cheese Production Allocation")
        
        with st.form("calculator_form"):
            col1, col2 = st.columns(2)
            with col1:
                num_items = st.number_input(
                    "Number of Ingredients to Allocate", 
                    min_value=1, 
                    max_value=10, 
                    value=1,
                    help="Select how many different cheese ingredients to allocate"
                )
            with col2:
                selected_dept = st.selectbox(
                    "Production Area Filter", 
                    unique_depts,
                    help="Filter by specific cheese production area or view all"
                )
            
            st.markdown("---")
            
            entries = []
            for i in range(num_items):
                st.markdown(f"**Ingredient {i+1}**")
                col1, col2 = st.columns([3, 1])
                with col1:
                    item = st.selectbox(
                        f"Select cheese ingredient {i+1}", 
                        unique_items, 
                        key=f"item_select_{i}",
                        help="Choose from available cheese production ingredients"
                    )
                with col2:
                    qty = st.number_input(
                        "Batch Quantity",
                        min_value=0.1,
                        value=1.0,
                        step=0.1,
                        key=f"qty_input_{i}",
                        help="Enter batch quantity for allocation"
                    )
                
                if item and qty > 0:
                    entries.append((item, qty))
            
            submitted = st.form_submit_button(
                "🧀 Calculate Production Allocation", 
                type="primary",
                use_container_width=True
            )
        
        st.markdown("</div>")
        
        # Process Allocation
        if submitted and entries:
            for idx, (item, qty) in enumerate(entries):
                with st.spinner(f"Calculating allocation for {item}..."):
                    result = allocate_quantity(data, item, qty, selected_dept)
                
                if result is not None and not result.empty:
                    st.markdown('<div class="card">', unsafe_allow_html=True)
                    st.markdown(f"### 📋 Production Allocation for: **{item}**")
                    
                    # Create display dataframe
                    display_df = result[["DEPARTMENT", "PROPORTION", "ALLOCATED_QUANTITY"]].copy()
                    display_df.columns = ["Production Area", "Usage %", "Allocated Quantity"]
                    display_df["Usage %"] = display_df["Usage %"].round(2)
                    
                    # Display table with custom styling
                    st.markdown("#### 📊 Allocation Summary")
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        column_config={
                            "Production Area": st.column_config.TextColumn(width="medium"),
                            "Usage %": st.column_config.ProgressColumn(
                                format="%.1f%%",
                                min_value=0,
                                max_value=100
                            ),
                            "Allocated Quantity": st.column_config.NumberColumn(format="%d units")
                        }
                    )
                    
                    # Summary metrics with cheese theme
                    st.markdown("#### 📈 Batch Statistics")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric(
                            "Total Allocated", 
                            f"{display_df['Allocated Quantity'].sum():.0f}",
                            "units"
                        )
                    with col2:
                        st.metric(
                            "Production Areas", 
                            len(display_df),
                            "locations"
                        )
                    with col3:
                        st.metric(
                            "Batch Size", 
                            f"{qty:.1f}",
                            "total units"
                        )
                    
                    # Chart
                    st.markdown("#### 📊 Allocation Visualization")
                    chart = generate_allocation_chart(result, item)
                    st.plotly_chart(chart, use_container_width=True)
                    
                    # Download option
                    csv = display_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Allocation Report",
                        data=csv,
                        file_name=f"cheese_allocation_{item.replace('/', '_').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    st.markdown("</div>")
                else:
                    st.error(f"❌ No historical production data found for: {item}")
                    st.info(f"💡 This ingredient may be new or not yet tracked in production. Check the Production Analytics view for available ingredients.")
    else:
        st.warning("🧀 No production data available for allocation. Please ensure your cheese production database is connected.")

elif view_mode_clean == "Data Overview":
    if data is not None and not data.empty:
        # Data Overview Interface
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### 📈 Cheese Production Analytics")
        
        # Filters
        col1, col2 = st.columns(2)
        with col1:
            filter_items = st.multiselect(
                "Filter by Ingredients",
                unique_items,
                default=[],
                help="Select specific cheese ingredients to analyze"
            )
        with col2:
            filter_depts = st.multiselect(
                "Filter by Production Areas",
                unique_depts[1:],
                default=[],
                help="Select specific cheese production areas"
            )
        
        # Apply filters
        filtered_data = data.copy()
        if filter_items:
            filtered_data = filtered_data[filtered_data["ITEM_NAME"].isin(filter_items)]
        if filter_depts:
            filtered_data = filtered_data[filtered_data["DEPARTMENT"].isin(filter_depts)]
        
        # Production Statistics
        st.markdown("#### 📊 Production Statistics")
        cols = st.columns(4)
        with cols[0]:
            st.metric("Production Records", f"{len(filtered_data):,}")
        with cols[1]:
            total_qty = filtered_data['QUANTITY'].sum()
            st.metric("Total Ingredients Used", f"{total_qty:,.0f}", "units")
        with cols[2]:
            unique_ingredients = filtered_data["ITEM_NAME"].nunique()
            st.metric("Unique Ingredients", unique_ingredients)
        with cols[3]:
            active_areas = filtered_data["DEPARTMENT"].nunique()
            st.metric("Active Production Areas", active_areas)
        
        # Data Preview
        st.markdown("#### 👁️ Production Data Preview")
        preview_cols = ["DATE", "ITEM_NAME", "DEPARTMENT", "QUANTITY", "UNIT_OF_MEASURE"]
        
        # Format the preview nicely
        preview_data = filtered_data[preview_cols].head(100).copy()
        preview_data["DATE"] = preview_data["DATE"].dt.strftime('%d %b %Y')
        
        st.dataframe(
            preview_data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "DATE": "Production Date",
                "ITEM_NAME": "Cheese Ingredient",
                "DEPARTMENT": "Production Area",
                "QUANTITY": "Quantity",
                "UNIT_OF_MEASURE": "Unit"
            }
        )
        
        if len(filtered_data) > 100:
            st.info(f"📄 Showing 100 of {len(filtered_data)} production records. Use filters to narrow down.")
        
        # Top Ingredients Chart
        st.markdown("#### 🏆 Top 10 Cheese Ingredients by Usage")
        top_items = data.groupby("ITEM_NAME")["QUANTITY"].sum().nlargest(10).reset_index()
        if not top_items.empty:
            fig1 = px.bar(
                top_items,
                x="ITEM_NAME",
                y="QUANTITY",
                title="Most Used Cheese Ingredients",
                color="QUANTITY",
                color_continuous_scale=['#FFD700', '#F4A460', '#DAA520', '#CD853F'],
                labels={"ITEM_NAME": "Cheese Ingredient", "QUANTITY": "Total Usage (units)"}
            )
            fig1.update_layout(
                xaxis_tickangle=-45,
                plot_bgcolor='#FFF8E7',
                paper_bgcolor='#FFF8E7',
                font=dict(color='#5D4037')
            )
            st.plotly_chart(fig1, use_container_width=True)
        
        # Production Area Distribution
        st.markdown("#### 🏭 Ingredient Usage by Production Area")
        dept_dist = data.groupby("DEPARTMENT")["QUANTITY"].sum().reset_index()
        if not dept_dist.empty and len(dept_dist) > 1:
            fig2 = px.pie(
                dept_dist,
                values="QUANTITY",
                names="DEPARTMENT",
                title="Ingredient Distribution Across Cheese Production",
                hole=0.4,
                color_discrete_sequence=['#FFD700', '#F4A460', '#DAA520', '#CD853F', '#8B4513', '#A0522D']
            )
            fig2.update_layout(
                plot_bgcolor='#FFF8E7',
                paper_bgcolor='#FFF8E7',
                font=dict(color='#5D4037')
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        # Monthly Production Trend
        st.markdown("#### 📅 Monthly Production Trend")
        monthly_data = data.copy()
        monthly_data["MONTH"] = monthly_data["DATE"].dt.to_period("M").astype(str)
        monthly_trend = monthly_data.groupby("MONTH")["QUANTITY"].sum().reset_index()
        
        if not monthly_trend.empty:
            fig3 = px.line(
                monthly_trend,
                x="MONTH",
                y="QUANTITY",
                title="Monthly Cheese Ingredient Usage",
                markers=True,
                line_shape="spline",
                color_discrete_sequence=['#8B4513']
            )
            fig3.update_layout(
                xaxis_title="Month",
                yaxis_title="Total Ingredients (units)",
                xaxis_tickangle=-45,
                plot_bgcolor='#FFF8E7',
                paper_bgcolor='#FFF8E7',
                font=dict(color='#5D4037')
            )
            fig3.update_traces(line=dict(width=3))
            st.plotly_chart(fig3, use_container_width=True)
        
        st.markdown("</div>")
    else:
        st.warning("🧀 No production data available for analytics. Please connect to the cheese production database.")

# Footer with Cheese Company Branding
st.markdown("""
    <div class="footer">
        <h4>🧀 Brown's Cheese Company</h4>
        <p style="margin: 10px 0; color: var(--dark-brown);">
            <strong>Artisan Cheese Excellence Since 1979</strong><br>
            Ingredients Allocation System • Version 3.2 • Cheese Production Edition
        </p>
        <p style="font-size: 12px; color: var(--brown); margin: 5px 0;">
            For production support: cheesedata@brownscheese.co.ke | 
            For system issues: it-support@brownscheese.co.ke
        </p>
        <p style="font-size: 11px; color: var(--brown); margin: 10px 0 0 0;">
            © 2024 Brown's Cheese Company. All rights reserved. | 
            Premium Dairy Products | Nairobi, Kenya
        </p>
    </div>
""", unsafe_allow_html=True)

# Add cheese-themed emoji decorations
st.markdown("""
    <div style="text-align: center; margin: 20px 0;">
        <span style="font-size: 24px;">🧀 🐄 🥛 🧈 🍶 🏭 📊 📈</span>
    </div>
""", unsafe_allow_html=True)
