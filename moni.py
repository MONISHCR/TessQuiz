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

# --- Property Mapping Specific Functions ---
def generate_property_mapping_sql_block(source_pty_id, target_pty_id, property_name):
    """Generates the SQL block for a single valid Property Mapping row."""
    safe_source_pty_id = escape_sql_string(source_pty_id)
    safe_property_name = escape_sql_string(property_name)

    # Ensure target_pty_id is treated as a number (remove potential quotes if accidentally added)
    try:
        numeric_target_pty_id = int(target_pty_id)
    except (ValueError, TypeError):
        # Handle cases where conversion fails, maybe log or raise error?
        # For now, let's try to proceed, assuming it might already be numeric,
        # but this indicates a potential data issue upstream.
        numeric_target_pty_id = target_pty_id # Fallback, might cause SQL error if not numeric

    return f"""
-- Property: {safe_property_name} (Source ID: {safe_source_pty_id})
SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_pty_id}' AND Target_Pty_Id = {numeric_target_pty_id};

IF NOT EXISTS (SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_pty_id}' AND Target_Pty_Id = {numeric_target_pty_id})
BEGIN
    PRINT 'Inserting mapping for Source_Pty_Id: {safe_source_pty_id} -> Target_Pty_Id: {numeric_target_pty_id}';
    INSERT INTO admin.PropertyMapping (Source_Pty_Id, Target_Pty_Id, Active, Created)
    VALUES ('{safe_source_pty_id}', {numeric_target_pty_id}, 1, GETDATE());
END
ELSE
BEGIN
    PRINT 'Mapping already exists for Source_Pty_Id: {safe_source_pty_id} -> Target_Pty_Id: {numeric_target_pty_id}';
    PRINT 'Updating Active flag to 1 and setting Created date for existing mapping.'; -- Or just PRINT 'Mapping already exists...'
    -- Optional: Update existing record if needed, e.g., ensure Active=1
    -- UPDATE admin.PropertyMapping SET Active = 1, Created = GETDATE() WHERE Source_Pty_Id = '{safe_source_pty_id}' AND Target_Pty_Id = {numeric_target_pty_id};
END

SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_pty_id}' AND Target_Pty_Id = {numeric_target_pty_id};
GO
"""

