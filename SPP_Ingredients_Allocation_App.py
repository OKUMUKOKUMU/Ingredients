import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
import time
import plotly.express as px
import numpy as np
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Configure page
st.set_page_config(page_title="SPP Ingredients Allocation App", layout="wide")

# Add custom CSS
st.markdown("""
<style>
    .main-header {text-align: center; color: #FFC300; margin-bottom: 20px;}
    .sub-header {margin-top: 15px; margin-bottom: 10px;}
    .highlight {background-color: #f0f2f6; padding: 10px; border-radius: 5px;}
    .footer {text-align: center; color: #888; font-size: 0.8em;}
    .stAlert {margin-top: 20px;}
</style>
""", unsafe_allow_html=True)

# Function to validate Google credentials
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

    # Standardize column names and handle potential missing columns
    expected_columns = ["DATE", "ITEM_SERIAL", "ITEM NAME", "Department", "ISSUED_TO", "QUANTITY", 
                        "UNIT_OF_MEASURE", "ITEM_CATEGORY", "WEEK", "REFERENCE", 
                        "DEPARTMENT_CAT", "BATCH NO.", "STORE", "RECEIVED BY"]
    
    # Handle column name mapping - Treat DEPARTMENT column as "Department" if necessary
    if "DEPARTMENT" in df.columns and "Department" not in df.columns:
        df = df.rename(columns={"DEPARTMENT": "Department"})
    
    # Check if all expected columns are present
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        st.warning(f"⚠️ Missing columns in spreadsheet: {', '.join(missing_columns)}")
        for col in missing_columns:
            df[col] = np.nan
    
    # Ensure column order matches expected order
    df = df[expected_columns]
    
    # Data cleaning and transformation
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df["QUANTITY"] = pd.to_numeric(df["QUANTITY"], errors="coerce")
    
    # Drop rows with missing quantities
    df.dropna(subset=["QUANTITY"], inplace=True)
    
    # Fill missing department values
    df["Department"].fillna("Unspecified", inplace=True)
    
    # Fill missing department categories
    df["DEPARTMENT_CAT"].fillna(df["Department"], inplace=True)
    
    # Fill missing ISSUED_TO values
    df["ISSUED_TO"].fillna("Unspecified", inplace=True)
    
    # Add quarter and year columns for potential filtering
    df["QUARTER"] = df["DATE"].dt.to_period("Q")
    df["YEAR"] = df["DATE"].dt.year
    
    return df


# Function to filter data by date range
def filter_data_by_date_range(df, start_date, end_date):
    """Filter dataframe to include only records within the specified date range"""
    if df.empty:
        return df
        
    # Convert to datetime if needed
    if not isinstance(start_date, pd.Timestamp):
        start_date = pd.Timestamp(start_date)
    if not isinstance(end_date, pd.Timestamp):
        end_date = pd.Timestamp(end_date)
    
    # Include the end_date by setting time to end of day
    end_date = pd.Timestamp(end_date.year, end_date.month, end_date.day, 23, 59, 59)
    
    # Filter to the date range
    date_mask = (df["DATE"] >= start_date) & (df["DATE"] <= end_date)
    filtered_df = df[date_mask].copy()
    
    return filtered_df

@st.cache_data
def calculate_proportion_hierarchical(df, identifier):
    """Calculate proportional usage by department and subdepartment for a specific item"""
    if df.empty:
        return None
        
    identifier = str(identifier).lower()
    # Improved search logic to handle partial matches
    filtered_df = df[(df["ITEM_SERIAL"].astype(str).str.lower() == identifier) |
                     (df["ITEM NAME"].str.lower() == identifier) |
                     (df["ITEM NAME"].str.lower().str.contains(identifier))]

    if filtered_df.empty:
        return None

    # Group by department and subdepartment and calculate total quantity
    usage_summary = filtered_df.groupby(["Department", "ISSUED_TO"])["QUANTITY"].sum()
    
    # Calculate proportions
    total_usage = usage_summary.sum()
    if total_usage == 0:
        return None
        
    proportions = (usage_summary / total_usage) * 100
    
    # Reset index to convert the Series with hierarchical index to DataFrame
    result = proportions.reset_index()
    
    # Sort by department and proportion (descending)
    result = result.sort_values(by=["Department", "QUANTITY"], ascending=[True, False])
    
    # Ensure no null values
    result = result.fillna(0)
    
    return result

