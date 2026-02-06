import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import plotly.express as px
import re
import numpy as np

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

def detect_columns_by_pattern(df_original):
    """
    Detect required columns by content patterns rather than exact names.
    Returns a dictionary mapping standard column names to actual column names.
    """
    column_mapping = {}
    df = df_original.copy()
    
    # Store original column names
    original_columns = list(df.columns)
    
    # Clean column names for easier matching
    df.columns = [str(col).strip().upper() for col in df.columns]
    
    # Create a display of what we found
    detection_report = []
    
    # 1. Detect DATE column - look for columns that contain dates
    date_candidates = []
    for col in df.columns:
        # Try to convert sample values to dates
        sample_values = df[col].dropna().head(10).astype(str)
        date_count = 0
        total_count = 0
        
        for val in sample_values:
            if re.match(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', str(val)) or re.match(r'\d{2,4}[/-]\d{1,2}[/-]\d{1,2}', str(val)):
                date_count += 1
            total_count += 1
        
        if total_count > 0 and date_count / total_count > 0.5:  # More than 50% look like dates
            date_candidates.append((col, date_count/total_count))
    
    if date_candidates:
        # Pick the column with highest date confidence
        date_column = sorted(date_candidates, key=lambda x: x[1], reverse=True)[0][0]
        column_mapping['DATE'] = original_columns[list(df.columns).index(date_column)]
        detection_report.append(f"📅 **DATE** column detected: '{column_mapping['DATE']}'")
    else:
        # Try column names as fallback
        for col in original_columns:
            col_upper = str(col).upper()
            if any(keyword in col_upper for keyword in ['DATE', 'DAY', 'TIME', 'ISSUE_DATE', 'TRANSACTION']):
                column_mapping['DATE'] = col
                detection_report.append(f"📅 **DATE** column detected by name: '{col}'")
                break
    
    # 2. Detect ITEM_NAME column - look for descriptive text columns
    item_name_candidates = []
    for col in df.columns:
        # Skip date column and numeric columns
        if col == column_mapping.get('DATE', ''):
            continue
            
        sample_values = df[col].dropna().head(20).astype(str)
        
        # Check if values look like item names (not too short, not numeric, not dates)
        item_like_count = 0
        total_count = 0
        
        for val in sample_values:
            val_str = str(val).strip()
            if len(val_str) > 2 and not re.match(r'^\d+$', val_str) and not re.match(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', val_str):
                # Check if it contains letters and possibly numbers/symbols
                if any(c.isalpha() for c in val_str):
                    item_like_count += 1
            total_count += 1
        
        if total_count > 0 and item_like_count / total_count > 0.7:  # More than 70% look like item names
            avg_length = sample_values.str.len().mean()
            item_name_candidates.append((col, item_like_count/total_count, avg_length))
    
    if item_name_candidates:
        # Pick the column with highest confidence and reasonable length
        item_name_candidates.sort(key=lambda x: (x[1], -x[2]), reverse=True)
        item_column = item_name_candidates[0][0]
        column_mapping['ITEM_NAME'] = original_columns[list(df.columns).index(item_column)]
        detection_report.append(f"📦 **ITEM_NAME** column detected: '{column_mapping['ITEM_NAME']}'")
    else:
        # Try column names as fallback
        for col in original_columns:
            col_upper = str(col).upper()
            if any(keyword in col_upper for keyword in ['ITEM', 'NAME', 'DESCRIPTION', 'MATERIAL', 'INGREDIENT', 'PRODUCT']):
                column_mapping['ITEM_NAME'] = col
                detection_report.append(f"📦 **ITEM_NAME** column detected by name: '{col}'")
                break
    
    # 3. Detect QUANTITY column - look for numeric columns
    quantity_candidates = []
    for col in df.columns:
        if col == column_mapping.get('DATE', '') or col == column_mapping.get('ITEM_NAME', ''):
            continue
            
        # Try to convert to numeric
        try:
            numeric_values = pd.to_numeric(df[col], errors='coerce')
            numeric_count = numeric_values.notna().sum()
            total_count = len(df[col])
            
            if total_count > 0 and numeric_count / total_count > 0.7:  # More than 70% are numeric
                # Check if values are typically > 0 (quantities usually are)
                positive_count = (numeric_values > 0).sum()
                quantity_candidates.append((col, numeric_count/total_count, positive_count/numeric_count if numeric_count > 0 else 0))
        except:
            continue
    
    if quantity_candidates:
        # Pick the column with highest numeric confidence and positive values
        quantity_candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        quantity_column = quantity_candidates[0][0]
        column_mapping['QUANTITY'] = original_columns[list(df.columns).index(quantity_column)]
        detection_report.append(f"🔢 **QUANTITY** column detected: '{column_mapping['QUANTITY']}'")
    else:
        # Try column names as fallback
        for col in original_columns:
            col_upper = str(col).upper()
            if any(keyword in col_upper for keyword in ['QTY', 'QUANTITY', 'AMOUNT', 'VOLUME', 'NUMBER', 'COUNT']):
                column_mapping['QUANTITY'] = col
                detection_report.append(f"🔢 **QUANTITY** column detected by name: '{col}'")
                break
    
    # 4. Detect DEPARTMENT column - look for categorical text columns
    dept_candidates = []
    for col in df.columns:
        if col in [column_mapping.get(key, '') for key in ['DATE', 'ITEM_NAME', 'QUANTITY']]:
            continue
            
        sample_values = df[col].dropna().head(50).astype(str)
        
        # Check if values look like department names (not too long, categorical)
        if len(sample_values) > 0:
            unique_count = sample_values.nunique()
            total_count = len(sample_values)
            
            # Departments typically have limited unique values relative to total
            if 2 <= unique_count <= 20 and total_count > 0:
                # Check if values are reasonably short
                avg_length = sample_values.str.len().mean()
                if avg_length < 50:  # Department names are usually not very long
                    dept_candidates.append((col, unique_count, avg_length))
    
    if dept_candidates:
        # Pick the column with moderate number of unique values
        dept_candidates.sort(key=lambda x: (abs(x[1] - 10), x[2]))  # Prefer around 10 unique values
        dept_column = dept_candidates[0][0]
        column_mapping['DEPARTMENT'] = original_columns[list(df.columns).index(dept_column)]
        detection_report.append(f"🏭 **DEPARTMENT** column detected: '{column_mapping['DEPARTMENT']}'")
    else:
        # Try column names as fallback
        for col in original_columns:
            col_upper = str(col).upper()
            if any(keyword in col_upper for keyword in ['DEPT', 'DEPARTMENT', 'AREA', 'LOCATION', 'SECTION', 'ZONE']):
                column_mapping['DEPARTMENT'] = col
                detection_report.append(f"🏭 **DEPARTMENT** column detected by name: '{col}'")
                break
    
    # 5. Try to detect ITEM_SERIAL column (optional)
    serial_candidates = []
    for col in df.columns:
        if col in [column_mapping.get(key, '') for key in ['DATE', 'ITEM_NAME', 'QUANTITY', 'DEPARTMENT']]:
            continue
            
        sample_values = df[col].dropna().head(20).astype(str)
        
        # Check if values look like serial numbers (mix of letters and numbers, specific patterns)
        serial_patterns = [r'INGR-\d+', r'[A-Z]{2,}\d+', r'\d+-[A-Z]+', r'[A-Z]+\d+[A-Z]*']
        serial_count = 0
        total_count = 0
        
        for val in sample_values:
            for pattern in serial_patterns:
                if re.match(pattern, str(val).strip()):
                    serial_count += 1
                    break
            total_count += 1
        
        if total_count > 0 and serial_count / total_count > 0.5:
            serial_candidates.append((col, serial_count/total_count))
    
    if serial_candidates:
        serial_candidates.sort(key=lambda x: x[1], reverse=True)
        serial_column = serial_candidates[0][0]
        column_mapping['ITEM_SERIAL'] = original_columns[list(df.columns).index(serial_column)]
        detection_report.append(f"🏷️ **ITEM_SERIAL** column detected: '{column_mapping['ITEM_SERIAL']}'")
    
    # Check if we have all required columns
    required = ['DATE', 'ITEM_NAME', 'QUANTITY', 'DEPARTMENT']
    missing = [col for col in required if col not in column_mapping]
    
    if missing:
        detection_report.append(f"❌ **Missing columns:** {', '.join(missing)}")
    
    return column_mapping, detection_report

def load_all_data_from_google_sheet():
    """
    Load ALL data from Google Sheets with automatic column detection.
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
            
            # Create DataFrame with original headers
            df_original = pd.DataFrame(data_rows, columns=headers)
            
            # Display original structure
            with st.expander("🔍 View Original Sheet Structure", expanded=False):
                st.write(f"**Number of columns:** {len(headers)}")
                st.write(f"**Number of rows:** {len(data_rows)}")
                st.write("**Column names:**")
                for i, col in enumerate(headers):
                    st.write(f"{i+1}. '{col}'")
                
                st.write("\n**Sample data (first 3 rows):**")
                st.dataframe(df_original.head(3))
            
            # Detect columns automatically
            column_mapping, detection_report = detect_columns_by_pattern(df_original)
            
            # Show detection report
            st.sidebar.markdown("### 🔍 Column Detection Report")
            for report in detection_report:
                st.sidebar.write(report)
            
            # Check if we have all required columns
            required = ['DATE', 'ITEM_NAME', 'QUANTITY', 'DEPARTMENT']
            missing = [col for col in required if col not in column_mapping]
            
            if missing:
                st.error(f"Missing required columns: {', '.join(missing)}")
                st.info("Please check if your sheet contains columns for: Date, Item Name, Quantity, and Department")
                
                # Allow manual column mapping
                st.warning("### Manual Column Mapping Required")
                st.write("Please map the columns manually:")
                
                manual_mapping = {}
                for req_col in required:
                    if req_col not in column_mapping:
                        available_cols = [col for col in headers if col not in manual_mapping.values()]
                        if available_cols:
                            selected = st.selectbox(
                                f"Select column for '{req_col}'",
                                options=available_cols,
                                key=f"manual_{req_col}"
                            )
                            manual_mapping[req_col] = selected
                
                # Update column mapping with manual selections
                column_mapping.update(manual_mapping)
                
                if all(col in column_mapping for col in required):
                    st.success("✓ All required columns mapped!")
                else:
                    return None
            
            # Now rename columns and process data
            df = df_original.copy()
            
            # Rename columns to standard names
            rename_dict = {}
            for std_name, actual_name in column_mapping.items():
                if actual_name in df.columns:
                    rename_dict[actual_name] = std_name
            
            df = df.rename(columns=rename_dict)
            
            # Add any missing standard columns with empty values
            for std_name in required:
                if std_name not in df.columns:
                    df[std_name] = ""
            
            # Process DATE column
            if 'DATE' in df.columns:
                # Try multiple date formats
                df["DATE"] = pd.to_datetime(df["DATE"], errors='coerce', dayfirst=True)
                
                # If that fails, try other common formats
                if df["DATE"].isna().all():
                    df["DATE"] = pd.to_datetime(df["DATE"], errors='coerce')
            
            # Process QUANTITY column
            if 'QUANTITY' in df.columns:
                def clean_quantity(value):
                    if pd.isna(value):
                        return np.nan
                    
                    # Convert to string and clean
                    str_val = str(value).strip()
                    
                    # Remove non-numeric characters except decimal point and minus
                    cleaned = re.sub(r'[^\d.-]', '', str_val)
                    
                    try:
                        if cleaned:
                            return float(cleaned)
                        else:
                            return np.nan
                    except:
                        return np.nan
                
                df["QUANTITY"] = df["QUANTITY"].apply(clean_quantity)
            
            # Clean text columns
            text_columns = ['ITEM_NAME', 'DEPARTMENT', 'ITEM_SERIAL', 'ISSUED_TO', 
                          'UNIT_OF_MEASURE', 'ITEM_CATEGORY', 'DEPARTMENT_CAT', 'STORE']
            
            for col in text_columns:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.strip()
                else:
                    # Add missing text columns with empty values
                    df[col] = ""
            
            # Remove rows with invalid quantities or dates
            initial_count = len(df)
            
            if 'QUANTITY' in df.columns:
                df = df.dropna(subset=["QUANTITY"])
                df = df[df["QUANTITY"] > 0]
            
            # Add quarter info for rows with valid dates
            if 'DATE' in df.columns:
                df["QUARTER"] = df["DATE"].dt.to_period("Q")
            
            # Show summary
            filtered_count = initial_count - len(df)
            
            st.sidebar.success(f"""
            ✅ **Data Loaded Successfully!**
            
            **Summary:**
            • Records loaded: {len(df):,}
            • Date range: {df['DATE'].min().strftime('%d/%m/%Y') if 'DATE' in df.columns and not df.empty else 'N/A'} 
              to {df['DATE'].max().strftime('%d/%m/%Y') if 'DATE' in df.columns and not df.empty else 'N/A'}
            • Unique items: {df['ITEM_NAME'].nunique() if 'ITEM_NAME' in df.columns and not df.empty else 0}
            • Unique departments: {df['DEPARTMENT'].nunique() if 'DEPARTMENT' in df.columns and not df.empty else 0}
            • Total quantity: {df['QUANTITY'].sum():,.0f if 'QUANTITY' in df.columns and not df.empty else 0}
            """)
            
            # Show cleaned data sample
            with st.expander("📊 View Cleaned Data Sample", expanded=False):
                display_cols = []
                for col in ['DATE', 'ITEM_NAME', 'DEPARTMENT', 'QUANTITY', 'ITEM_SERIAL', 'UNIT_OF_MEASURE']:
                    if col in df.columns:
                        display_cols.append(col)
                
                if display_cols:
                    display_df = df[display_cols].head(10).copy()
                    if 'DATE' in display_df.columns:
                        display_df['DATE'] = display_df['DATE'].dt.strftime('%d/%m/%Y')
                    st.dataframe(display_df)
            
            return df
            
        except Exception as e:
            st.error(f"Error loading data: {str(e)}")
            import traceback
            st.error(f"Detailed error: {traceback.format_exc()}")
            return None

# ... (keep all other functions the same: filter_data_by_date_range, get_all_cached_data, 
# find_similar_items, calculate_proportion, allocate_quantity, generate_allocation_chart)

# Streamlit App Configuration and CSS (keep the same)

# Update the sidebar section to include column mapping options:

# In the sidebar, after loading data, add:
with st.sidebar:
    # ... (existing sidebar code until after data is loaded)
    
    # Add column mapping viewer
    if st.session_state.get('all_data') is not None:
        st.markdown("---")
        st.markdown("### 🗂️ Column Mapping")
        
        # Show what columns were detected
        if hasattr(st.session_state.all_data, 'attrs') and 'column_mapping' in st.session_state.all_data.attrs:
            mapping = st.session_state.all_data.attrs['column_mapping']
            for std_name, actual_name in mapping.items():
                st.write(f"**{std_name}:** `{actual_name}`")
        
        # Allow manual override if needed
        if st.checkbox("Override column mapping", key="override_mapping"):
            st.warning("⚠️ Advanced feature: Use only if automatic detection failed")
            
            available_cols = list(st.session_state.all_data.columns)
            col1, col2 = st.columns(2)
            
            with col1:
                date_col = st.selectbox("Date column", available_cols, 
                                       index=available_cols.index('DATE') if 'DATE' in available_cols else 0)
                item_col = st.selectbox("Item Name column", available_cols,
                                       index=available_cols.index('ITEM_NAME') if 'ITEM_NAME' in available_cols else 0)
            
            with col2:
                qty_col = st.selectbox("Quantity column", available_cols,
                                      index=available_cols.index('QUANTITY') if 'QUANTITY' in available_cols else 0)
                dept_col = st.selectbox("Department column", available_cols,
                                       index=available_cols.index('DEPARTMENT') if 'DEPARTMENT' in available_cols else 0)
            
            if st.button("Apply manual mapping", use_container_width=True):
                # Rename columns based on manual selection
                rename_dict = {
                    date_col: 'DATE',
                    item_col: 'ITEM_NAME',
                    qty_col: 'QUANTITY',
                    dept_col: 'DEPARTMENT'
                }
                
                st.session_state.all_data = st.session_state.all_data.rename(columns=rename_dict)
                st.success("Column mapping updated!")
                st.rerun()