def process_property_mapping(uploaded_file):
    """Handles the entire process for the Property Mapping option."""
    # Reset state variables for this run
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = uploaded_file.name # Store filename for display

    # --- Property Mapping Specific Configuration ---
    COL_PROVIDER_HDR = "Provider"
    COL_SOURCE_ID_HDR = "Source_Pty_Id"
    COL_AIM_CODE_HDR = "AIM Code"
    COL_AIM_NAME_HDR = "AIM Property Name"
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
        # Use openpyxl for broader compatibility if available, fallback to default
        try:
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0, engine='openpyxl')
        except ImportError:
            st.warning("openpyxl not found, using default engine. Consider installing openpyxl (`pip install openpyxl`) for better .xlsx support.", icon="⚠️")
            file_content.seek(0) # Reset stream position
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0) # Default engine

        actual_headers = df_header_check.columns.tolist()

        header_map = {hdr.lower().strip(): hdr for hdr in actual_headers} # Use lower + strip for robust matching
        col_indices = {}
        missing_cols = []
        found_cols_display = [] # For nicer display

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

        # Display header validation results clearly
        with st.expander("Header Validation Details", expanded=not all_found):
            st.markdown("\n".join(found_cols_display + missing_cols))

        if not all_found:
            st.error(f"Header validation failed. Could not find all required headers in Row {HEADER_ROW_ZERO_INDEXED + 1}.")
            st.session_state.error_message = f"Missing required headers: {', '.join([h.split('**')[1] for h in missing_cols])}" # Extract names
            status_placeholder.empty() # Clear status message
            return # Stop processing

        st.success("Header validation successful!")

        # --- Stage 3: Read Full Data ---
        status_placeholder.info("Reading full data from sheet...")
        file_content.seek(0)
        try:
            df = pd.read_excel(
                file_content,
                header=HEADER_ROW_ZERO_INDEXED,
                usecols=list(col_indices.values()),
                dtype=str, # Read all as string initially
                engine='openpyxl'
            )
        except ImportError:
             file_content.seek(0)
             df = pd.read_excel(
                 file_content,
                 header=HEADER_ROW_ZERO_INDEXED,
                 usecols=list(col_indices.values()),
                 dtype=str # Read all as string initially
             )

        df = df.fillna('') # Replace Pandas NaN/NaT with empty strings
        st.session_state.rows_read = len(df)
        status_placeholder.info(f"Read {st.session_state.rows_read} data rows. Applying filters...")

        # --- Stage 4: Data Processing and Filtering ---
        # Rename columns to standard names for easier processing
        reverse_header_map = {v: k for k, v in col_indices.items()}
        df_processed = df.rename(columns=reverse_header_map)

        # Clean data before filtering
        df_processed[COL_SOURCE_ID_HDR] = df_processed[COL_SOURCE_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_CODE_HDR] = df_processed[COL_AIM_CODE_HDR].astype(str).str.strip()
        df_processed[COL_EXT_ID_HDR] = df_processed[COL_EXT_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_NAME_HDR] = df_processed[COL_AIM_NAME_HDR].astype(str).str.strip()
        # Convert target ID, coercing errors to NaN for filtering
        df_processed[COL_TARGET_ID_HDR] = pd.to_numeric(df_processed[COL_TARGET_ID_HDR], errors='coerce')

        # Apply Filter Logic specific to Property Mapping
        filter_mask = (df_processed[COL_SOURCE_ID_HDR] != '') # Source ID must not be blank
        filter_mask &= (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_AIM_CODE_HDR])
        filter_mask &= (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_EXT_ID_HDR])
        filter_mask &= df_processed[COL_TARGET_ID_HDR].notna() # Target ID must be numeric

        filtered_df = df_processed[filter_mask].copy()

        # Convert valid Target IDs to integer *after* filtering
        if not filtered_df.empty:
             # Use .loc to avoid SettingWithCopyWarning
             filtered_df.loc[:, COL_TARGET_ID_HDR] = filtered_df[COL_TARGET_ID_HDR].astype(int)

        st.session_state.rows_filtered = len(filtered_df)
        status_placeholder.info(f"Found {st.session_state.rows_filtered} rows matching filter criteria. Generating SQL...")

        # --- Stage 5: Generate SQL Script ---
        if not filtered_df.empty:
            sql_blocks = []
            queries_generated_count = 0

            # Add header block to SQL script
            sql_blocks.append(f"-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            sql_blocks.append(f"-- Operation Type: Property Mapping")
            sql_blocks.append(f"-- Target Table: admin.PropertyMapping")
            sql_blocks.append(f"-- Generated from file: {uploaded_file.name}")
            sql_blocks.append(f"-- Filter Condition: {COL_SOURCE_ID_HDR} == {COL_AIM_CODE_HDR} == {COL_EXT_ID_HDR} (non-blank) AND {COL_TARGET_ID_HDR} is numeric")
            sql_blocks.append(f"-- Rows Read: {st.session_state.rows_read}, Rows Filtered: {st.session_state.rows_filtered}")
            sql_blocks.append("-- ======================================================================")
            sql_blocks.append("")

            for index, row in filtered_df.iterrows():
                # Check for potentially missing values again just in case
                if pd.notna(row[COL_TARGET_ID_HDR]) and str(row[COL_SOURCE_ID_HDR]).strip() != '':
                    sql_block = generate_property_mapping_sql_block(
                        str(row[COL_SOURCE_ID_HDR]).strip(), # Ensure it's string and stripped
                        int(row[COL_TARGET_ID_HDR]),         # Ensure it's int
                        str(row[COL_AIM_NAME_HDR]).strip()   # Ensure it's string and stripped
                    )
                    sql_blocks.append(sql_block)
                    queries_generated_count += 1
                # else: # Optional: Log rows skipped at this stage if needed
                #    st.warning(f"Skipping row {index+HEADER_ROW_ZERO_INDEXED+1} due to unexpected missing data after filtering.")


            final_sql_script = "\n".join(sql_blocks)
            st.session_state.processed_data = final_sql_script
            st.session_state.queries_generated = queries_generated_count
            status_placeholder.success("SQL script generated successfully!")

        else:
            status_placeholder.warning("No data rows matched the filter criteria. No SQL script generated.")
            st.session_state.error_message = "No matching rows found for Property Mapping criteria." # Use this for specific warning display
            st.session_state.queries_generated = 0

    except Exception as e:
        st.error(f"An error occurred during Property Mapping processing:")
        st.error(str(e))
        # Provide more details in an expander for debugging
        with st.expander("Error Details"):
            st.error(f"Traceback: {traceback.format_exc()}")
        st.session_state.processed_data = None
        st.session_state.error_message = f"An unexpected error occurred: {str(e)}"
        st.session_state.queries_generated = 0
        if 'status_placeholder' in locals() and status_placeholder:
             status_placeholder.error("Processing failed.")

# --- DMG Data Cleanup Specific Functions ---
def generate_dmg_cleanup_sql(client_db, start_period, end_period):
    """Generates the SQL script for DMG Data Cleanup."""
    # Basic validation (more can be added)
    if not client_db or not start_period or not end_period:
        raise ValueError("Client DB Name, Start Period, and End Period cannot be empty.")
    if not (start_period.isdigit() and len(start_period) == 8 and end_period.isdigit() and len(end_period) == 8):
         raise ValueError("Periods must be numeric and in YYYYMMDD format (e.g., 20241201).")
    if int(start_period) > int(end_period):
        raise ValueError("Start Period cannot be later than End Period.")

    # Escape client DB name in case it contains special characters (though unlikely for DB names)
    safe_client_db = f"[{client_db.replace(']', ']]')}]" # Basic escaping for brackets

    return f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: DMG Data Cleanup
-- Target Database: {safe_client_db}
-- Target Table: CashFlow (via Entity join)
-- Filter: EntityType = 'Asset' AND Period BETWEEN {start_period} AND {end_period}
-- ======================================================================

PRINT 'Using database: {safe_client_db}';
USE {safe_client_db};
GO

PRINT 'Selecting records to be deleted (before deletion)...';
SELECT C.*
FROM CashFlow C
INNER JOIN Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};

