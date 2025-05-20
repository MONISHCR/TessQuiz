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

# --- Property Mapping Specific SQL Generation Functions (NEW/REVISED) ---

def generate_sql_property_name_check(property_names):
    """
    Generates the '--SELECT * FROM Property' block based on property names.
    Output is commented out per requirement. (Unchanged)
    """
    if not property_names:
        return "-- No valid property names found in the filtered data to generate Property check."
    escaped_names = [f"'{escape_sql_string(name)}'" for name in property_names]
    in_clause = ",\n--".join(escaped_names)
    return f"""--SELECT * FROM Property
--WHERE name_txt IN ({in_clause}
--);
"""

def generate_sql_individual_mapping_block(source_id, target_id, property_name, action="insert"):
    """
    Generates a complete SQL block for a single mapping (insert or delete)
    in the specific required format.
    """
    safe_source_id = escape_sql_string(str(source_id).strip())
    # Target ID should be validated as numeric before calling this function
    target_id_int = int(target_id)
    comment_name = f"-- {escape_sql_string(str(property_name).strip())}" if pd.notna(property_name) and str(property_name).strip() else "-- Property Name Not Provided"

    select_query = f"SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id_int}"

    if action == "insert":
        operation_sql = f"""IF NOT EXISTS (SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id_int})
    BEGIN
        INSERT INTO admin.PropertyMapping (Source_Pty_Id, Target_Pty_Id, Active, Created)
        VALUES ('{safe_source_id}', {target_id_int}, 1, GETDATE());
    END"""
    elif action == "delete":
        operation_sql = f"""IF EXISTS (SELECT * FROM admin.PropertyMapping WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id_int})
    BEGIN
        DELETE FROM admin.PropertyMapping
        WHERE Source_Pty_Id = '{safe_source_id}' AND Target_Pty_Id = {target_id_int};
    END"""
    else:
        return "-- Invalid action specified for mapping block"

    return f"""{comment_name}
{select_query}

{operation_sql}

{select_query}"""


