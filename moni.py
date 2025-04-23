# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import io
from datetime import datetime
import numpy as np # Needed for checking NaN
import traceback # For detailed error logging
import re # For input validation

# --- General Configuration ---
HEADER_ROW_ZERO_INDEXED = 0      # Row where headers are located (Pandas uses 0-based index)

# --- Helper function to escape single quotes for SQL ---
def escape_sql_string(value):
    """Escapes single quotes in a string for SQL insertion."""
    if isinstance(value, str):
        return value.replace("'", "''")
    return value # Return as is if not a string (e.g., numbers)

# --- Function to create and provide the template file (Property Mapping) ---
def get_template_excel():
    """Creates an Excel template file in memory for Property Mapping."""
    template_headers = [
        "Provider", "Source_Pty_Id", "AIM Code", "AIM Property Name",
        "Pty_iTarget_Pty_Idd", "Ext_Id"
    ]
    example_data = {
         "Provider": ["ExampleProvider"],
         "Source_Pty_Id": ["SRC100"],
         "AIM Code": ["AIM100"],
         "AIM Property Name": ["Example Property One"],
         "Pty_iTarget_Pty_Idd": ["12345"],
         "Ext_Id": ["EXT100"]
     }
    df_template = pd.DataFrame(example_data, columns=template_headers)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_template.to_excel(writer, index=False, sheet_name='MappingData')
    output.seek(0)
    return output

# --- Property Mapping Specific SQL Generation Functions ---

def generate_sql_property_name_check(property_names):
    """
    Generates the 'SELECT * FROM Property' block based on property names.
    This uses the names extracted from the 'AIM Property Name' column.
    """
    if not property_names:
        return "-- No valid property names found in the filtered data to generate Property check."

    # Escape each name and format for the IN clause
    escaped_names = [f"'{escape_sql_string(name)}'" for name in property_names]
    in_clause = ",\n".join(escaped_names)

    # Construct the SQL query
    return f"""
-- Check if Target Properties exist by Name (from 'AIM Property Name' column)
SELECT * FROM Property
WHERE name_txt IN (
{in_clause}
);
GO
"""

def generate_sql_mapping_checks(filtered_df, source_col, target_col):
    """Generates the block of SELECT statements to check existing mappings."""
    if filtered_df.empty:
        return "-- No rows to generate mapping checks."

    select_statements = []
    for index, row in filtered_df.iterrows():
        safe_source_id = escape_sql_string(str(row[source_col]).strip())
        # Target ID should already be validated as numeric and converted to int
        target_id = int(row[target_col])
        select_statements.append(f"SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id};")

    return "\n".join(select_statements) + "\nGO\n"

def generate_sql_mapping_inserts(filtered_df, source_col, target_col, name_col):
    """Generates the block of IF NOT EXISTS...INSERT statements."""
    if filtered_df.empty:
        return "-- No rows to generate mapping inserts."

    insert_blocks = []
    for index, row in filtered_df.iterrows():
        safe_source_id = escape_sql_string(str(row[source_col]).strip())
        target_id = int(row[target_col]) # Assumes already validated int
        safe_name = escape_sql_string(str(row[name_col]).strip()) # For comment

        insert_blocks.append(f"""
-- Map: {safe_name} (Source: {safe_source_id} -> Target: {target_id})
IF NOT EXISTS (SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id})
BEGIN
    INSERT INTO admin.PropertyMapping (Source_Pty_Id, Target_Pty_Id, Active, Created)
    VALUES ('{safe_source_id}', {target_id}, 1, GETDATE());
    PRINT 'Mapping inserted for Source_Pty_Id = ''{safe_source_id}'' AND Target_Pty_Id = {target_id}';
END
ELSE
BEGIN
    PRINT 'Mapping already exists for Source_Pty_Id = ''{safe_source_id}'' AND Target_Pty_Id = {target_id}';
END
""")
        # Adding GO after the entire block.

    return "\n".join(insert_blocks) + "\nGO\n"