PRINT 'Attempting to delete records...';
DELETE C
FROM CashFlow C
INNER JOIN Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};

PRINT 'Selecting records after deletion attempt (should be empty if successful)...';
SELECT C.*
FROM CashFlow C
INNER JOIN Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' AND C.Period BETWEEN {start_period} AND {end_period};

PRINT 'DMG Data Cleanup script finished for period {start_period} to {end_period}.';
GO
"""

def process_dmg_cleanup(client_db, start_period, end_period):
    """Handles the process for DMG Data Cleanup."""
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    # Reset file-specific state
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None

    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for DMG Cleanup: DB='{client_db}', Period='{start_period}-{end_period}'")
        # Generate SQL
        final_sql_script = generate_dmg_cleanup_sql(client_db, start_period, end_period)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1 # Typically generates one logical script block
        status_placeholder.success("DMG Cleanup SQL script generated successfully!")

    except ValueError as ve:
        st.error(f"Input validation failed: {ve}")
        st.session_state.error_message = f"Input validation failed: {ve}"
        status_placeholder.warning("Script generation failed due to invalid input.")
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
    # Basic validation
    if not aim_db or not period:
        raise ValueError("AIM Database Name and Period cannot be empty.")
    # Regex to check for YYYYMTHMM format (case-insensitive MTH)
    if not re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", period):
         raise ValueError("Period must be in YYYYMTHMM format (e.g., 2025MTH01).")

    safe_aim_db = f"[{aim_db.replace(']', ']]')}]"
    safe_period = escape_sql_string(period) # Escape potential quotes in period

    return f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: AIM Data Cleanup
-- Target Database: {safe_aim_db}
-- Target Table: line_item
-- Filter: item_typ_id IN (SELECT acct_id FROM account) AND period = '{safe_period}'
-- ======================================================================

PRINT 'Using database: {safe_aim_db}';
USE {safe_aim_db};
GO

PRINT 'Selecting records to be deleted (before deletion)...';
SELECT *
FROM line_item
WHERE item_typ_id IN (SELECT acct_id FROM account)
  AND period = '{safe_period}';

PRINT 'Attempting to delete records...';
DELETE FROM line_item
WHERE item_typ_id IN (SELECT acct_id FROM account)
  AND period = '{safe_period}';

PRINT 'Selecting records after deletion attempt (should be empty if successful)...';
SELECT *
FROM line_item
WHERE item_typ_id IN (SELECT acct_id FROM account)
  AND period = '{safe_period}';

PRINT 'AIM Data Cleanup script finished for period {safe_period}.';
GO
"""