def allocate_quantity_hierarchical(df, item_quantities, min_threshold=5):
    """Allocate quantities to departments and subdepartments based on historical usage patterns"""
    if df.empty:
        st.error("❌ No data available for allocation!")
        return {}
        
    allocations = {}
    
    for item, quantity in item_quantities.items():
        if quantity <= 0:
            continue
            
        proportions = calculate_proportion_hierarchical(df, item)
        if proportions is None:
            st.warning(f"⚠️ No usage data found for '{item}'.")
            continue

        # Create a copy to avoid modifying the original dataframe
        allocation_df = proportions.copy()
        allocation_df["Allocated Quantity"] = np.round((allocation_df["QUANTITY"] / 100) * quantity, 1)
        
        # First, group by department to get department-level allocations
        dept_allocations = allocation_df.groupby("Department")[["QUANTITY", "Allocated Quantity"]].sum()
        dept_allocations = dept_allocations.reset_index()
        
        # Handle minimum threshold allocation at department level
        total_allocated = dept_allocations["Allocated Quantity"].sum()
        if total_allocated > 0:
            # Identify departments that would receive less than the minimum threshold
            min_quantity = (quantity * min_threshold / 100)
            underallocated_depts = dept_allocations[dept_allocations["Allocated Quantity"] < min_quantity].copy()
            
            if not underallocated_depts.empty and len(dept_allocations) > len(underallocated_depts):
                # Calculate how much quantity needs to be reallocated
                needed_reallocation = sum(min_quantity - row["Allocated Quantity"] 
                                         for _, row in underallocated_depts.iterrows())
                
                # Set underallocated departments to minimum threshold
                for idx, row in underallocated_depts.iterrows():
                    dept_name = row["Department"]
                    old_alloc = row["Allocated Quantity"]
                    scaling_factor = min_quantity / old_alloc if old_alloc > 0 else 0
                    
                    # Update the department allocation
                    dept_allocations.loc[dept_allocations["Department"] == dept_name, "Allocated Quantity"] = min_quantity
                    
                    # Scale all subdepartments in this department by the same factor
                    mask = allocation_df["Department"] == dept_name
                    if scaling_factor > 0:
                        allocation_df.loc[mask, "Allocated Quantity"] = allocation_df.loc[mask, "Allocated Quantity"] * scaling_factor
                
                # Calculate how much to reduce from other departments
                overallocated_depts = dept_allocations[~dept_allocations["Department"].isin(underallocated_depts["Department"])]
                if not overallocated_depts.empty:
                    total_over = overallocated_depts["Allocated Quantity"].sum()
                    reduction_factor = needed_reallocation / total_over
                    
                    # Reduce allocation proportionally from other departments
                    for _, row in overallocated_depts.iterrows():
                        dept_name = row["Department"]
                        current = row["Allocated Quantity"]
                        new_dept_total = max(0, current - (current * reduction_factor))
                        
                        # Calculate scaling for subdepartments in this department
                        scaling_factor = new_dept_total / current if current > 0 else 0
                        
                        # Update all subdepartments in this department
                        mask = allocation_df["Department"] == dept_name
                        if scaling_factor > 0:
                            allocation_df.loc[mask, "Allocated Quantity"] = allocation_df.loc[mask, "Allocated Quantity"] * scaling_factor
            
            # Special case: if all departments would be under minimum threshold
            elif len(underallocated_depts) == len(dept_allocations) and len(dept_allocations) > 1:
                # Distribute equally among departments
                equal_share = quantity / len(dept_allocations)
                
                for dept_name in dept_allocations["Department"]:
                    # Get subdepartments for this department
                    subdepts = allocation_df[allocation_df["Department"] == dept_name]
                    
                    if not subdepts.empty:
                        # Find total allocation for this department
                        dept_total = subdepts["Allocated Quantity"].sum()
                        if dept_total > 0:
                            # Scale subdepartment allocations to match equal share
                            scaling_factor = equal_share / dept_total
                            allocation_df.loc[allocation_df["Department"] == dept_name, "Allocated Quantity"] = \
                                allocation_df.loc[allocation_df["Department"] == dept_name, "Allocated Quantity"] * scaling_factor
        
        # Round allocated quantities to 1 decimal place for readability
        allocation_df["Allocated Quantity"] = np.round(allocation_df["Allocated Quantity"], 1)
        
        # Check if allocation sum matches original quantity (adjust for rounding errors)
        total_after_allocation = allocation_df["Allocated Quantity"].sum()
        if abs(total_after_allocation - quantity) > 0.5:
            # Adjust the largest allocation to compensate for rounding differences
            idx_max = allocation_df["Allocated Quantity"].idxmax()
            adjustment = quantity - total_after_allocation
            allocation_df.loc[idx_max, "Allocated Quantity"] += adjustment
            allocation_df.loc[idx_max, "Allocated Quantity"] = np.round(allocation_df.loc[idx_max, "Allocated Quantity"], 1)
        
        # Rename columns for better UI display - Ensure ISSUED_TO is renamed to Subdepartment
        allocation_df.rename(columns={
            "ISSUED_TO": "Subdepartment", 
            "QUANTITY": "Proportion (%)"
        }, inplace=True)
        
        allocation_df["Proportion (%)"] = np.round(allocation_df["Proportion (%)"], 1)
        
        # Add to allocations dictionary
        allocations[item] = allocation_df

    return allocations

