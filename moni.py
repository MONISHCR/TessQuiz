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

# --- Property Mapping Specific SQL Generation Functions (Unchanged - Strict Format) ---

def generate_sql_property_name_check(property_names):
    """
    Generates the '--SELECT * FROM Property' block based on property names.
    Output is commented out per requirement.
    """
    if not property_names:
        return "-- No valid property names found in the filtered data to generate Property check."
    escaped_names = [f"'{escape_sql_string(name)}'" for name in property_names]
    in_clause = ",\n--".join(escaped_names)
    return f"""--SELECT * FROM Property
--WHERE name_txt IN ({in_clause}
--);
"""

def generate_sql_mapping_checks(filtered_df, source_col, target_col):
    """Generates the block of SELECT statements to check existing mappings."""
    if filtered_df.empty:
        return "-- No rows to generate mapping checks."
    select_statements = []
    for index, row in filtered_df.iterrows():
        safe_source_id = escape_sql_string(str(row[source_col]).strip())
        target_id = int(row[target_col])
        select_statements.append(f"SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id}")
    return "\n".join(select_statements)


def generate_sql_mapping_inserts(filtered_df, source_col, target_col, name_col):
    """Generates the block of IF NOT EXISTS...INSERT statements in the specific required format."""
    if filtered_df.empty:
        return "-- No rows to generate mapping inserts."
    insert_blocks = []
    for index, row in filtered_df.iterrows():
        safe_source_id = escape_sql_string(str(row[source_col]).strip())
        target_id = int(row[target_col])
        insert_blocks.append(f"""IF NOT EXISTS (SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id})
    BEGIN
        INSERT INTO admin.PropertyMapping (Source_Pty_Id, Target_Pty_Id, Active, Created)
        VALUES ('{safe_source_id}', {target_id}, 1, GETDATE());
    END""")
    return "\n\n".join(insert_blocks)


# --- Property Mapping Processing Function (Unchanged - Strict Format) ---
def process_property_mapping(uploaded_file):
    """Handles the entire process for the Property Mapping option."""
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = uploaded_file.name

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

    try:
        status_placeholder = st.empty()
        status_placeholder.info(f"Processing file: *{uploaded_file.name}*")

        file_content = io.BytesIO(uploaded_file.getvalue())
        status_placeholder.info("Reading headers...")
        try:
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0, engine='openpyxl')
        except ImportError:
            st.warning("openpyxl not found, using default engine. Consider installing openpyxl (`pip install openpyxl`) for better .xlsx support.", icon="⚠️")
            file_content.seek(0)
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0)
        except Exception as e:
             st.error(f"Error reading Excel headers: {e}")
             st.session_state.error_message = f"Failed to read headers from the Excel file. Ensure it's a valid Excel file. Error: {e}"
             status_placeholder.empty()
             return

        actual_headers = df_header_check.columns.tolist()
        header_map = {hdr.lower().strip(): hdr for hdr in actual_headers}
        col_indices = {}
        missing_cols = []
        found_cols_display = []

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

        status_placeholder.info("Reading full data from sheet...")
        file_content.seek(0)
        try:
            df = pd.read_excel(
                file_content, header=HEADER_ROW_ZERO_INDEXED,
                usecols=list(col_indices.values()), dtype=str, engine='openpyxl'
            )
        except ImportError:
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

        df = df.fillna('')
        st.session_state.rows_read = len(df)
        status_placeholder.info(f"Read {st.session_state.rows_read} data rows. Applying filters...")

        reverse_header_map = {v: k for k, v in col_indices.items()}
        df_processed = df.rename(columns=reverse_header_map)

        df_processed[COL_SOURCE_ID_HDR] = df_processed[COL_SOURCE_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_CODE_HDR] = df_processed[COL_AIM_CODE_HDR].astype(str).str.strip()
        df_processed[COL_EXT_ID_HDR] = df_processed[COL_EXT_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_NAME_HDR] = df_processed[COL_AIM_NAME_HDR].astype(str).str.strip()
        df_processed[COL_TARGET_ID_HDR] = pd.to_numeric(df_processed[COL_TARGET_ID_HDR], errors='coerce')

        filter_mask = (df_processed[COL_SOURCE_ID_HDR] != '')
        filter_mask &= (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_AIM_CODE_HDR])
        filter_mask &= (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_EXT_ID_HDR])
        filter_mask &= df_processed[COL_TARGET_ID_HDR].notna()

        filtered_df = df_processed[filter_mask].copy()

        if not filtered_df.empty:
             filtered_df.loc[:, COL_TARGET_ID_HDR] = filtered_df[COL_TARGET_ID_HDR].astype(int)

        st.session_state.rows_filtered = len(filtered_df)
        status_placeholder.info(f"Found {st.session_state.rows_filtered} rows matching filter criteria. Generating SQL...")

        if not filtered_df.empty:
            sql_blocks = []
            unique_property_names = filtered_df[COL_AIM_NAME_HDR].dropna().unique().tolist()
            valid_property_names = [name for name in unique_property_names if isinstance(name, str) and name.strip()]
            sql_blocks.append(generate_sql_property_name_check(valid_property_names))
            sql_blocks.append(generate_sql_mapping_checks(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR))
            sql_blocks.append(generate_sql_mapping_inserts(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR, COL_AIM_NAME_HDR))
            sql_blocks.append(generate_sql_mapping_checks(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR))

            final_sql_script = "\n\n".join(sql_blocks)
            st.session_state.processed_data = final_sql_script
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
        if 'status_placeholder' in locals() and status_placeholder:
             status_placeholder.error("Processing failed.")