def process_aim_cleanup(aim_db, period):
    """Handles the process for AIM Data Cleanup."""
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    # Reset file-specific state
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None

    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for AIM Cleanup: DB='{aim_db}', Period='{period}'")
        # Generate SQL
        final_sql_script = generate_aim_cleanup_sql(aim_db, period)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1 # Typically generates one logical script block
        status_placeholder.success("AIM Cleanup SQL script generated successfully!")

    except ValueError as ve:
        st.error(f"Input validation failed: {ve}")
        st.session_state.error_message = f"Input validation failed: {ve}"
        status_placeholder.warning("Script generation failed due to invalid input.")
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
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'error_message' not in st.session_state:
    st.session_state.error_message = None
if 'queries_generated' not in st.session_state:
    st.session_state.queries_generated = 0
if 'rows_read' not in st.session_state: # Still useful for Property Mapping
    st.session_state.rows_read = 0
if 'rows_filtered' not in st.session_state: # Still useful for Property Mapping
    st.session_state.rows_filtered = 0
if 'file_name_processed' not in st.session_state: # Specific to file uploads
    st.session_state.file_name_processed = None
if 'current_operation' not in st.session_state:
    st.session_state.current_operation = None # Track the operation for which results are shown
if 'dmg_client_db' not in st.session_state:
    st.session_state.dmg_client_db = ""
if 'dmg_start_period' not in st.session_state:
    st.session_state.dmg_start_period = ""
if 'dmg_end_period' not in st.session_state:
    st.session_state.dmg_end_period = ""
if 'aim_db_name' not in st.session_state:
    st.session_state.aim_db_name = ""
if 'aim_period' not in st.session_state:
    st.session_state.aim_period = ""
if 'uploaded_file_key' not in st.session_state: # To help reset file uploader
    st.session_state.uploaded_file_key = 0

st.title("🏢 SQL Script Generator")
st.markdown("Automate SQL script creation from Excel files or inputs for specific operations.")
st.divider()

# --- Step 1: Select Operation ---
st.subheader("Step 1: Select Operation Type")
operation_options = [
    "Property Mapping",
    "DMG Data Cleanup",
    "AIM Data Cleanup",
    # "User Access Update (Future)", # Keep placeholders if needed
    # "Data Cleanup Task (Future)"
]

# Define a callback function to reset states when operation changes
def reset_state_on_operation_change():
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None
    st.session_state.current_operation = None
    # Reset specific inputs
    st.session_state.dmg_client_db = ""
    st.session_state.dmg_start_period = ""
    st.session_state.dmg_end_period = ""
    st.session_state.aim_db_name = ""
    st.session_state.aim_period = ""
    # Increment file uploader key to force reset if needed
    st.session_state.uploaded_file_key += 1


selected_operation = st.selectbox(
    "Select the task you want to perform:",
    options=operation_options,
    index=0, # Default to the first option
    key="operation_selector",
    on_change=reset_state_on_operation_change # Use the callback
)