# --- Property Mapping Processing Function (REVISED) ---
def process_property_mapping(uploaded_file):
    """Handles the entire process for the Property Mapping option."""
    st.session_state.processed_data = None
    st.session_state.error_message = None
    st.session_state.queries_generated = 0
    st.session_state.rows_read = 0
    st.session_state.rows_filtered = 0
    st.session_state.pm_mismatched_rows_processed = 0 # Reset specific counter
    st.session_state.file_name_processed = uploaded_file.name

    COL_PROVIDER_HDR = "Provider"
    COL_SOURCE_ID_HDR = "Source_Pty_Id"
    COL_AIM_CODE_HDR = "AIM Code"
    COL_AIM_NAME_HDR = "AIM Property Name"
    COL_TARGET_ID_HDR = "Pty_iTarget_Pty_Idd" # Corrected from Pty_iTarget_Pty_Idd to Pty_iTarget_Pty_Idd
    COL_EXT_ID_HDR = "Ext_Id"
    REQUIRED_HEADERS = [
        COL_PROVIDER_HDR, COL_SOURCE_ID_HDR, COL_AIM_CODE_HDR,
        COL_AIM_NAME_HDR, COL_TARGET_ID_HDR, COL_EXT_ID_HDR
    ]

    try:
        status_placeholder = st.empty()
        status_placeholder.info(f"Processing file: *{uploaded_file.name}* for **{st.session_state.pm_action}** action.")

        file_content = io.BytesIO(uploaded_file.getvalue())
        # Header reading and validation (same as before)
        status_placeholder.info("Reading headers...")
        try:
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0, engine='openpyxl')
        except ImportError:
            st.warning("openpyxl not found, using default engine.", icon="⚠️")
            file_content.seek(0)
            df_header_check = pd.read_excel(file_content, header=HEADER_ROW_ZERO_INDEXED, nrows=0)
        except Exception as e:
             st.error(f"Error reading Excel headers: {e}")
             st.session_state.error_message = f"Failed to read headers. Error: {e}"
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
            st.error(f"Header validation failed. Missing headers in Row {HEADER_ROW_ZERO_INDEXED + 1}.")
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
            st.session_state.error_message = f"Failed to read data. Error: {e}"
            status_placeholder.empty()
            return

        df = df.fillna('')
        st.session_state.rows_read = len(df)
        status_placeholder.info(f"Read {st.session_state.rows_read} data rows. Applying filters for '{st.session_state.pm_action}'...")

        reverse_header_map = {v: k for k, v in col_indices.items()}
        df_processed = df.rename(columns=reverse_header_map)

        # Data type conversions and stripping
        df_processed[COL_SOURCE_ID_HDR] = df_processed[COL_SOURCE_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_CODE_HDR] = df_processed[COL_AIM_CODE_HDR].astype(str).str.strip()
        df_processed[COL_EXT_ID_HDR] = df_processed[COL_EXT_ID_HDR].astype(str).str.strip()
        df_processed[COL_AIM_NAME_HDR] = df_processed[COL_AIM_NAME_HDR].astype(str).str.strip()
        df_processed[COL_TARGET_ID_HDR] = pd.to_numeric(df_processed[COL_TARGET_ID_HDR], errors='coerce')

        # Base validity: Source_Pty_Id must not be blank, Target_Pty_Id must be a valid number
        is_target_id_valid_mask = df_processed[COL_TARGET_ID_HDR].notna()
        is_source_id_valid_mask = df_processed[COL_SOURCE_ID_HDR] != ''
        base_valid_rows_mask = is_target_id_valid_mask & is_source_id_valid_mask

        filtered_df_list = []

        if st.session_state.pm_action == "Insert/Update":
            # Strict match criteria: Source_Pty_Id == AIM Code == Ext_Id
            strict_match_criteria_mask = (
                (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_AIM_CODE_HDR]) &
                (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_EXT_ID_HDR])
            )
            final_strict_mask = base_valid_rows_mask & strict_match_criteria_mask
            df_strict_matches = df_processed[final_strict_mask]
            if not df_strict_matches.empty:
                filtered_df_list.append(df_strict_matches)
            
            status_placeholder.info(f"Found {len(df_strict_matches)} rows matching strict criteria.")

            if st.session_state.pm_include_mismatches:
                # Mismatch criteria: Base valid, but NOT strict match
                # (Source_Pty_Id != AIM Code OR Source_Pty_Id != Ext_Id)
                potential_mismatch_mask = base_valid_rows_mask & ~strict_match_criteria_mask
                df_mismatches = df_processed[potential_mismatch_mask]
                if not df_mismatches.empty:
                    filtered_df_list.append(df_mismatches)
                    st.session_state.pm_mismatched_rows_processed = len(df_mismatches)
                    status_placeholder.info(f"Including {len(df_mismatches)} additional rows with Source_Pty_Id mismatches (as selected).")
                else:
                    status_placeholder.info("No additional rows found for Source_Pty_Id mismatch inclusion.")


        elif st.session_state.pm_action == "Delete":
            # For delete, only base validity (Source_Pty_Id and Target_Pty_Id are present and valid)
            df_delete_candidates = df_processed[base_valid_rows_mask]
            if not df_delete_candidates.empty:
                filtered_df_list.append(df_delete_candidates)
            status_placeholder.info(f"Found {len(df_delete_candidates)} rows eligible for deletion.")

        if filtered_df_list:
            filtered_df = pd.concat(filtered_df_list).drop_duplicates().copy() # drop_duplicates just in case, though logic should prevent it
        else:
            filtered_df = pd.DataFrame(columns=df_processed.columns) # Empty DataFrame with correct columns

        if not filtered_df.empty:
             # Ensure Target_Pty_Id is int for SQL generation after all filtering
             filtered_df.loc[:, COL_TARGET_ID_HDR] = filtered_df[COL_TARGET_ID_HDR].astype(int)

        st.session_state.rows_filtered = len(filtered_df)
        status_placeholder.info(f"Total {st.session_state.rows_filtered} rows for processing. Generating SQL...")

        if not filtered_df.empty:
            sql_blocks_main_script = []
            
            # 1. Generate Property Name Check (SELECT * FROM Property...)
            unique_property_names = filtered_df[COL_AIM_NAME_HDR].dropna().unique().tolist()
            valid_property_names = [name for name in unique_property_names if isinstance(name, str) and name.strip()]
            sql_blocks_main_script.append(generate_sql_property_name_check(valid_property_names))

            # 2. Generate individual mapping blocks
            action_for_sql = "insert" if st.session_state.pm_action == "Insert/Update" else "delete"
            individual_mapping_sqls = []
            for index, row in filtered_df.iterrows():
                # AIM Property Name is passed for the comment
                property_name_for_comment = row[COL_AIM_NAME_HDR] if COL_AIM_NAME_HDR in row else None

                block = generate_sql_individual_mapping_block(
                    source_id=row[COL_SOURCE_ID_HDR],
                    target_id=row[COL_TARGET_ID_HDR],
                    property_name=property_name_for_comment,
                    action=action_for_sql
                )
                individual_mapping_sqls.append(block)
            
            if individual_mapping_sqls:
                 sql_blocks_main_script.append("\n\n".join(individual_mapping_sqls))

            final_sql_script = "\n\n".join(sql_blocks_main_script)
            st.session_state.processed_data = final_sql_script
            st.session_state.queries_generated = len(filtered_df) # Each row in filtered_df produces one block
            status_placeholder.success(f"SQL script for Property Mapping ({st.session_state.pm_action}) generated successfully!")
        else:
            status_placeholder.warning(f"No data rows matched the criteria for '{st.session_state.pm_action}'. No SQL script generated.")
            st.session_state.error_message = f"No matching rows found for Property Mapping '{st.session_state.pm_action}' criteria."
            st.session_state.queries_generated = 0
            if st.session_state.pm_action == "Insert/Update" and st.session_state.pm_include_mismatches and st.session_state.pm_mismatched_rows_processed > 0:
                 st.session_state.error_message += f" Although mismatch inclusion was enabled, processed {st.session_state.pm_mismatched_rows_processed} such rows which might have been filtered out by other issues."


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
from CashFlow C
inner join Entity E ON C.EntityKey = E.EntityKey
WHERE E.EntityType = 'Asset' and Period between {start_period} and {end_period};