# --- DMG Data Cleanup Specific Functions --- (MODIFIED - Strict Templates) ---
def generate_dmg_cleanup_sql(client_db, start_period, end_period, cleanup_scope):
    """
    Generates the SQL script for DMG Data Cleanup using STRICT templates
    based on the cleanup_scope.
    """
    # Input validation (remains the same)
    if not client_db or not start_period or not end_period or not cleanup_scope:
        raise ValueError("Client DB Name, Start Period, End Period, and Cleanup Scope cannot be empty.")
    if not (re.fullmatch(r"^\d{8}$", start_period) and re.fullmatch(r"^\d{8}$", end_period)):
         raise ValueError("Periods must be numeric and in YYYYMMDD format (e.g., 20241201).")
    try:
        if int(start_period) > int(end_period):
            raise ValueError("Start Period cannot be later than End Period.")
    except ValueError:
         raise ValueError("Periods must be valid numeric dates in YYYYMMDD format.")
    if cleanup_scope not in ["Actuals Only", "All Book Types"]:
        raise ValueError("Invalid Cleanup Scope selected.")

    # Safely quote database name
    safe_client_db = f"[{client_db.replace(']', ']]')}]"

    # --- Select the STRICT template based on Scope ---
    if cleanup_scope == "Actuals Only":
        # Template 1: Actuals Only Cleanup (Uses c.*, JOIN Lookup.Value)
        sql_template = f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: DMG Data Cleanup (Actuals Only)
-- Target Database: {safe_client_db}
-- Filter: EntityType = 'Asset' AND Period BETWEEN {start_period} AND {end_period} AND BookType = 'Actual'
-- ======================================================================

USE {safe_client_db};
GO


select c.*
from CashFlow C
inner join Entity E ON C.EntityKey = E.EntityKey
INNER JOIN Lookup.Value AS BT ON C.BookTypeKey=BT.ValueKey AND BT.ValueID='Actual'
WHERE  E.EntityType = 'Asset' and C.Period between {start_period} and {end_period};
GO

delete C
from CashFlow C
inner join Entity E ON C.EntityKey = E.EntityKey
INNER JOIN Lookup.Value AS BT ON C.BookTypeKey=BT.ValueKey AND BT.ValueID='Actual' -- Corrected C.BookTypeKey
WHERE  E.EntityType = 'Asset' and C.Period between {start_period} and {end_period};

select c.*
from CashFlow C
inner join Entity E ON C.EntityKey = E.EntityKey
INNER JOIN Lookup.Value AS BT ON C.BookTypeKey=BT.ValueKey AND BT.ValueID='Actual' -- Corrected C.BookTypeKey
WHERE  E.EntityType = 'Asset' and C.Period between {start_period} and {end_period};

"""
    elif cleanup_scope == "All Book Types":
        # Template 2: All Book Types Cleanup (Uses *, no Lookup.Value JOIN)
        # NOTE: The original example had 'and EntityType = ...' which is redundant
        # if already joined on EntityKey. Corrected to use standard WHERE clause.
        sql_template = f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: DMG Data Cleanup (All Book Types)
-- Target Database: {safe_client_db}
-- Filter: EntityType = 'Asset' AND Period BETWEEN {start_period} AND {end_period}
-- ======================================================================

USE {safe_client_db};
GO


select *
from CashFlow C 
inner join Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' and Period between {start_period} and {end_period};
GO


delete C
from CashFlow C
inner join Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' and C.Period between {start_period} and {end_period};

select *
from CashFlow C WITH
inner join Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' and Period between {start_period} and {end_period};

"""
    else:
        # This case should not be reached due to prior validation, but included for safety
        raise ValueError(f"Unsupported cleanup scope: {cleanup_scope}")

    return sql_template