# --- Instructions & Template/Inputs ---
with st.expander("ℹ Instructions and Inputs", expanded=True): # Default to expanded
    st.markdown(f"**Selected Operation: {selected_operation}**")
    st.markdown("---")

    if selected_operation == "Property Mapping":
        pm_headers = [ "Provider", "Source_Pty_Id", "AIM Code", "AIM Property Name", "Pty_iTarget_Pty_Idd", "Ext_Id"]
        st.markdown(f"""
            **Instructions for Property Mapping:**

            1.  **Prepare Excel File:** Use a `.xlsx` or `.xls` file.
            2.  **Headers:** Ensure the *first sheet* contains the required headers in **Row {HEADER_ROW_ZERO_INDEXED + 1}**. Header names are case-insensitive but must match the spelling below. Cells in the header row must be *unmerged*.
                *   **Required Headers:** `{', '.join([f'**{h}**' for h in pm_headers])}`
            3.  **Template:** Download the template below to ensure the correct structure and header names. Fill it with your data.
            4.  **Upload:** Use the 'Browse files' button in Step 2 to upload your completed file.
            5.  **Validation:** The tool checks if all required headers are present.
            6.  **Filtering Logic:** Rows are processed *only if* they meet **all** these conditions:
                *   `Source_Pty_Id` value is **equal** to the `AIM Code` value.
                *   `Source_Pty_Id` value is **equal** to the `Ext_Id` value.
                *   `Source_Pty_Id` value is **not blank**.
                *   `Pty_iTarget_Pty_Idd` value is a **valid number**.
            7.  **Generate:** Click the 'Generate Script' button in Step 3.
            8.  **Download:** If successful, a `.sql` script targeting `admin.PropertyMapping` will be available for download in the Results section.
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
            2.  **Client Database Name:** Enter the exact name of the target database (e.g., `AegonDQSI`).
            3.  **Start/End Period:** Enter the period range in `YYYYMMDD` format (e.g., `20241201`). The script will delete `CashFlow` records for `EntityType = 'Asset'` *between* these dates (inclusive).
            4.  **Generate:** Click the 'Generate Script' button in Step 3.
            5.  **Download:** If successful, a `.sql` script performing the deletion (with checks before and after) will be available for download. **Review the script carefully before execution.**
        """)
    elif selected_operation == "AIM Data Cleanup":
         st.markdown("""
            **Instructions for AIM Data Cleanup:**

            1.  **Inputs:** Provide the required information in the fields below in "Step 2".
            2.  **AIM Database Name:** Enter the exact name of the target AIM database (e.g., `aim_1019`).
            3.  **Period:** Enter the specific period in `YYYYMTHMM` format (e.g., `2025MTH01`). The script will delete `line_item` records for this period where the `item_typ_id` exists in the `account` table (`acct_id`).
            4.  **Generate:** Click the 'Generate Script' button in Step 3.
            5.  **Download:** If successful, a `.sql` script performing the deletion (with checks before and after) will be available for download. **Review the script carefully before execution.**
        """)
    # Add elif blocks for other future operations here
    # elif selected_operation == "User Access Update (Future)":
    #      st.markdown("**Instructions for User Access Update:**\n\n*   (Details for this future option will be added here.)")
    else:
        st.markdown("Select an operation type above to see specific instructions.")

    st.markdown("---")
    st.markdown("""
        **General Support:**
        *   *Developed by:* Monish & Sanju
        *   *Version:* 1.3 (Streamlit - Added Cleanup Operations)
    """)

st.divider()

# --- Step 2: Provide Inputs (File or Fields) ---
st.subheader(f"Step 2: Provide Inputs for '{selected_operation}'")

uploaded_file = None # Initialize for non-file operations
dmg_client_db = None
dmg_start_period = None
dmg_end_period = None
aim_db_name = None
aim_period = None