# --- Property Mapping Processing Function ---
def process_property_mapping(uploaded_file):
    """Handles the entire process for the Property Mapping option."""
    # Reset state variables for this run
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0 # Represents rows processed for mapping
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = uploaded_file.name # Store filename for display

    # --- Property Mapping Specific Configuration ---
    COL_PROVIDER_HDR = "Provider"
    COL_SOURCE_ID_HDR = "Source_Pty_Id"
    COL_AIM_CODE_HDR = "AIM Code"
    COL_AIM_NAME_HDR = "AIM Property Name" # <--- This is the column used for names
    COL_TARGET_ID_HDR = "Pty_iTarget_Pty_Idd"
    COL_EXT_ID_HDR = "Ext_Id"
    REQUIRED_HEADERS = [
        COL_PROVIDER_HDR, COL_SOURCE_ID_HDR, COL_AIM_CODE_HDR,
        COL_AIM_NAME_HDR, COL_TARGET_ID_HDR, COL_EXT_ID_HDR
    ]
    # --- End Property Mapping Specific Configuration ---

    try:
        status_placeholder = st.empty() # Placeholder for status updates
        status_placeholder.info(f"Processing file: *{uploaded_file.name}*")

        # --- Stage 1: Read Excel File ---
        file_content = io.BytesIO(uploaded_file.getvalue())
        status_placeholder.info("Reading headers...")
        try:
            # Try reading with openpyxl first for better .xlsx support
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0, engine='openpyxl')
        except ImportError:
            st.warning("openpyxl not found, using default engine. Consider installing openpyxl (`pip install openpyxl`) for better .xlsx support.", icon="⚠️")
            file_content.seek(0) # Rewind buffer if first read failed/didn't use openpyxl
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0)
        except Exception as e: # Catch other potential read errors early
             st.error(f"Error reading Excel headers: {e}")
             st.session_state.error_message = f"Failed to read headers from the Excel file. Ensure it's a valid Excel file. Error: {e}"
             status_placeholder.empty()
             return


        actual_headers = df_header_check.columns.tolist()
        header_map = {hdr.lower().strip(): hdr for hdr in actual_headers}
        col_indices = {}
        missing_cols = []
        found_cols_display = []

        # --- Stage 2: Validate Headers ---
        status_placeholder.info("Validating headers for Property Mapping...")
        all_found = True
        for req_hdr in REQUIRED_HEADERS:
            req_hdr_lower = req_hdr.lower()
            if req_hdr_lower in header_map:
                original_case_hdr = header_map[req_hdr_lower]
                col_indices[req_hdr] = original_case_hdr
                found_cols_display.append(f"  ✅ Found **'{req_hdr}'** (as '{original_case_hdr}')")
            else:
                missing_cols.append(f"  ❌ Missing **'{req_hdr}'**")
                all_found = False

        with st.expander("Header Validation Details", expanded=not all_found):
            st.markdown("\n".join(found_cols_display + missing_cols))

        if not all_found:
            st.error(f"Header validation failed. Could not find all required headers in Row {HEADER_ROW_ZERO_INDEXED + 1}.")
            st.session_state.error_message = f"Missing required headers: {', '.join([h.split('**')[1] for h in missing_cols])}"
            status_placeholder.empty()
            return

        st.success("Header validation successful!")

        # --- Stage 3: Read Full Data ---
        status_placeholder.info("Reading full data from sheet...")
        file_content.seek(0) # Rewind buffer before reading full data
        try:
            # Use specified columns and ensure data is read as string initially
            df = pd.read_excel(
                file_content, header=HEADER_ROW_ZERO_INDEXED,
                usecols=list(col_indices.values()), dtype=str, engine='openpyxl'
            )
        except ImportError:
             # Fallback if openpyxl is not installed
             file_content.seek(0)
             df = pd.read_excel(
                 file_content, header=HEADER_ROW_ZERO_INDEXED,
                 usecols=list(col_indices.values()), dtype=str
             )
        except Exception as e:
            st.error(f"Error reading full Excel data: {e}")
            st.session_state.error_message = f"Failed to read data from the Excel file. Error: {e}"
            status_placeholder.empty()
            return

        df = df.fillna('') # Replace Pandas NaN/NaT with empty strings for consistency
        st.session_state.rows_read = len(df)
        status_placeholder.info(f"Read {st.session_state.rows_read} data rows. Applying filters...")

        # --- Stage 4: Data Processing and Filtering ---
        # Create a reverse map to rename columns to our standard internal names
        reverse_header_map = {v: k for k, v in col_indices.items()}
        df_processed = df.rename(columns=reverse_header_map)

        # Clean and type-cast relevant columns BEFORE filtering
        df_processed[COL_SOURCE_ID_HDR] = df_processed[COL_SOURCE_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_CODE_HDR] = df_processed[COL_AIM_CODE_HDR].astype(str).str.strip()
        df_processed[COL_EXT_ID_HDR] = df_processed[COL_EXT_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_NAME_HDR] = df_processed[COL_AIM_NAME_HDR].astype(str).str.strip() # Clean property name
        # Attempt numeric conversion for Target ID, coercing errors to NaN
        df_processed[COL_TARGET_ID_HDR] = pd.to_numeric(df_processed[COL_TARGET_ID_HDR], errors='coerce')

        # Define the filter mask based on cleaned data
        filter_mask = (df_processed[COL_SOURCE_ID_HDR] != '') # Source ID must not be blank
        filter_mask &= (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_AIM_CODE_HDR]) # Source ID == AIM Code
        filter_mask &= (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_EXT_ID_HDR]) # Source ID == Ext ID
        filter_mask &= df_processed[COL_TARGET_ID_HDR].notna() # Target ID must be a valid number (not NaN after coercion)

        # Apply the filter
        filtered_df = df_processed[filter_mask].copy() # Use .copy() to avoid SettingWithCopyWarning

        # Convert Target ID to integer *after* filtering (safe because NaNs are removed)
        if not filtered_df.empty:
             # Use .loc to ensure modification happens on the DataFrame itself
             filtered_df.loc[:, COL_TARGET_ID_HDR] = filtered_df[COL_TARGET_ID_HDR].astype(int)

        st.session_state.rows_filtered = len(filtered_df)
        status_placeholder.info(f"Found {st.session_state.rows_filtered} rows matching filter criteria. Generating SQL...")

        # --- Stage 5: Generate SQL Script (New Structure) ---
        if not filtered_df.empty:
            sql_blocks = []

            # Add header block to SQL script
            sql_blocks.append(f"-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            sql_blocks.append(f"-- Operation Type: Property Mapping")
            sql_blocks.append(f"-- Target Tables: Property, admin.PropertyMapping")
            sql_blocks.append(f"-- Generated from file: {uploaded_file.name}")
            sql_blocks.append(f"-- Filter Condition: {COL_SOURCE_ID_HDR} == {COL_AIM_CODE_HDR} == {COL_EXT_ID_HDR} (non-blank) AND {COL_TARGET_ID_HDR} is numeric")
            sql_blocks.append(f"-- Rows Read: {st.session_state.rows_read}, Rows Filtered: {st.session_state.rows_filtered}")
            sql_blocks.append("-- ======================================================================")
            sql_blocks.append("")

            # Block 1: Check Property Names (Uses 'AIM Property Name' column)
            # Extract unique, non-empty, string property names from the filtered data
            unique_property_names = filtered_df[COL_AIM_NAME_HDR].dropna().unique().tolist()
            valid_property_names = [name for name in unique_property_names if isinstance(name, str) and name.strip()]
            sql_blocks.append(generate_sql_property_name_check(valid_property_names)) # <--- Generates the SELECT * FROM Property...

            # Block 2: Initial Check Mappings
            sql_blocks.append("-- Initial check for existing mappings (Source -> Target)")
            sql_blocks.append(generate_sql_mapping_checks(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR))

            # Block 3: Insert Mappings if they don't exist
            sql_blocks.append("-- Insert mappings if they do not exist")
            sql_blocks.append(generate_sql_mapping_inserts(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR, COL_AIM_NAME_HDR))

            # Block 4: Final Check Mappings (Post-Insert Verification)
            sql_blocks.append("-- Final check for mappings (verify inserts)")
            sql_blocks.append(generate_sql_mapping_checks(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR))

            final_sql_script = "\n".join(sql_blocks)
            st.session_state.processed_data = final_sql_script
            # Count represents the number of mappings attempted (rows in filtered_df)
            st.session_state.queries_generated = len(filtered_df)
            status_placeholder.success("SQL script generated successfully!")

        else:
            status_placeholder.warning("No data rows matched the filter criteria. No SQL script generated.")
            st.session_state.error_message = "No matching rows found for Property Mapping criteria."
            st.session_state.queries_generated = 0

    except Exception as e:
        st.error(f"An error occurred during Property Mapping processing:")
        st.error(str(e))
        with st.expander("Error Details"):
            st.error(f"Traceback: {traceback.format_exc()}")
        st.session_state.processed_data = None
        st.session_state.error_message = f"An unexpected error occurred: {str(e)}"
        st.session_state.queries_generated = 0
        # Ensure status placeholder is updated or cleared on error
        if 'status_placeholder' in locals() and status_placeholder:
             status_placeholder.error("Processing failed.")

# --- DMG Data Cleanup Specific Functions ---
def generate_dmg_cleanup_sql(client_db, start_period, end_period):
    """Generates the SQL script for DMG Data Cleanup."""
    # Input validation
    if not client_db or not start_period or not end_period:
        raise ValueError("Client DB Name, Start Period, and End Period cannot be empty.")
    if not (re.fullmatch(r"^\d{8}$", start_period) and re.fullmatch(r"^\d{8}$", end_period)):
         raise ValueError("Periods must be numeric and in YYYYMMDD format (e.g., 20241201).")
    try:
        if int(start_period) > int(end_period):
            raise ValueError("Start Period cannot be later than End Period.")
    except ValueError: # Catch if conversion to int fails (shouldn't with regex, but good practice)
         raise ValueError("Periods must be valid numeric dates in YYYYMMDD format.")

    # Safely quote database name (handle potential ']' characters)
    safe_client_db = f"[{client_db.replace(']', ']]')}]"

    return f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: DMG Data Cleanup
-- Target Database: {safe_client_db}
-- Target Table: CashFlow (via Entity join)
-- Filter: EntityType = 'Asset' AND Period BETWEEN {start_period} AND {end_period}
-- ======================================================================

USE {safe_client_db};
GO

PRINT '--- Before Deletion ---';
SELECT COUNT(*) AS RecordCount_BeforeDelete
FROM CashFlow C WITH (NOLOCK) -- Use NOLOCK for count if acceptable for your environment
INNER JOIN Entity E WITH (NOLOCK) ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};
-- Optional: Select top N records before delete for inspection
-- SELECT TOP 10 C.* FROM CashFlow C INNER JOIN Entity E ON C.EntityKey = E.EntityKey WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};
GO