# --- DMG Process Function (Unchanged - passes scope) ---
def process_dmg_cleanup(client_db, start_period, end_period, cleanup_scope):
    """Handles the process for DMG Data Cleanup."""
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None

    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for DMG Cleanup: DB='{client_db}', Period='{start_period}-{end_period}', Scope='{cleanup_scope}'")
        final_sql_script = generate_dmg_cleanup_sql(client_db, start_period, end_period, cleanup_scope) # Uses the modified generator
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1
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

# --- AIM Data Cleanup Specific Functions --- (Unchanged)
def generate_aim_cleanup_sql(aim_db, period):
    """Generates the SQL script for AIM Data Cleanup."""
    if not aim_db or not period:
        raise ValueError("AIM Database Name and Period cannot be empty.")
    if not re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", period):
         raise ValueError("Period must be in YYYYMTHMM format (e.g., 2025MTH01).")

    safe_aim_db = f"[{aim_db.replace(']', ']]')}]"
    safe_period = escape_sql_string(period)

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
SELECT COUNT(*) AS RecordCount_BeforeDelete
FROM dbo.line_item li WITH (NOLOCK)
WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account WITH (NOLOCK))
  AND li.period = '{safe_period}';
GO

PRINT '--- Performing Deletion ---';
BEGIN TRAN T1_AIM_Cleanup;

DELETE FROM dbo.line_item
WHERE item_typ_id IN (SELECT acct_id FROM dbo.account)
  AND period = '{safe_period}';

DECLARE @RowsDeleted_AIM INT = @@ROWCOUNT;
PRINT 'Attempted to delete records. Rows affected: ' + CAST(@RowsDeleted_AIM AS VARCHAR);

-- !! IMPORTANT !! Review the count and affected rows before committing.
-- ROLLBACK TRAN T1_AIM_Cleanup;
-- PRINT 'Transaction Rolled Back. No changes were made.';

COMMIT TRAN T1_AIM_Cleanup;
PRINT 'Transaction Committed.';

GO

PRINT '--- After Deletion ---';
SELECT COUNT(*) AS RecordCount_AfterDelete
FROM dbo.line_item li WITH (NOLOCK)
WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account WITH (NOLOCK))
  AND li.period = '{safe_period}';
GO