if selected_operation == "Property Mapping":
    uploaded_file = st.file_uploader(
        f"Upload your completed Excel file (.xlsx, .xls)",
        type=['xlsx', 'xls'],
        key=f"uploader_prop_map_{st.session_state.uploaded_file_key}", # Use key to help reset
        help="Ensure the file follows the structure described in the instructions."
    )
    # Clear previous non-file results if a file is uploaded
    if uploaded_file and uploaded_file.name != st.session_state.get('file_name_processed'):
         st.session_state.update({
             'processed_data': None, 'error_message': None, 'queries_generated': 0,
             'current_operation': selected_operation
             # Keep rows_read/filtered etc. as they are relevant here
         })
elif selected_operation == "DMG Data Cleanup":
    dmg_client_db = st.text_input(
        "Client Database Name:",
        key="dmg_client_db_input",
        value=st.session_state.dmg_client_db, # Persist value within session
        placeholder="e.g., AegonDQSI",
        help="Enter the exact name of the database."
    )
    st.session_state.dmg_client_db = dmg_client_db # Update session state on input change

    col1, col2 = st.columns(2)
    with col1:
        dmg_start_period = st.text_input(
            "Start Period (YYYYMMDD):",
            key="dmg_start_period_input",
            value=st.session_state.dmg_start_period,
            placeholder="e.g., 20241201",
            max_chars=8,
            help="Inclusive start date."
        )
        st.session_state.dmg_start_period = dmg_start_period
    with col2:
        dmg_end_period = st.text_input(
            "End Period (YYYYMMDD):",
            key="dmg_end_period_input",
            value=st.session_state.dmg_end_period,
            placeholder="e.g., 20241231",
            max_chars=8,
            help="Inclusive end date."
        )
        st.session_state.dmg_end_period = dmg_end_period

elif selected_operation == "AIM Data Cleanup":
    aim_db_name = st.text_input(
        "AIM Database Name:",
        key="aim_db_name_input",
        value=st.session_state.aim_db_name,
        placeholder="e.g., aim_1019",
        help="Enter the exact name of the AIM database."
        )
    st.session_state.aim_db_name = aim_db_name

    aim_period = st.text_input(
        "Period (YYYYMTHMM):",
        key="aim_period_input",
        value=st.session_state.aim_period,
        placeholder="e.g., 2025MTH01",
        max_chars=9, # YYYY MTH MM = 4+3+2 = 9
        help="Enter the specific period in YYYYMTHMM format (case-insensitive 'MTH')."
        )
    st.session_state.aim_period = aim_period

# Add elif for future operations if they need specific inputs

elif selected_operation:
    st.info(f"Input configuration for '{selected_operation}' is not yet implemented or not required.")

st.divider()

# --- Step 3: Generate Script ---
st.subheader("Step 3: Generate SQL Script")

# Determine if inputs are sufficient to enable the button
can_process = False
if selected_operation == "Property Mapping" and uploaded_file is not None:
    can_process = True
elif selected_operation == "DMG Data Cleanup" and dmg_client_db and dmg_start_period and dmg_end_period:
     can_process = True
elif selected_operation == "AIM Data Cleanup" and aim_db_name and aim_period:
     can_process = True
# Add elif for future operations

process_button = st.button("⚙️ Generate Script", disabled=not can_process, help="Provide all required inputs first.")

if process_button and can_process:
    # Set the current operation being processed *before* calling the function
    st.session_state.current_operation = selected_operation

    # Show spinner while processing
    with st.spinner(f"Processing '{selected_operation}'... Please wait."):
        if selected_operation == "Property Mapping":
            process_property_mapping(uploaded_file)
        elif selected_operation == "DMG Data Cleanup":
             process_dmg_cleanup(dmg_client_db, dmg_start_period, dmg_end_period)
        elif selected_operation == "AIM Data Cleanup":
             process_aim_cleanup(aim_db_name, aim_period)
        # Add elif for other operations
        else:
            st.warning(f"Processing logic for '{selected_operation}' is not implemented yet.")
            st.session_state.error_message = "Not implemented"
            st.session_state.queries_generated = 0
            st.session_state.file_name_processed = uploaded_file.name if uploaded_file else None