PRINT '--- Performing Deletion ---';
BEGIN TRAN T1_DMG_Cleanup;

-- Consider adding a delay if this might run on a busy production server
-- WAITFOR DELAY '00:00:02'; -- Example: wait 2 seconds

DELETE C
FROM CashFlow C
INNER JOIN Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};

DECLARE @RowsDeleted INT = @@ROWCOUNT;
PRINT 'Attempted to delete records. Rows affected: ' + CAST(@RowsDeleted AS VARCHAR);

-- !! IMPORTANT !! Review the count and affected rows before committing.
-- Uncomment the ROLLBACK and comment the COMMIT to test without making changes.
-- ROLLBACK TRAN T1_DMG_Cleanup;
-- PRINT 'Transaction Rolled Back. No changes were made.';

COMMIT TRAN T1_DMG_Cleanup;
PRINT 'Transaction Committed.';

GO

PRINT '--- After Deletion ---';
SELECT COUNT(*) AS RecordCount_AfterDelete
FROM CashFlow C WITH (NOLOCK) -- Use NOLOCK for count if acceptable
INNER JOIN Entity E WITH (NOLOCK) ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};
-- Optional: Select top N records after delete to verify
-- SELECT TOP 10 C.* FROM CashFlow C INNER JOIN Entity E ON C.EntityKey = E.EntityKey WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};
GO