# Sidebar UI
st.sidebar.markdown("""
    <h1 class='main-header'>SPP Ingredients Allocation App</h1>
""", unsafe_allow_html=True)

# Loading data indicator in the main area instead of sidebar
with st.spinner("Loading data..."):
    full_data = load_data_from_google_sheet()

if full_data.empty:
    st.error("❌ Unable to load data. Please check your connection and credentials.")
else:
    # Show data statistics in the sidebar
    st.sidebar.success(f"✅ Loaded {len(full_data):,} records")
    
    # Date range information from the full dataset
    if not full_data["DATE"].empty:
        data_min_date = full_data["DATE"].min()
        data_max_date = full_data["DATE"].max()
        
        st.sidebar.header("📅 Date Range Selection")
        
        # Default to showing last 3 months of data
        default_start_date = data_max_date - timedelta(days=90)
        if default_start_date < data_min_date:
            default_start_date = data_min_date
            
        # Date selection with default values
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = st.date_input(
                "From:", 
                value=default_start_date,
                min_value=data_min_date,
                max_value=data_max_date
            )
        with col2:
            end_date = st.date_input(
                "To:", 
                value=data_max_date,
                min_value=data_min_date,
                max_value=data_max_date
            )
            
        # Validate date range
        if start_date > end_date:
            st.sidebar.error("⚠️ Start date must be before end date")
            # Swap dates if needed
            start_date, end_date = end_date, start_date
            
        # Filter data based on selected date range
        data = filter_data_by_date_range(full_data, start_date, end_date)
        
        # Show date range info
        date_range_str = f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
        st.sidebar.info(f"📅 Showing data for: {date_range_str}")
        st.sidebar.info(f"📊 {len(data):,} records in selected date range")
        
    else:
        data = full_data
        st.sidebar.warning("⚠️ No date information available in the data")
    
    # Item selection section
    st.sidebar.header("🔍 Item Selection")
    
    # Get basic stats for the filtered data
    unique_items_count = data["ITEM NAME"].nunique()
    st.sidebar.info(f"📦 {unique_items_count} unique items in date range")
    
    # Option to filter by category first
    categories = sorted(data["ITEM_CATEGORY"].dropna().unique().tolist())
    if categories:
        selected_category = st.sidebar.selectbox("Filter by Category (Optional):", 
                                               ["All Categories"] + categories)
        
        if selected_category != "All Categories":
            filtered_data = data[data["ITEM_CATEGORY"] == selected_category]
        else:
            filtered_data = data
    else:
        filtered_data = data
    
    # Get unique item names with sorting for better UX
    unique_item_names = sorted(filtered_data["ITEM NAME"].dropna().unique().tolist())
    
    # Search functionality for better user experience
    search_term = st.sidebar.text_input("Search for items:", "")
    if search_term:
        matching_items = [item for item in unique_item_names 
                         if search_term.lower() in item.lower()]
        if not matching_items:
            st.sidebar.warning(f"No items found matching '{search_term}'")
    else:
        matching_items = unique_item_names
    
    # Select items with limited selections for performance
    max_selections = 10
    selected_identifiers = st.sidebar.multiselect(
        f"Select Items (max {max_selections}):", 
        matching_items, 
        max_selections=max_selections
    )

    # Enter quantities with validation
    if selected_identifiers:
        st.sidebar.subheader("📌 Enter Available Quantities")
        
        # Add option to set same quantity for all
        use_same_qty = st.sidebar.checkbox("Use same quantity for all items")
        
        item_quantities = {}
        if use_same_qty:
            default_qty = st.sidebar.number_input(
                "Quantity for all items:", 
                min_value=0.0, 
                max_value=10000.0,
                step=0.1
            )
            for item in selected_identifiers:
                item_quantities[item] = default_qty
        else:
            for item in selected_identifiers:
                item_quantities[item] = st.sidebar.number_input(
                    f"{item}:", 
                    min_value=0.0, 
                    max_value=10000.0,
                    step=0.1, 
                    key=item
                )
        
        # Option to adjust minimum allocation threshold
        st.sidebar.subheader("⚙️ Advanced Settings")
        min_threshold = st.sidebar.slider(
            "Minimum allocation threshold (%):", 
            min_value=0, 
            max_value=20, 
            value=5,
            help="Departments allocated less than this percentage will be adjusted"
        )
        
        # Calculate button with loading indicator
        if st.sidebar.button("🚀 Calculate Allocation", type="primary"):
            if all(qty == 0 for qty in item_quantities.values()):
                st.sidebar.error("Please enter at least one non-zero quantity")
            else:
                # Use the spinner in the main area instead of sidebar
                with st.spinner("Calculating allocation..."):
                    time.sleep(0.5)  # Brief pause for UX
                    result = allocate_quantity_hierarchical(filtered_data, item_quantities, min_threshold)
                    
                    if result:
                        # Main area results display
                        st.markdown("<h2 class='main-header'>📊 Allocation Results</h2>", unsafe_allow_html=True)
                        
                        # Show date range information in results
                        st.markdown(f"### Analysis Period: {start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}")
                        
                        # Summary card
                        summary_cols = st.columns([1, 1])
                        with summary_cols[0]:
                            st.info(f"📋 Items processed: {len(result)}")
                        with summary_cols[1]:
                            total_qty = sum(sum(table["Allocated Quantity"]) for table in result.values())
                            st.info(f"📦 Total quantity allocated: {total_qty:,.1f}")
                        
                        # Use tabs for better organization when multiple items
                        if len(result) > 1:
                            tabs = st.tabs([f"{item}" for item in result.keys()])
                            for i, (item, table) in enumerate(result.items()):
                                with tabs[i]:
                                    # Display allocation table
                                    st.markdown(f"#### Allocation Table for {item}")
                                    st.dataframe(
                                        table,
                                        use_container_width=True
                                    )
                                    
                                    # Create two sections: Department-level and subdepartment-level visualizations
                                    st.markdown("#### Department-Level Allocation")
                                    
                                    # Aggregate by department for department-level visualizations
                                    dept_summary = table.groupby("Department")[["Proportion (%)", "Allocated Quantity"]].sum().reset_index()
                                    
                                    # Show department-level visualization
                                    display_cols = st.columns([2, 1])
                                    with display_cols[0]:
                                        fig_pie = px.pie(
                                            dept_summary, 
                                            names="Department", 
                                            values="Allocated Quantity",
                                            title=f"Department Quantity Allocation for {item}",
                                            color_discrete_sequence=px.colors.qualitative.Set3
                                        )
                                        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                                        st.plotly_chart(fig_pie, use_container_width=True)
                                    
                                    with display_cols[1]:
                                        # Show bar chart of proportions
                                        fig_bar = px.bar(
                                            dept_summary, 
                                            x="Department", 
                                            y="Proportion (%)",
                                            title="Department Historical Usage Pattern",
                                            color="Proportion (%)",
                                            color_continuous_scale="Blues",
                                        )
                                        fig_bar.update_layout(xaxis_tickangle=-45)
                                        st.plotly_chart(fig_bar, use_container_width=True)
                                    
                                    # Show detailed subdepartment breakdown for each department
                                    st.markdown("#### Subdepartment Breakdown")
                                    
                                    # Create an expander for each department
                                    departments = sorted(table["Department"].unique())
                                    for dept in departments:
                                        with st.expander(f"📊 {dept} Subdepartments"):
                                            dept_data = table[table["Department"] == dept]
                                            
                                            # Show subdepartment allocation table
                                            st.dataframe(dept_data, use_container_width=True)
                                            
                                            # Display charts for subdepartment breakdown
                                            subdept_cols = st.columns([1, 1])
                                            with subdept_cols[0]:
                                                fig_subdept_pie = px.pie(
                                                    dept_data, 
                                                    names="Subdepartment", 
                                                    values="Allocated Quantity",
                                                    title=f"Subdepartment Allocation for {dept}",
                                                    color_discrete_sequence=px.colors.qualitative.Pastel
                                                )
                                                fig_subdept_pie.update_traces(textposition='inside', textinfo='percent+label')
                                                st.plotly_chart(fig_subdept_pie, use_container_width=True)
                                            
                                            with subdept_cols[1]:
                                                if len(dept_data) > 1:  # Only show if there are multiple subdepartments
                                                    fig_subdept_bar = px.bar(
                                                        dept_data, 
                                                        x="Subdepartment", 
                                                        y="Allocated Quantity",
                                                        title=f"Allocation Quantity by Subdepartment",
                                                        color="Subdepartment"
                                                    )
                                                    fig_subdept_bar.update_layout(xaxis_tickangle=-45)
                                                    st.plotly_chart(fig_subdept_bar, use_container_width=True)
                        else:
                            # Simpler layout for single item
                            for item, table in result.items():
                                st.markdown(f"#### 🔹 Allocation for {item}")
                                st.dataframe(
                                    table,
                                    use_container_width=True
                                )
                                
                                # Department level summary
                                st.markdown("#### Department-Level Summary")
                                dept_summary = table.groupby("Department")[["Proportion (%)", "Allocated Quantity"]].sum().reset_index()
                                
                                # Create columns for charts
                                col1, col2 = st.columns([1, 1])
                                with col1:
                                    fig = px.pie(
                                        dept_summary, 
                                        names="Department", 
                                        values="Allocated Quantity",
                                        title=f"Department Quantity Allocation",
                                        color_discrete_sequence=px.colors.qualitative.Set3
                                    )
                                    fig.update_traces(textposition='inside', textinfo='percent+label')
                                    st.plotly_chart(fig, use_container_width=True)
                                
                                with col2:
                                    fig_bar = px.bar(
                                        dept_summary, 
                                        x="Department", 
                                        y="Proportion (%)",
                                        title="Department Historical Usage Pattern",
                                        color="Proportion (%)",
                                        color_continuous_scale="Blues"
                                    )
                                    fig_bar.update_layout(xaxis_tickangle=-45)
                                    st.plotly_chart(fig_bar, use_container_width=True)
                                
                                # Show detailed subdepartment breakdown for each department
                                st.markdown("#### Subdepartment Breakdown")
                                
                                # Create an expander for each department
                                departments = sorted(table["Department"].unique())
                                for dept in departments:
                                    with st.expander(f"📊 {dept} Subdepartments"):
                                        dept_data = table[table["Department"] == dept]
                                        
                                        # Show subdepartment allocation table
                                        st.dataframe(dept_data, use_container_width=True)
                                        
                                        # Display charts for subdepartment breakdown
                                        subdept_cols = st.columns([1, 1])
                                        with subdept_cols[0]:
                                            fig_subdept_pie = px.pie(
                                                dept_data, 
                                                names="Subdepartment", 
                                                values="Allocated Quantity",
                                                title=f"Subdepartment Allocation for {dept}",
                                                color_discrete_sequence=px.colors.qualitative.Pastel
                                            )
                                            fig_subdept_pie.update_traces(textposition='inside', textinfo='percent+label')
                                            st.plotly_chart(fig_subdept_pie, use_container_width=True)
                                        
                                        with subdept_cols[1]:
                                            if len(dept_data) > 1:  # Only show if there are multiple subdepartments
                                                fig_subdept_bar = px.bar(
                                                    dept_data, 
                                                    x="Subdepartment", 
                                                    y="Allocated Quantity",
                                                    title=f"Allocation Quantity by Subdepartment",
                                                    color="Subdepartment"
                                                )
                                                fig_subdept_bar.update_layout(xaxis_tickangle=-45)
                                                st.plotly_chart(fig_subdept_bar, use_container_width=True)
                                
                        # Option to download results
                        st.markdown("### 📥 Download Results")
                        download_cols = st.columns(min(3, len(result)))
                        for i, (item, table) in enumerate(result.items()):
                            with download_cols[i % 3]:
                                csv = table.to_csv(index=False)
                                filename = f"{item.replace(' ', '_')}_allocation_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.csv"
                                st.download_button(
                                    f"Download {item} allocation",
                                    csv,
                                    filename,
                                    "text/csv",
                                    key=f"download_{item}"
                                )
                    else:
                        st.error("❌ No matching data found for the selected items in the date range!")

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "<p class='footer'>Developed by Brown's Data Team<br>©2025 | v2.0</p>", 
        unsafe_allow_html=True
    )
    
    # Help section
    with st.sidebar.expander("ℹ️ Help & Information"):
        st.markdown("""
        **How to use this app:**
        1. Select a date range for historical analysis
        2. Select items from the dropdown menu
        3. Enter the available quantities for each item
        4. Click 'Calculate Allocation' to see results
        
        **Understanding Results:**
        - The app analyzes historical usage patterns to suggest optimal allocations
        - Results are now organized hierarchically by Department and Subdepartment
        - Departments that would receive very small amounts are handled based on the minimum threshold setting
        - Department-level visualizations show the big picture allocation
        - Subdepartment breakdowns show detailed allocation within each department - Visualizations help you understand both
        
        **Need more help?** Contact data-team@browns.com
        """)