# --- Step 4: Results ---
st.divider()
st.subheader("📊 Results")

# Display results based on session state *and* if they belong to the currently selected operation
# Check if there *is* a current_operation set (meaning Generate was clicked)
results_ready = st.session_state.get('current_operation') is not None
# Check if the results shown match the *currently selected* operation in the dropdown
operation_results_match = st.session_state.get('current_operation') == selected_operation

if results_ready and operation_results_match:
    processed_identifier = st.session_state.get('file_name_processed', 'Input Parameters') # Use filename or generic text

    if st.session_state.get('processed_data'):
        st.success(f"✅ Script generation complete for **{selected_operation}** using **{processed_identifier}**!")

        # Display Metrics - Adapt based on operation type
        if selected_operation == "Property Mapping":
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read", st.session_state.get('rows_read', 0))
            col2.metric("Rows Matching Filter", st.session_state.get('rows_filtered', 0))
            col3.metric("SQL Blocks Generated", st.session_state.get('queries_generated', 0))
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"]:
             # Only show generated count for cleanup tasks
             st.metric("SQL Script Generated", "1" if st.session_state.get('queries_generated', 0) > 0 else "0") # Should be 1 if successful
        # Add elif for other operations if needed

        st.subheader("Generated SQL Preview (First 1000 chars)")
        preview_text = st.session_state.processed_data[:1000] + ("..." if len(st.session_state.processed_data) > 1000 else "")
        st.code(preview_text, language="sql")

        # --- Download Button ---
        file_name = f"{selected_operation.replace(' ', '')}_Script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        st.download_button(
            label=f"📥 Download Full SQL Script",
            data=st.session_state.processed_data,
            file_name=file_name,
            mime="text/plain",
            help="Download the generated SQL script as a .sql file."
        )

    elif st.session_state.get('error_message'):
        error_msg = st.session_state.error_message
        # Specific warning for "No matching rows" (only relevant for Property Mapping now)
        if selected_operation == "Property Mapping" and "No matching rows" in error_msg:
            st.warning(f"⚠️ No data rows matched the filter criteria for '{selected_operation}' in file **{processed_identifier}**. No SQL script was generated.")
            # Display metrics even if no rows matched
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read", st.session_state.get('rows_read', 0))
            col2.metric("Rows Matching Filter", 0)
            col3.metric("SQL Blocks Generated", 0)
        elif error_msg != "Not implemented":
             st.error(f"❌ Processing failed for **{selected_operation}** using **{processed_identifier}**. Error: {error_msg}")
             # Optionally show metrics like Rows Read if they were populated before the error
             if selected_operation == "Property Mapping" and st.session_state.get('rows_read', 0) > 0:
                 col1, col2, col3 = st.columns(3)
                 col1.metric("Rows Read", st.session_state.get('rows_read', 0))
                 col2.metric("Rows Matching Filter", "N/A")
                 col3.metric("SQL Blocks Generated", "N/A")

        # Don't show anything specific for "Not implemented" here, as it's handled elsewhere or implied

    # elif process_button: # Redundant check if spinner works correctly
    #     st.info("Processing...")

    else:
        # This case might happen if processing finishes but sets neither data nor error (unlikely)
       st.info("Provide inputs and click 'Generate Script' to see results.")

elif not results_ready:
    # No button press yet in this session
    st.info("Provide inputs and click 'Generate Script' to see results.")

elif not operation_results_match:
    # Results are available, but for a *different* operation than currently selected
    st.info(f"Results shown below are for a previous run of '{st.session_state.current_operation}'. Select '{st.session_state.current_operation}' or process new inputs for '{selected_operation}' to see updated results.")
    # Optionally, still show the old results here if desired, clearly marked.


# --- Footer ---
st.divider()
st.caption(f"SQL Generator Tool | Current Operation: {selected_operation} | Version 1.3")