PRINT '--- DMG Cleanup Script Complete ---';
GO
"""

def process_dmg_cleanup(client_db, start_period, end_period):
    """Handles the process for DMG Data Cleanup."""
    # Reset relevant session state variables
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None # Not file based

    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for DMG Cleanup: DB='{client_db}', Period='{start_period}-{end_period}'")
        # generate_dmg_cleanup_sql now includes validation and raises ValueError on failure
        final_sql_script = generate_dmg_cleanup_sql(client_db, start_period, end_period)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1 # Represents one script block generated
        status_placeholder.success("DMG Cleanup SQL script generated successfully!")

    except ValueError as ve:
        st.error(f"Input validation failed: {ve}")
        st.session_state.error_message = f"Input validation failed: {ve}"
        if status_placeholder: status_placeholder.warning("Script generation failed due to invalid input.")
    except Exception as e:
        st.error(f"An error occurred during DMG Cleanup processing:")
        st.error(str(e))
        with st.expander("Error Details"):
            st.error(f"Traceback: {traceback.format_exc()}")
        st.session_state.error_message = f"An unexpected error occurred: {str(e)}"
        if status_placeholder: status_placeholder.error("Processing failed.")

# --- AIM Data Cleanup Specific Functions ---
def generate_aim_cleanup_sql(aim_db, period):
    """Generates the SQL script for AIM Data Cleanup."""
    if not aim_db or not period:
        raise ValueError("AIM Database Name and Period cannot be empty.")
    # Regex allows 'mth' or 'MTH'
    if not re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", period):
         raise ValueError("Period must be in YYYYMTHMM format (e.g., 2025MTH01).")

    safe_aim_db = f"[{aim_db.replace(']', ']]')}]"
    safe_period = escape_sql_string(period) # Escape just in case, though format is strict

    return f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: AIM Data Cleanup
-- Target Database: {safe_aim_db}
-- Target Table: line_item
-- Filter: item_typ_id IN (SELECT acct_id FROM account) AND period = '{safe_period}'
-- ======================================================================

USE {safe_aim_db};
GO

PRINT '--- Before Deletion ---';
-- Check count before deleting
SELECT COUNT(*) AS RecordCount_BeforeDelete
FROM dbo.line_item li WITH (NOLOCK) -- Assuming schema is dbo, use NOLOCK if appropriate
WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account WITH (NOLOCK)) -- Added NOLOCK here too
  AND li.period = '{safe_period}';
-- Optional: Select top N records before delete for inspection
-- SELECT TOP 10 li.* FROM dbo.line_item li WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account) AND li.period = '{safe_period}';
GO

PRINT '--- Performing Deletion ---';
BEGIN TRAN T1_AIM_Cleanup;

-- Consider adding a delay if this might run on a busy production server
-- WAITFOR DELAY '00:00:02'; -- Example: wait 2 seconds

DELETE FROM dbo.line_item -- Specify schema explicitly
WHERE item_typ_id IN (SELECT acct_id FROM dbo.account) -- Subquery to identify relevant item types
  AND period = '{safe_period}';

DECLARE @RowsDeleted_AIM INT = @@ROWCOUNT;
PRINT 'Attempted to delete records. Rows affected: ' + CAST(@RowsDeleted_AIM AS VARCHAR);

-- !! IMPORTANT !! Review the count and affected rows before committing.
-- Uncomment the ROLLBACK and comment the COMMIT to test without making changes.
-- ROLLBACK TRAN T1_AIM_Cleanup;
-- PRINT 'Transaction Rolled Back. No changes were made.';

COMMIT TRAN T1_AIM_Cleanup;
PRINT 'Transaction Committed.';

GO

PRINT '--- After Deletion ---';
-- Check count after deleting
SELECT COUNT(*) AS RecordCount_AfterDelete
FROM dbo.line_item li WITH (NOLOCK)
WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account WITH (NOLOCK))
  AND li.period = '{safe_period}';
-- Optional: Select top N records after delete to verify
-- SELECT TOP 10 li.* FROM dbo.line_item li WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account) AND li.period = '{safe_period}';
GO

PRINT '--- AIM Cleanup Script Complete ---';
GO
"""