"""
    else:
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
        final_sql_script = generate_dmg_cleanup_sql(client_db, start_period, end_period, cleanup_scope)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1 # Indicates one script block
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
select *from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}' and bud_value IS NULL;

-- !! IMPORTANT !! Review the count and affected rows before committing.
-- ROLLBACK TRAN T1_AIM_Cleanup;
-- PRINT 'Transaction Rolled Back. No changes were made.';
delete from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}' and bud_value IS NULL;

COMMIT TRAN T1_AIM_Cleanup;
PRINT 'Transaction Committed.';
update line_item set act_value = null where item_typ_id in (select acct_id from account) and period = '{safe_period}' AND act_value IS NOT NULL and bud_value IS NOT NULL

GO

PRINT '--- After Deletion ---';
SELECT COUNT(*) AS RecordCount_AfterDelete
FROM dbo.line_item li WITH (NOLOCK)
WHERE li.item_typ_id IN (SELECT acct_id FROM dbo.account WITH (NOLOCK))
  AND li.period = '{safe_period}';
GO
select *from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}';

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
        st.session_state.queries_generated = 1 # Indicates one script block
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
    'dmg_cleanup_scope': "All Book Types",
    'aim_db_name': "",
    'aim_period': "",
    'uploaded_file_key': 0,
    'sql_file_name_input': "",
    'pm_action': "Insert/Update", # New for Property Mapping action
    'pm_include_mismatches': False, # New for Property Mapping mismatch handling
    'pm_mismatched_rows_processed': 0, # Counter for mismatched rows
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
    # Keep current operation to avoid re-selecting it, but reset everything else
    current_op_buffer = st.session_state.get('operation_selector', "Property Mapping")
    for key in defaults:
        st.session_state[key] = defaults[key]
    st.session_state.current_operation = current_op_buffer # Restore intended selection
    st.session_state.uploaded_file_key += 1 # Increment to allow re-upload of same file name
    # Explicitly reset PM specific states (already done by defaults, but good for clarity)
    st.session_state.pm_action = "Insert/Update"
    st.session_state.pm_include_mismatches = False
    st.session_state.pm_mismatched_rows_processed = 0


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
# Update current_operation if selectbox changes it directly without on_change (e.g. first load)
if st.session_state.operation_selector != st.session_state.current_operation:
    reset_state_on_operation_change() # Ensure full reset if changed
    st.session_state.current_operation = st.session_state.operation_selector


# --- Instructions & Template/Inputs ---
with st.expander("ℹ Instructions and Inputs", expanded=True):
    st.markdown(f"**Selected Operation: {st.session_state.current_operation}**")
    st.markdown("---")

    if st.session_state.current_operation == "Property Mapping":
        pm_headers = [ "Provider", "Source_Pty_Id", "AIM Code", "AIM Property Name", "Pty_iTarget_Pty_Idd", "Ext_Id"]
        st.markdown(f"""
            **Instructions for Property Mapping:**
            1.  **Prepare Excel File:** Use `.xlsx` or `.xls`. *Avoid CSV*.
            2.  **Headers:** Ensure first sheet has headers in **Row {HEADER_ROW_ZERO_INDEXED + 1}**. Case-insensitive, match spelling below, unmerged cells.
                *   Required Headers: `{', '.join([f'**{h}**' for h in pm_headers])}`
            3.  **Template:** Download template below.
            4.  **Select Action:** Choose 'Insert/Update' or 'Delete' in Step 2.
            5.  **Upload:** Use 'Browse files' in Step 2.
            6.  **Validation:** Checks for required headers.
            7.  **Filtering Logic for 'Insert/Update':**
                *   Base: `Source_Pty_Id` not blank, `Pty_iTarget_Pty_Idd` is valid number.
                *   Strict: Base + `Source_Pty_Id` == `AIM Code` == `Ext_Id`.
                *   Optional Mismatch: If "Include mismatches..." checked, also includes Base valid rows where `Source_Pty_Id` *doesn't* match `AIM Code` OR `Ext_Id`.
            8.  **Filtering Logic for 'Delete':**
                *   Processes rows where `Source_Pty_Id` is not blank and `Pty_iTarget_Pty_Idd` is a valid number.
            9.  **Generate:** Click 'Generate Script' in Step 3.
            10. **Download:** `.sql` script generated. Customize filename in Results.
        """)
        st.markdown("**Download Template:**")
        template_excel_bytes = get_template_excel()
        st.download_button(
            label="📄 Download Property Mapping Template (.xlsx)",
            data=template_excel_bytes,
            file_name="PropertyMapping_Template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    elif st.session_state.current_operation == "DMG Data Cleanup":
        st.markdown("""
            **Instructions for DMG Data Cleanup:**
            1.  **Inputs:** Provide required info in "Step 2".
            2.  **Client Database Name:** Exact target database name (e.g., `AegonDQSI`).
            3.  **Start/End Period:** `YYYYMMDD` format (e.g., `20241201`). Inclusive range for deletion.
            4.  **Cleanup Scope:** Choose the scope:
                *   `Actuals Only`: Deletes records matching criteria **AND** `BookType = 'Actual'`.
                *   `All Book Types`: Deletes records matching criteria regardless of Book Type.
            5.  **Generate:** Click 'Generate Script' in Step 3.
            6.  **Review & Download:** `.sql` script generated. **Review VERY carefully before execution.**
        """)
    elif st.session_state.current_operation == "AIM Data Cleanup":
         st.markdown("""
            **Instructions for AIM Data Cleanup:**
            1.  **Inputs:** Provide required info in "Step 2".
            2.  **AIM Database Name:** Exact target AIM database name (e.g., `aim_1019`).
            3.  **Period:** `YYYYMTHMM` format (e.g., `2025MTH01`). Deletes `line_item` records.
            4.  **Generate:** Click 'Generate Script' in Step 3.
            5.  **Review & Download:** `.sql` script performs deletion. **Review VERY carefully before execution.**
        """)
    else:
        st.markdown("Select an operation type above to see specific instructions.")

    st.markdown("---")
    st.markdown("""
        **General Support:**
        *   *Developed by:* Monish & Sanju
        *   *Version:* 1.9 (Property Mapping Updates - Insert/Delete/Mismatch)
    """)

st.divider()

# --- Step 2: Provide Inputs (File or Fields) ---
st.subheader(f"Step 2: Provide Inputs for '{st.session_state.current_operation}'")

uploaded_file = None
dmg_client_db = None
dmg_start_period = None
dmg_end_period = None
dmg_cleanup_scope = None
aim_db_name = None
aim_period = None

if st.session_state.current_operation == "Property Mapping":
    # Property Mapping specific options
    st.session_state.pm_action = st.radio(
        "Mapping Action:",
        options=["Insert/Update", "Delete"],
        index=0 if st.session_state.pm_action == "Insert/Update" else 1,
        key="pm_action_radio",
        horizontal=True,
        help="Choose 'Insert/Update' to add new mappings, or 'Delete' to remove existing ones."
    )

    if st.session_state.pm_action == "Insert/Update":
        st.session_state.pm_include_mismatches = st.checkbox(
            "Include mappings where Source_Pty_Id doesn't match AIM Code / Ext_Id?",
            value=st.session_state.pm_include_mismatches,
            key="pm_include_mismatches_checkbox",
            help="If checked, rows where Source_Pty_Id is valid but doesn't match AIM Code or Ext_Id will also be processed for insert. Review generated SQL carefully for these."
        )
    else: # If action is "Delete", mismatch option is not relevant
        st.session_state.pm_include_mismatches = False # Ensure it's reset if user switches

    uploaded_file = st.file_uploader(
        f"Upload your completed Excel file (.xlsx, .xls) for Property Mapping:",
        type=['xlsx', 'xls'],
        key=f"uploader_prop_map_{st.session_state.uploaded_file_key}", # Use key to allow re-upload
        help="Ensure the file follows the structure described in the instructions. Use the template."
    )
    if uploaded_file and uploaded_file.name != st.session_state.get('file_name_processed'):
         # Reset results if a new file is uploaded or current file changes
         st.session_state.update({
             'processed_data': None, 'error_message': None, 'queries_generated': 0,
             'rows_read': 0, 'rows_filtered': 0, 'pm_mismatched_rows_processed': 0,
             'file_name_processed': None, 'sql_file_name_input': ""
         })

elif st.session_state.current_operation == "DMG Data Cleanup":
    dmg_client_db = st.text_input(
        "Client Database Name:",
        key="dmg_client_db_input",
        value=st.session_state.dmg_client_db,
        on_change=lambda: st.session_state.update({'dmg_client_db': st.session_state.dmg_client_db_input}),
        placeholder="e.g., AegonDQSI"
    )
    col1, col2 = st.columns(2)
    with col1:
        dmg_start_period = st.text_input(
            "Start Period (YYYYMMDD):",
            key="dmg_start_period_input",
            value=st.session_state.dmg_start_period,
            on_change=lambda: st.session_state.update({'dmg_start_period': st.session_state.dmg_start_period_input}),
            placeholder="e.g., 20241201", max_chars=8
        )
    with col2:
        dmg_end_period = st.text_input(
            "End Period (YYYYMMDD):",
            key="dmg_end_period_input",
            value=st.session_state.dmg_end_period,
            on_change=lambda: st.session_state.update({'dmg_end_period': st.session_state.dmg_end_period_input}),
            placeholder="e.g., 20241231", max_chars=8
        )
    dmg_cleanup_scope_options = ["Actuals Only", "All Book Types"]
    scope_idx = dmg_cleanup_scope_options.index(st.session_state.dmg_cleanup_scope) if st.session_state.dmg_cleanup_scope in dmg_cleanup_scope_options else 1
    dmg_cleanup_scope = st.radio(
        "Cleanup Scope:",
        options=dmg_cleanup_scope_options,
        index=scope_idx,
        key="dmg_cleanup_scope_radio",
        horizontal=True,
        on_change=lambda: st.session_state.update({'dmg_cleanup_scope': st.session_state.dmg_cleanup_scope_radio})
    )


elif st.session_state.current_operation == "AIM Data Cleanup":
    aim_db_name = st.text_input(
        "AIM Database Name:", key="aim_db_name_input",
        value=st.session_state.aim_db_name,
        on_change=lambda: st.session_state.update({'aim_db_name': st.session_state.aim_db_name_input}),
        placeholder="e.g., aim_1019"
        )
    aim_period = st.text_input(
        "Period (YYYYMTHMM):", key="aim_period_input",
        value=st.session_state.aim_period,
        on_change=lambda: st.session_state.update({'aim_period': st.session_state.aim_period_input}),
        placeholder="e.g., 2025MTH01", max_chars=9
        )

st.divider()

# --- Step 3: Generate Script ---
st.subheader("Step 3: Generate SQL Script")

can_process = False
if st.session_state.current_operation == "Property Mapping" and uploaded_file is not None:
    can_process = True
elif st.session_state.current_operation == "DMG Data Cleanup" and \
     st.session_state.dmg_client_db and st.session_state.dmg_start_period and st.session_state.dmg_end_period and st.session_state.dmg_cleanup_scope:
     if re.fullmatch(r"^\d{8}$", st.session_state.dmg_start_period) and re.fullmatch(r"^\d{8}$", st.session_state.dmg_end_period):
        can_process = True
elif st.session_state.current_operation == "AIM Data Cleanup" and st.session_state.aim_db_name and st.session_state.aim_period:
     if re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", st.session_state.aim_period): # case-insensitive MTH
        can_process = True

process_button = st.button(
    "⚙️ Generate Script",
    disabled=not can_process,
    help="Provide all required inputs in the correct format first." if not can_process else f"Click to generate the script for {st.session_state.current_operation}"
)

if process_button and can_process:
    if st.session_state.current_operation == "Property Mapping":
        st.session_state.sql_file_name_input = "" # Reset filename suggestion for PM

    with st.spinner(f"Processing '{st.session_state.current_operation}'... Please wait."):
        if st.session_state.current_operation == "Property Mapping":
            process_property_mapping(uploaded_file)
        elif st.session_state.current_operation == "DMG Data Cleanup":
             process_dmg_cleanup(
                 st.session_state.dmg_client_db,
                 st.session_state.dmg_start_period,
                 st.session_state.dmg_end_period,
                 st.session_state.dmg_cleanup_scope
             )
        elif st.session_state.current_operation == "AIM Data Cleanup":
             process_aim_cleanup(
                 st.session_state.aim_db_name,
                 st.session_state.aim_period
             )
        else: # Should not happen with current options
            st.warning(f"Processing logic for '{st.session_state.current_operation}' is not implemented yet.")
            st.session_state.error_message = "Not implemented"
            if uploaded_file: st.session_state.file_name_processed = uploaded_file.name
            else: st.session_state.file_name_processed = "Input Parameters"

# --- Step 4: Results ---
st.divider()
st.subheader("📊 Results")

# Check if results are available AND pertain to the currently selected operation
results_available_for_current_op = (st.session_state.get('processed_data') is not None or st.session_state.get('error_message') is not None) and \
                                   st.session_state.get('current_operation_at_processing_time') == st.session_state.current_operation

# Store the operation type at the time of processing to compare later
if process_button and can_process:
    st.session_state.current_operation_at_processing_time = st.session_state.current_operation
elif st.session_state.operation_selector != st.session_state.get('current_operation_at_processing_time'):
    # If operation changed since last processing, results are not for current op
    results_available_for_current_op = False


if results_available_for_current_op:
    processed_identifier = st.session_state.get('file_name_processed', 'Input Parameters')

    if st.session_state.get('processed_data'):
        st.success(f"✅ Script generation complete for **{st.session_state.current_operation}** using **{processed_identifier}**!")

        if st.session_state.current_operation == "Property Mapping":
            st.info(f"Action performed: **{st.session_state.pm_action}**")
            cols = st.columns(3)
            cols[0].metric("Rows Read from File", st.session_state.get('rows_read', 0))
            cols[1].metric(f"Rows Processed for {st.session_state.pm_action}", st.session_state.get('rows_filtered', 0))
            cols[2].metric("SQL Blocks Generated", st.session_state.get('queries_generated', 0), help="Number of mapping blocks (SELECT/IF/ACTION/SELECT) generated.")

            if st.session_state.pm_action == "Insert/Update" and st.session_state.pm_include_mismatches and st.session_state.get('pm_mismatched_rows_processed', 0) > 0:
                st.warning(f"**Included {st.session_state.get('pm_mismatched_rows_processed', 0)} rows with Source_Pty_Id mismatches.** Please review these specific SQL blocks carefully.", icon="⚠️")

        elif st.session_state.current_operation in ["DMG Data Cleanup", "AIM Data Cleanup"]:
             scope_info = f" (Scope: {st.session_state.dmg_cleanup_scope})" if st.session_state.current_operation == "DMG Data Cleanup" else ""
             st.metric("SQL Script Generated", "1 Block" if st.session_state.get('queries_generated', 0) > 0 else "0 Blocks", help=f"Indicates if the SQL script block was successfully generated{scope_info}.")

        st.subheader("Generated SQL Preview (First ~1000 chars)")
        preview_text = st.session_state.processed_data[:1000] + ("..." if len(st.session_state.processed_data) > 1000 else "")
        st.code(preview_text, language="sql")

        st.subheader("Download Script")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sanitized_operation = re.sub(r'\W+', '_', st.session_state.current_operation)
        default_filename = f"{sanitized_operation}_Script_{timestamp}.sql"

        if st.session_state.current_operation == "Property Mapping":
            action_tag = "_Delete" if st.session_state.pm_action == "Delete" else "_InsertUpdate"
            default_prop_map_filename = f"Integrations_DF_ARES_Property_Mapping{action_tag}_PME-XXXXXX_{datetime.now().strftime('%Y%m%d')}.sql"
            current_filename_value = st.session_state.get('sql_file_name_input') or default_prop_map_filename
            user_filename = st.text_input(
                "Enter desired SQL file name (.sql will be added if missing):",
                value=current_filename_value,
                key="sql_file_name_input_field", # Changed key to avoid conflict
                help="Suggested format: Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_YYYYMMDD.sql. Replace XXXXXX as needed."
            )
            st.session_state.sql_file_name_input = user_filename # Store user input
            download_filename = user_filename if user_filename else default_prop_map_filename
            if not download_filename.lower().endswith('.sql'):
                download_filename += '.sql'
        elif st.session_state.current_operation == "DMG Data Cleanup":
            scope_tag = "_ActualsOnly" if st.session_state.dmg_cleanup_scope == "Actuals Only" else "_AllBookTypes"
            download_filename = f"{sanitized_operation}{scope_tag}_Script_{timestamp}.sql"
            st.info(f"Download filename will be: `{download_filename}`")
        else: # AIM or other future non-custom filename ops
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
        if st.session_state.current_operation == "Property Mapping" and "No matching rows" in error_msg:
            st.warning(f"⚠️ No data rows matched the filter criteria for **{st.session_state.current_operation} ({st.session_state.pm_action})** in file **{processed_identifier}**. No SQL script was generated.")
            cols = st.columns(3)
            cols[0].metric("Rows Read from File", st.session_state.get('rows_read', 0))
            cols[1].metric(f"Rows Processed for {st.session_state.pm_action}", 0)
            cols[2].metric("SQL Blocks Generated", 0)
            if st.session_state.pm_action == "Insert/Update" and st.session_state.pm_include_mismatches and st.session_state.get('pm_mismatched_rows_processed', 0) > 0:
                st.info(f"Note: Mismatch inclusion was enabled and {st.session_state.get('pm_mismatched_rows_processed',0)} rows were initially considered for mismatch, but none passed final criteria.")

        elif st.session_state.current_operation in ["DMG Data Cleanup", "AIM Data Cleanup"] and "Input validation failed" in error_msg:
             st.error(f"❌ Script generation failed for **{st.session_state.current_operation}** due to invalid inputs.")
             st.error(f"Error details: {error_msg}")
             st.info("Please correct the inputs in Step 2 and try generating the script again.")
        elif error_msg != "Not implemented": # General error
             st.error(f"❌ Processing failed for **{st.session_state.current_operation}** using **{processed_identifier}**.")
             st.error(f"Error: {error_msg}")
             if st.session_state.current_operation == "Property Mapping" and st.session_state.get('rows_read', 0) > 0:
                 cols = st.columns(3)
                 cols[0].metric("Rows Read", st.session_state.get('rows_read', 0))
                 cols[1].metric(f"Rows Processed for {st.session_state.pm_action}", "N/A due to error")
                 cols[2].metric("SQL Blocks Generated", "N/A due to error")
    else:
       st.info("Processing attempted, but no data or error message was recorded. Please try again.")

elif not results_available_for_current_op:
    # This handles the case where the page loads, or operation changed AFTER last processing
    if st.session_state.get('current_operation_at_processing_time') and \
       st.session_state.current_operation_at_processing_time != st.session_state.current_operation and \
       (st.session_state.get('processed_data') or st.session_state.get('error_message')):
        st.info(f"Results displayed previously were for '{st.session_state.current_operation_at_processing_time}'.")
        st.info(f"Provide inputs for '{st.session_state.current_operation}' and click 'Generate Script' above to see results for the current selection.")
    else:
        st.info("Select an operation, provide inputs, and click 'Generate Script' in Step 3 to see results here.")


# --- Footer ---
st.divider()
st.caption(f"SQL Generator Tool | Current Operation: {st.session_state.current_operation} | Version 1.9")