PRINT '--- AIM Cleanup Script Complete ---';
GO
"""

def process_aim_cleanup(aim_db, period):
    """Handles the process for AIM Data Cleanup."""
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.file_name_processed = None

    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for AIM Cleanup: DB='{aim_db}', Period='{period}'")
        final_sql_script = generate_aim_cleanup_sql(aim_db, period)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1
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


# --- Streamlit App UI --- (Unchanged from v1.7)
st.set_page_config(page_title="SQL Generator Tool", layout="wide")

# Initialize session state variables
defaults = {
    'processed_data': None,
    'error_message': None,
    'queries_generated': 0,
    'rows_read': 0,
    'rows_filtered': 0,
    'file_name_processed': None,
    'current_operation': "Property Mapping",
    'dmg_client_db': "",
    'dmg_start_period': "",
    'dmg_end_period': "",
    'dmg_cleanup_scope': "All Book Types", # Default scope
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
]

def reset_state_on_operation_change():
    for key in defaults:
        st.session_state[key] = defaults[key]
    st.session_state.uploaded_file_key += 1
    pass

previous_operation = st.session_state.current_operation
default_index = 0
if st.session_state.current_operation in operation_options:
    default_index = operation_options.index(st.session_state.current_operation)

selected_operation = st.selectbox(
    "Select the task you want to perform:",
    options=operation_options,
    index=default_index,
    key="operation_selector",
    on_change=reset_state_on_operation_change
)
st.session_state.current_operation = selected_operation

# --- Instructions & Template/Inputs ---
with st.expander("ℹ Instructions and Inputs", expanded=True):
    st.markdown(f"**Selected Operation: {selected_operation}**")
    st.markdown("---")

    if selected_operation == "Property Mapping":
        pm_headers = [ "Provider", "Source_Pty_Id", "AIM Code", "AIM Property Name", "Pty_iTarget_Pty_Idd", "Ext_Id"]
        st.markdown(f"""
            **Instructions for Property Mapping:**
            1.  **Prepare Excel File:** Use `.xlsx` or `.xls`. *Avoid CSV*.
            2.  **Headers:** Ensure first sheet has headers in **Row {HEADER_ROW_ZERO_INDEXED + 1}**. Case-insensitive, match spelling below, unmerged cells.
                *   Required Headers: `{', '.join([f'**{h}**' for h in pm_headers])}`
            3.  **Template:** Download template below.
            4.  **Upload:** Use 'Browse files' in Step 2.
            5.  **Validation:** Checks for required headers.
            6.  **Filtering Logic:** Rows processed if **all** conditions met:
                *   `Source_Pty_Id` == `AIM Code`
                *   `Source_Pty_Id` == `Ext_Id`
                *   `Source_Pty_Id` is **not blank**.
                *   `Pty_iTarget_Pty_Idd` is a **valid number**.
            7.  **Generate:** Click 'Generate Script' in Step 3.
            8.  **Download:** `.sql` script generated matching the required strict format. Customize filename in Results.
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
            1.  **Inputs:** Provide required info in "Step 2".
            2.  **Client Database Name:** Exact target database name (e.g., `AegonDQSI`).
            3.  **Start/End Period:** `YYYYMMDD` format (e.g., `20241201`). Inclusive range for deletion.
            4.  **Cleanup Scope:** Choose the scope:
                *   `Actuals Only`: Deletes records matching criteria **AND** `BookType = 'Actual'` (using `Lookup.Value`). Preserves Budget data. Uses `select c.*` for checks.
                *   `All Book Types`: Deletes records matching criteria regardless of Book Type. Uses `select *` for checks.
            5.  **Generate:** Click 'Generate Script' in Step 3.
            6.  **Review & Download:** `.sql` script generated using the *exact* template for the chosen scope. **Review VERY carefully before execution**, especially the `COMMIT`/`ROLLBACK` and `SELECT` statements.
        """)
    elif selected_operation == "AIM Data Cleanup":
         st.markdown("""
            **Instructions for AIM Data Cleanup:**
            1.  **Inputs:** Provide required info in "Step 2".
            2.  **AIM Database Name:** Exact target AIM database name (e.g., `aim_1019`).
            3.  **Period:** `YYYYMTHMM` format (e.g., `2025MTH01`). Case for 'MTH' doesn't matter. Deletes `line_item` records where `item_typ_id` is in `account` table.
            4.  **Generate:** Click 'Generate Script' in Step 3.
            5.  **Review & Download:** `.sql` script performs deletion with counts and transaction control. **Review VERY carefully before execution**.
        """)
    else:
        st.markdown("Select an operation type above to see specific instructions.")

    st.markdown("---")
    st.markdown("""
        **General Support:**
        *   *Developed by:* Monish & Sanju
        *   *Version:* 1.8 (DMG Strict Templates)
    """) # Updated version number

st.divider()

# --- Step 2: Provide Inputs (File or Fields) ---
st.subheader(f"Step 2: Provide Inputs for '{selected_operation}'")

uploaded_file = None
dmg_client_db = None
dmg_start_period = None
dmg_end_period = None
dmg_cleanup_scope = None
aim_db_name = None
aim_period = None

if selected_operation == "Property Mapping":
    uploaded_file = st.file_uploader(
        f"Upload your completed Excel file (.xlsx, .xls)",
        type=['xlsx', 'xls'],
        key=f"uploader_prop_map_{st.session_state.uploaded_file_key}",
        help="Ensure the file follows the structure described in the instructions. Use the template."
    )
    if uploaded_file and uploaded_file.name != st.session_state.get('file_name_processed'):
         st.session_state.update({
             'processed_data': None, 'error_message': None, 'queries_generated': 0,
             'rows_read': 0, 'rows_filtered': 0,
             'file_name_processed': None, 'sql_file_name_input': ""
         })

elif selected_operation == "DMG Data Cleanup":
    dmg_client_db = st.text_input(
        "Client Database Name:",
        key="dmg_client_db_input",
        value=st.session_state.dmg_client_db,
        placeholder="e.g., AegonDQSI",
        help="Enter the exact name of the database."
    )
    st.session_state.dmg_client_db = dmg_client_db

    col1, col2 = st.columns(2)
    with col1:
        dmg_start_period = st.text_input(
            "Start Period (YYYYMMDD):",
            key="dmg_start_period_input",
            value=st.session_state.dmg_start_period,
            placeholder="e.g., 20241201", max_chars=8,
            help="Inclusive start date (8 digits)."
        )
        st.session_state.dmg_start_period = dmg_start_period
    with col2:
        dmg_end_period = st.text_input(
            "End Period (YYYYMMDD):",
            key="dmg_end_period_input",
            value=st.session_state.dmg_end_period,
            placeholder="e.g., 20241231", max_chars=8,
            help="Inclusive end date (8 digits)."
        )
        st.session_state.dmg_end_period = dmg_end_period

    dmg_cleanup_scope_options = ["Actuals Only", "All Book Types"]
    try:
        scope_index = dmg_cleanup_scope_options.index(st.session_state.dmg_cleanup_scope)
    except ValueError:
        scope_index = 1 # Default to "All Book Types"

    dmg_cleanup_scope = st.radio(
        "Cleanup Scope:",
        options=dmg_cleanup_scope_options,
        index=scope_index,
        key="dmg_cleanup_scope_radio",
        horizontal=True,
        help="Choose 'Actuals Only' (uses Lookup.Value) or 'All Book Types' (no BookType filter)."
    )
    st.session_state.dmg_cleanup_scope = dmg_cleanup_scope

elif selected_operation == "AIM Data Cleanup":
    aim_db_name = st.text_input(
        "AIM Database Name:", key="aim_db_name_input",
        value=st.session_state.aim_db_name,
        placeholder="e.g., aim_1019",
        help="Enter the exact name of the AIM database."
        )
    st.session_state.aim_db_name = aim_db_name

    aim_period = st.text_input(
        "Period (YYYYMTHMM):", key="aim_period_input",
        value=st.session_state.aim_period,
        placeholder="e.g., 2025MTH01", max_chars=9,
        help="Enter the specific period in YYYYMTHMM format (case-insensitive 'MTH')."
        )
    st.session_state.aim_period = aim_period

st.divider()

# --- Step 3: Generate Script ---
st.subheader("Step 3: Generate SQL Script")

can_process = False
if selected_operation == "Property Mapping" and uploaded_file is not None:
    can_process = True
elif selected_operation == "DMG Data Cleanup" and dmg_client_db and dmg_start_period and dmg_end_period and dmg_cleanup_scope:
     if re.fullmatch(r"^\d{8}$", dmg_start_period) and re.fullmatch(r"^\d{8}$", dmg_end_period):
        can_process = True
elif selected_operation == "AIM Data Cleanup" and aim_db_name and aim_period:
     if re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", aim_period):
        can_process = True

process_button = st.button(
    "⚙️ Generate Script",
    disabled=not can_process,
    help="Provide all required inputs in the correct format first." if not can_process else f"Click to generate the script for {selected_operation}"
)

if process_button and can_process:
    st.session_state.current_operation = selected_operation
    if selected_operation == "Property Mapping":
        st.session_state.sql_file_name_input = ""

    with st.spinner(f"Processing '{selected_operation}'... Please wait."):
        if selected_operation == "Property Mapping":
            process_property_mapping(uploaded_file)
        elif selected_operation == "DMG Data Cleanup":
             process_dmg_cleanup( # Passes the scope to use the correct template
                 st.session_state.dmg_client_db,
                 st.session_state.dmg_start_period,
                 st.session_state.dmg_end_period,
                 st.session_state.dmg_cleanup_scope
             )
        elif selected_operation == "AIM Data Cleanup":
             process_aim_cleanup(
                 st.session_state.aim_db_name,
                 st.session_state.aim_period
             )
        else:
            st.warning(f"Processing logic for '{selected_operation}' is not implemented yet.")
            st.session_state.error_message = "Not implemented"
            st.session_state.processed_data = None
            st.session_state.queries_generated = 0
            if uploaded_file: st.session_state.file_name_processed = uploaded_file.name
            else: st.session_state.file_name_processed = "Input Parameters"

# --- Step 4: Results ---
st.divider()
st.subheader("📊 Results")

results_available_for_current_op = (st.session_state.get('processed_data') is not None or st.session_state.get('error_message') is not None) and \
                                   st.session_state.get('current_operation') == selected_operation

if results_available_for_current_op:
    processed_identifier = st.session_state.get('file_name_processed', 'Input Parameters')

    if st.session_state.get('processed_data'):
        st.success(f"✅ Script generation complete for **{selected_operation}** using **{processed_identifier}**!")

        if selected_operation == "Property Mapping":
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Matching Filter", st.session_state.get('rows_filtered', 0))
            col3.metric("Mappings Processed", st.session_state.get('queries_generated', 0), help="Number of rows from filtered data processed for mapping checks/inserts.")
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"]:
             scope_info = f" (Scope: {st.session_state.dmg_cleanup_scope})" if selected_operation == "DMG Data Cleanup" else ""
             st.metric("SQL Script Generated", "1 Block" if st.session_state.get('queries_generated', 0) > 0 else "0 Blocks", help=f"Indicates if the SQL script block was successfully generated{scope_info}.")

        st.subheader("Generated SQL Preview (First ~1000 chars)")
        preview_text = st.session_state.processed_data[:1000] + ("..." if len(st.session_state.processed_data) > 1000 else "")
        st.code(preview_text, language="sql")

        st.subheader("Download Script")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sanitized_operation = re.sub(r'\W+', '_', selected_operation)
        default_filename = f"{sanitized_operation}_Script_{timestamp}.sql"
        if selected_operation == "DMG Data Cleanup":
            scope_tag = "_ActualsOnly" if st.session_state.dmg_cleanup_scope == "Actuals Only" else "_AllBookTypes"
            default_filename = f"{sanitized_operation}{scope_tag}_Script_{timestamp}.sql"

        if selected_operation == "Property Mapping":
            default_prop_map_filename = f"Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_{datetime.now().strftime('%Y%m%d')}.sql"
            current_filename_value = st.session_state.get('sql_file_name_input') or default_prop_map_filename
            user_filename = st.text_input(
                "Enter desired SQL file name (.sql will be added if missing):",
                value=current_filename_value,
                key="sql_file_name_input",
                help="Suggested format: Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_YYYYMMDD.sql. Replace XXXXXX as needed."
            )
            download_filename = user_filename if user_filename else default_prop_map_filename
            if not download_filename.lower().endswith('.sql'):
                download_filename += '.sql'
        else:
            download_filename = default_filename
            st.info(f"Download filename will be: `{download_filename}`")

        st.download_button(
            label=f"📥 Download Full SQL Script ({download_filename})",
            data=st.session_state.processed_data,
            file_name=download_filename,
            mime="text/plain",
            help="Download the generated SQL script as a .sql file. Review carefully before execution!"
        )

    elif st.session_state.get('error_message'):
        error_msg = st.session_state.error_message
        if selected_operation == "Property Mapping" and "No matching rows" in error_msg:
            st.warning(f"⚠️ No data rows matched the filter criteria for **{selected_operation}** in file **{processed_identifier}**. No SQL script was generated.")
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Matching Filter", 0)
            col3.metric("Mappings Processed", 0)
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"] and "Input validation failed" in error_msg:
             st.error(f"❌ Script generation failed for **{selected_operation}** due to invalid inputs.")
             st.error(f"Error details: {error_msg}")
             st.info("Please correct the inputs in Step 2 and try generating the script again.")
        elif error_msg != "Not implemented":
             st.error(f"❌ Processing failed for **{selected_operation}** using **{processed_identifier}**.")
             st.error(f"Error: {error_msg}")
             if selected_operation == "Property Mapping" and st.session_state.get('rows_read', 0) > 0:
                 col1, col2, col3 = st.columns(3)
                 col1.metric("Rows Read", st.session_state.get('rows_read', 0))
                 col2.metric("Rows Matching Filter", "N/A due to error")
                 col3.metric("Mappings Processed", "N/A due to error")
    else:
       st.info("Processing attempted, but no data or error message was recorded. Please try again.")

elif not results_available_for_current_op:
    if st.session_state.get('current_operation') and st.session_state.current_operation != selected_operation and \
       (st.session_state.get('processed_data') or st.session_state.get('error_message')):
        st.info(f"Results displayed previously were for '{st.session_state.current_operation}'.")
        st.info(f"Provide inputs for '{selected_operation}' and click 'Generate Script' above to see results for the current selection.")
    else:
        st.info("Select an operation, provide inputs, and click 'Generate Script' in Step 3 to see results here.")

# --- Footer ---
st.divider()
st.caption(f"SQL Generator Tool | Current Operation: {selected_operation} | Version 1.8") # Updated version number