def process_aim_cleanup(aim_db, period):
    """Handles the process for AIM Data Cleanup."""
    # Reset relevant session state variables
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None # Not file based

    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for AIM Cleanup: DB='{aim_db}', Period='{period}'")
        # generate_aim_cleanup_sql now includes validation and raises ValueError on failure
        final_sql_script = generate_aim_cleanup_sql(aim_db, period)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1 # Represents one script block generated
        status_placeholder.success("AIM Cleanup SQL script generated successfully!")

    except ValueError as ve:
        st.error(f"Input validation failed: {ve}")
        st.session_state.error_message = f"Input validation failed: {ve}"
        if status_placeholder: status_placeholder.warning("Script generation failed due to invalid input.")
    except Exception as e:
        st.error(f"An error occurred during AIM Cleanup processing:")
        st.error(str(e))
        with st.expander("Error Details"):
            st.error(f"Traceback: {traceback.format_exc()}")
        st.session_state.error_message = f"An unexpected error occurred: {str(e)}"
        if status_placeholder: status_placeholder.error("Processing failed.")


# --- Streamlit App UI ---
st.set_page_config(page_title="SQL Generator Tool", layout="wide")

# Initialize session state variables if they don't exist
# (Ensures robustness if the script reruns unexpectedly)
defaults = {
    'processed_data': None,
    'error_message': None,
    'queries_generated': 0,
    'rows_read': 0,
    'rows_filtered': 0,
    'file_name_processed': None,
    'current_operation': None,
    'dmg_client_db': "",
    'dmg_start_period': "",
    'dmg_end_period': "",
    'aim_db_name': "",
    'aim_period': "",
    'uploaded_file_key': 0,
    'sql_file_name_input': ""
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

st.title("🏢 SQL Script Generator")
st.markdown("Automate SQL script creation from Excel files or inputs for specific operations.")
st.divider()

# --- Step 1: Select Operation ---
st.subheader("Step 1: Select Operation Type")
operation_options = [
    "Property Mapping",
    "DMG Data Cleanup",
    "AIM Data Cleanup",
    # Add future options here
    # "User Access Update (Future)",
    # "Data Cleanup Task (Future)"
]

# Define a callback function to reset states when operation changes
def reset_state_on_operation_change():
    # Reset all general state variables
    for key in defaults:
         st.session_state[key] = defaults[key] # Reset to initial defaults
    # Increment file uploader key to force widget reset if it exists
    st.session_state.uploaded_file_key += 1
    # Clear any displayed status message from previous runs
    # Find a way to clear status_placeholder if it exists - difficult across reruns
    pass # Placeholder for potential future status clearing logic

# Get the currently selected operation (before potential change)
previous_operation = st.session_state.current_operation

selected_operation = st.selectbox(
    "Select the task you want to perform:",
    options=operation_options,
    index=operation_options.index(st.session_state.current_operation) if st.session_state.current_operation in operation_options else 0,
    key="operation_selector",
    on_change=reset_state_on_operation_change # Callback resets state
)

# Store the newly selected operation if it changed
if selected_operation != previous_operation:
    st.session_state.current_operation = selected_operation
    # No need to reset here, on_change handles it.

# --- Instructions & Template/Inputs ---
with st.expander("ℹ Instructions and Inputs", expanded=True):
    st.markdown(f"**Selected Operation: {selected_operation}**")
    st.markdown("---")

    if selected_operation == "Property Mapping":
        pm_headers = [ "Provider", "Source_Pty_Id", "AIM Code", "AIM Property Name", "Pty_iTarget_Pty_Idd", "Ext_Id"]
        st.markdown(f"""
            **Instructions for Property Mapping:**

            1.  **Prepare Excel File:** Use a `.xlsx` or `.xls` file. *Avoid CSV*.
            2.  **Headers:** Ensure the *first sheet* contains the required headers in **Row {HEADER_ROW_ZERO_INDEXED + 1}**. Header names are case-insensitive but must match the spelling below. Cells in the header row should be *unmerged*.
                *   Required Headers: `{', '.join([f'**{h}**' for h in pm_headers])}`
            3.  **Template:** Download the template below to ensure the correct structure and header names. Fill it with your data.
            4.  **Upload:** Use the 'Browse files' button in Step 2 to upload your completed file.
            5.  **Validation:** The tool checks if all required headers are present.
            6.  **Filtering Logic:** Rows are processed *only if* they meet **all** these conditions:
                *   `Source_Pty_Id` value is **equal** to the `AIM Code` value.
                *   `Source_Pty_Id` value is **equal** to the `Ext_Id` value.
                *   `Source_Pty_Id` value is **not blank**.
                *   `Pty_iTarget_Pty_Idd` value is a **valid number** (integer or decimal).
            7.  **Generate:** Click the 'Generate Script' button in Step 3.
            8.  **Download:** If successful, a `.sql` script targeting `Property` (for checking names) and `admin.PropertyMapping` (for checking/inserting mappings) will be available for download. You can customize the filename before downloading in the Results section.
        """)
        st.markdown("**Download Template:**")
        template_excel_bytes = get_template_excel()
        st.download_button(
            label="📄 Download Property Mapping Template (.xlsx)",
            data=template_excel_bytes,
            file_name="PropertyMapping_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    elif selected_operation == "DMG Data Cleanup":
        st.markdown("""
            **Instructions for DMG Data Cleanup:**

            1.  **Inputs:** Provide the required information in the fields below in "Step 2".
            2.  **Client Database Name:** Enter the exact name of the target database (e.g., `AegonDQSI`). Square brackets `[]` are handled automatically if needed.
            3.  **Start/End Period:** Enter the period range in `YYYYMMDD` format (e.g., `20241201`). The script will delete `CashFlow` records for `EntityType = 'Asset'` *between* these dates (inclusive).
            4.  **Generate:** Click the 'Generate Script' button in Step 3.
            5.  **Review & Download:** If successful, a `.sql` script performing the deletion (with counts before/after and transaction control) will be available. **Review the script VERY carefully before execution**, especially the `COMMIT`/`ROLLBACK` section.
        """)
    elif selected_operation == "AIM Data Cleanup":
         st.markdown("""
            **Instructions for AIM Data Cleanup:**

            1.  **Inputs:** Provide the required information in the fields below in "Step 2".
            2.  **AIM Database Name:** Enter the exact name of the target AIM database (e.g., `aim_1019`). Square brackets `[]` are handled automatically if needed.
            3.  **Period:** Enter the specific period in `YYYYMTHMM` format (e.g., `2025MTH01`). Case for 'MTH' doesn't matter. The script will delete `line_item` records for this period where the `item_typ_id` exists in the `account` table (`acct_id`).
            4.  **Generate:** Click the 'Generate Script' button in Step 3.
            5.  **Review & Download:** If successful, a `.sql` script performing the deletion (with counts before/after and transaction control) will be available. **Review the script VERY carefully before execution**, especially the `COMMIT`/`ROLLBACK` section.
        """)
    else:
        st.markdown("Select an operation type above to see specific instructions.")

    st.markdown("---")
    st.markdown("""
        **General Support:**
        *   *Developed by:* Monish & Sanju
        *   *Version:* 1.5 (Added Cleanup Ops, Refined PropMap, Filename Input)
    """)

st.divider()

# --- Step 2: Provide Inputs (File or Fields) ---
st.subheader(f"Step 2: Provide Inputs for '{selected_operation}'")

# Input widgets are conditional based on selected_operation
uploaded_file = None
dmg_client_db = None
dmg_start_period = None
dmg_end_period = None
aim_db_name = None
aim_period = None

if selected_operation == "Property Mapping":
    uploaded_file = st.file_uploader(
        f"Upload your completed Excel file (.xlsx, .xls)",
        type=['xlsx', 'xls'],
        key=f"uploader_prop_map_{st.session_state.uploaded_file_key}", # Use key to force reset on operation change
        help="Ensure the file follows the structure described in the instructions. Use the template."
    )
    # Clear results if a NEW file is uploaded for the SAME operation
    if uploaded_file and uploaded_file.name != st.session_state.get('file_name_processed'):
         st.session_state.update({
             'processed_data': None, 'error_message': None, 'queries_generated': 0,
             'rows_read': 0, 'rows_filtered': 0,
             'file_name_processed': None, # Clear filename until processed
             'sql_file_name_input': "" # Reset custom filename input
         })

elif selected_operation == "DMG Data Cleanup":
    # Use session state to preserve input values across reruns *within the same operation*
    dmg_client_db = st.text_input(
        "Client Database Name:",
        key="dmg_client_db_input",
        value=st.session_state.dmg_client_db, # Bind to session state
        placeholder="e.g., AegonDQSI",
        help="Enter the exact name of the database."
    )
    st.session_state.dmg_client_db = dmg_client_db # Update session state on input change

    col1, col2 = st.columns(2)
    with col1:
        dmg_start_period = st.text_input(
            "Start Period (YYYYMMDD):",
            key="dmg_start_period_input",
            value=st.session_state.dmg_start_period, # Bind
            placeholder="e.g., 20241201", max_chars=8,
            help="Inclusive start date (8 digits)."
        )
        st.session_state.dmg_start_period = dmg_start_period # Update
    with col2:
        dmg_end_period = st.text_input(
            "End Period (YYYYMMDD):",
            key="dmg_end_period_input",
            value=st.session_state.dmg_end_period, # Bind
            placeholder="e.g., 20241231", max_chars=8,
            help="Inclusive end date (8 digits)."
        )
        st.session_state.dmg_end_period = dmg_end_period # Update

elif selected_operation == "AIM Data Cleanup":
    aim_db_name = st.text_input(
        "AIM Database Name:", key="aim_db_name_input",
        value=st.session_state.aim_db_name, # Bind
        placeholder="e.g., aim_1019",
        help="Enter the exact name of the AIM database."
        )
    st.session_state.aim_db_name = aim_db_name # Update

    aim_period = st.text_input(
        "Period (YYYYMTHMM):", key="aim_period_input",
        value=st.session_state.aim_period, # Bind
        placeholder="e.g., 2025MTH01", max_chars=9,
        help="Enter the specific period in YYYYMTHMM format (case-insensitive 'MTH')."
        )
    st.session_state.aim_period = aim_period # Update

# elif selected_operation: # Placeholder for future operations
#     st.info(f"Input configuration for '{selected_operation}' is not yet implemented or does not require specific inputs here.")

st.divider()

# --- Step 3: Generate Script ---
st.subheader("Step 3: Generate SQL Script")

# Determine if the "Generate" button should be enabled
can_process = False
if selected_operation == "Property Mapping" and uploaded_file is not None:
    can_process = True
elif selected_operation == "DMG Data Cleanup" and dmg_client_db and dmg_start_period and dmg_end_period:
     # Add basic format check for enablement, full validation happens on click
     if re.fullmatch(r"^\d{8}$", dmg_start_period) and re.fullmatch(r"^\d{8}$", dmg_end_period):
        can_process = True
elif selected_operation == "AIM Data Cleanup" and aim_db_name and aim_period:
     # Add basic format check for enablement
     if re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", aim_period):
        can_process = True

process_button = st.button(
    "⚙️ Generate Script",
    disabled=not can_process,
    help="Provide all required inputs in the correct format first." if not can_process else f"Click to generate the script for {selected_operation}"
)

if process_button and can_process:
    # Ensure the current operation state matches the button click context
    st.session_state.current_operation = selected_operation
    # Reset custom filename input *only* when generating a new script for Prop Mapping
    if selected_operation == "Property Mapping":
        st.session_state.sql_file_name_input = ""

    with st.spinner(f"Processing '{selected_operation}'... Please wait."):
        if selected_operation == "Property Mapping":
            process_property_mapping(uploaded_file)
        elif selected_operation == "DMG Data Cleanup":
             process_dmg_cleanup(dmg_client_db, dmg_start_period, dmg_end_period)
        elif selected_operation == "AIM Data Cleanup":
             process_aim_cleanup(aim_db_name, aim_period)
        # Add elif blocks for future operations
        else:
            st.warning(f"Processing logic for '{selected_operation}' is not implemented yet.")
            st.session_state.error_message = "Not implemented"
            st.session_state.processed_data = None
            st.session_state.queries_generated = 0
            # Store identifier even if not implemented
            if uploaded_file: st.session_state.file_name_processed = uploaded_file.name
            else: st.session_state.file_name_processed = "Input Parameters"


# --- Step 4: Results ---
st.divider()
st.subheader("📊 Results")

# Check if there are results from a completed run *and* if they match the currently selected operation
results_available_for_current_op = (st.session_state.get('processed_data') is not None or st.session_state.get('error_message') is not None) and \
                                   st.session_state.get('current_operation') == selected_operation

if results_available_for_current_op:
    processed_identifier = st.session_state.get('file_name_processed', 'Input Parameters') # File name or generic text

    # --- Success Case ---
    if st.session_state.get('processed_data'):
        st.success(f"✅ Script generation complete for **{selected_operation}** using **{processed_identifier}**!")

        # Display metrics based on operation type
        if selected_operation == "Property Mapping":
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Matching Filter", st.session_state.get('rows_filtered', 0))
            col3.metric("Mappings Processed", st.session_state.get('queries_generated', 0), help="Number of rows from filtered data processed for mapping checks/inserts.")
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"]:
             st.metric("SQL Script Generated", "1 Block" if st.session_state.get('queries_generated', 0) > 0 else "0 Blocks", help="Indicates if the SQL script block was successfully generated.")

        # --- SQL Preview ---
        st.subheader("Generated SQL Preview (First ~1000 chars)")
        preview_text = st.session_state.processed_data[:1000] + ("..." if len(st.session_state.processed_data) > 1000 else "")
        st.code(preview_text, language="sql")

        # --- Download Section ---
        st.subheader("Download Script")

        # Default filename generation
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sanitized_operation = re.sub(r'\W+', '_', selected_operation) # Replace non-alphanumeric with underscore
        default_filename = f"{sanitized_operation}_Script_{timestamp}.sql"

        # Specific default and input field ONLY for Property Mapping
        if selected_operation == "Property Mapping":
            # Suggest a more specific default format
            default_prop_map_filename = f"Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_{datetime.now().strftime('%Y%m%d')}.sql"
            # Use session state value if it exists (user typed something), otherwise use the specific default
            current_filename_value = st.session_state.get('sql_file_name_input') or default_prop_map_filename

            # Display the text input field for custom filename
            user_filename = st.text_input(
                "Enter desired SQL file name (.sql will be added if missing):",
                value=current_filename_value,
                key="sql_file_name_input", # Link to session state to preserve edits
                help="Suggested format: Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_YYYYMMDD.sql. Replace XXXXXX as needed."
            )
             # Use the user's input (or the default if unchanged/cleared) for the download button
            download_filename = user_filename if user_filename else default_prop_map_filename # Fallback
            # Ensure filename ends with .sql
            if not download_filename.lower().endswith('.sql'):
                download_filename += '.sql'

        else:
            # For other operations, use the standard default filename generated earlier
            download_filename = default_filename
            # Display the filename that will be used (read-only info)
            st.info(f"Download filename will be: `{download_filename}`")


        # Download Button - uses the determined filename
        st.download_button(
            label=f"📥 Download Full SQL Script ({download_filename})",
            data=st.session_state.processed_data,
            file_name=download_filename, # Use the determined filename
            mime="text/plain", # Use text/plain for .sql files
            help="Download the generated SQL script as a .sql file. Review carefully before execution!"
        )

    # --- Error Case ---
    elif st.session_state.get('error_message'):
        error_msg = st.session_state.error_message
        # Specific handling for "No matching rows" in Property Mapping
        if selected_operation == "Property Mapping" and "No matching rows" in error_msg:
            st.warning(f"⚠️ No data rows matched the filter criteria for **{selected_operation}** in file **{processed_identifier}**. No SQL script was generated.")
            # Show relevant metrics even if no script generated
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Matching Filter", 0)
            col3.metric("Mappings Processed", 0)
        # Handle input validation errors for Cleanup operations
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"] and "Input validation failed" in error_msg:
             st.error(f"❌ Script generation failed for **{selected_operation}** due to invalid inputs.")
             st.error(f"Error details: {error_msg}")
             st.info("Please correct the inputs in Step 2 and try generating the script again.")
        # Handle other generic errors
        elif error_msg != "Not implemented": # Don't show "Not implemented" as a failure
             st.error(f"❌ Processing failed for **{selected_operation}** using **{processed_identifier}**.")
             st.error(f"Error: {error_msg}")
             # Optionally show metrics if reading started but failed later
             if selected_operation == "Property Mapping" and st.session_state.get('rows_read', 0) > 0:
                 col1, col2, col3 = st.columns(3)
                 col1.metric("Rows Read", st.session_state.get('rows_read', 0))
                 col2.metric("Rows Matching Filter", "N/A due to error")
                 col3.metric("Mappings Processed", "N/A due to error")
    # --- Fallback if state is somehow inconsistent ---
    else:
       st.info("Processing attempted, but no data or error message was recorded. Please try again.")


# --- Initial State / Different Operation Selected ---
elif not results_available_for_current_op:
    # Check if results exist but for a *different* operation
    if st.session_state.get('current_operation') and st.session_state.current_operation != selected_operation and \
       (st.session_state.get('processed_data') or st.session_state.get('error_message')):
        st.info(f"Results displayed previously were for '{st.session_state.current_operation}'.")
        st.info(f"Provide inputs for '{selected_operation}' and click 'Generate Script' above to see results for the current selection.")
    # Otherwise, it's the initial state or after an operation change before processing
    else:
        st.info("Select an operation, provide inputs, and click 'Generate Script' in Step 3 to see results here.")


# --- Footer ---
st.divider()
st.caption(f"SQL Generator Tool | Current Operation: {selected_operation} | Version 1.5")
