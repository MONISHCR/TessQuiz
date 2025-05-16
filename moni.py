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


# --- Property Mapping Processing Function (MODIFIED for confirmation dialog) ---
def process_property_mapping(uploaded_file):
    """Handles the entire process for the Property Mapping option, including confirmation for differing IDs."""
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
    
    # This placeholder is for messages during the main processing steps
    status_placeholder = st.empty()
    # This placeholder is specifically for the confirmation dialog UI
    confirmation_ui_placeholder = st.container()


    try:
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
        status_placeholder.info(f"Read {st.session_state.rows_read} data rows. Pre-processing data...")

        reverse_header_map = {v: k for k, v in col_indices.items()}
        df_processed = df.rename(columns=reverse_header_map)

        # Basic type conversions and stripping
        for col in [COL_SOURCE_ID_HDR, COL_AIM_CODE_HDR, COL_EXT_ID_HDR, COL_AIM_NAME_HDR, COL_PROVIDER_HDR]:
            if col in df_processed.columns:
                df_processed[col] = df_processed[col].astype(str).str.strip()
        if COL_TARGET_ID_HDR in df_processed.columns:
            df_processed[COL_TARGET_ID_HDR] = pd.to_numeric(df_processed[COL_TARGET_ID_HDR], errors='coerce')

        # --- Logic for identifying strictly matching vs. potentially discrepant rows ---
        base_valid_mask = (
            (df_processed[COL_SOURCE_ID_HDR] != '') &
            df_processed[COL_TARGET_ID_HDR].notna() &
            (df_processed[COL_PROVIDER_HDR] != '') # Assuming provider should not be blank
        )
        
        strict_match_conditions_mask = (
            (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_AIM_CODE_HDR]) &
            (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_EXT_ID_HDR])
        )

        df_strict_matches = df_processed[base_valid_mask & strict_match_conditions_mask].copy()
        df_potential_discrepancies = df_processed[base_valid_mask & ~strict_match_conditions_mask].copy()
        
        # --- Confirmation Dialog Logic ---
        if not df_potential_discrepancies.empty and 'pm_confirmation_decision' not in st.session_state:
            status_placeholder.empty() # Clear the general status message
            with confirmation_ui_placeholder:
                st.warning(f"Found {len(df_potential_discrepancies)} row(s) where `Source_Pty_Id` may not be identical to both `AIM Code` and `Ext_Id`.")
                st.markdown("Please review these rows:")
                display_cols = [COL_PROVIDER_HDR, COL_SOURCE_ID_HDR, COL_AIM_CODE_HDR, COL_AIM_NAME_HDR, COL_TARGET_ID_HDR, COL_EXT_ID_HDR]
                st.dataframe(df_potential_discrepancies[display_cols])
                st.markdown("**Do you want to include these specific rows in the SQL script generation?**")
                st.caption("Rows where `Source_Pty_Id`, `AIM Code`, and `Ext_Id` are identical (and meet other criteria) will be processed regardless of this choice.")

                col_yes, col_no, _ = st.columns([1,1,3]) # Adjust column ratios as needed
                if col_yes.button("✅ Yes, include these rows", key="pm_confirm_yes", help="Include these reviewed rows in the script."):
                    st.session_state.pm_confirmation_decision = "yes"
                    st.session_state.pm_temp_processing_state = {
                        "columns": list(df_processed.columns),
                        "strict_matches_records": df_strict_matches.to_dict('records'),
                        "potential_discrepancies_records": df_potential_discrepancies.to_dict('records')
                    }
                    confirmation_ui_placeholder.empty()
                    st.rerun()

                if col_no.button("❌ No, exclude these rows", key="pm_confirm_no", help="Exclude these reviewed rows from the script."):
                    st.session_state.pm_confirmation_decision = "no"
                    st.session_state.pm_temp_processing_state = {
                        "columns": list(df_processed.columns),
                        "strict_matches_records": df_strict_matches.to_dict('records'),
                        # Discrepancies not needed if 'no', but store for consistency if logic changes
                        "potential_discrepancies_records": df_potential_discrepancies.to_dict('records') 
                    }
                    confirmation_ui_placeholder.empty()
                    st.rerun()
            
            # Stop further processing in this run; wait for user's decision via rerun
            st.session_state.processed_data = None 
            st.session_state.error_message = "User confirmation pending for rows with differing IDs."
            st.session_state.queries_generated = 0
            return

        # --- Post-Confirmation or No-Discrepancy Path ---
        confirmation_ui_placeholder.empty() # Ensure confirmation UI is cleared if we passed it or it wasn't needed
        filtered_df_list = []

        if 'pm_confirmation_decision' in st.session_state:
            status_placeholder.info("Processing based on user confirmation...")
            processing_state = st.session_state.get('pm_temp_processing_state')
            if not processing_state:
                st.error("Critical error: Processing state not found after confirmation. Please try generating the script again.")
                st.session_state.error_message = "Internal error: Missing processing state."
                # Clean up to prevent inconsistent state on next run
                if 'pm_confirmation_decision' in st.session_state: del st.session_state.pm_confirmation_decision
                return

            cols_for_reconstruction = processing_state["columns"]
            reconstructed_strict_matches = pd.DataFrame(processing_state["strict_matches_records"], columns=cols_for_reconstruction)
            reconstructed_potential_discrepancies = pd.DataFrame(processing_state["potential_discrepancies_records"], columns=cols_for_reconstruction)

            if not reconstructed_strict_matches.empty:
                filtered_df_list.append(reconstructed_strict_matches)

            if st.session_state.pm_confirmation_decision == "yes":
                status_placeholder.info("User confirmed 'Yes' for differing rows. Including them.")
                if not reconstructed_potential_discrepancies.empty:
                    filtered_df_list.append(reconstructed_potential_discrepancies)
            else: # Decision was "no"
                status_placeholder.info("User confirmed 'No' for differing rows. Excluding them.")
            
            # Clean up session state for this confirmation cycle
            del st.session_state.pm_confirmation_decision
            if 'pm_temp_processing_state' in st.session_state: del st.session_state.pm_temp_processing_state
        
        else: # No discrepancies found initially, or confirmation path was not taken
            status_placeholder.info("Processing strictly matching rows (no differing IDs found or confirmation not applicable).")
            if not df_strict_matches.empty:
                filtered_df_list.append(df_strict_matches)

        if filtered_df_list:
            filtered_df = pd.concat(filtered_df_list).drop_duplicates().reset_index(drop=True)
        else:
            filtered_df = pd.DataFrame(columns=REQUIRED_HEADERS) # Empty DF with correct columns

        # Final validation and type conversion for Target_Pty_Id on the consolidated DataFrame
        if not filtered_df.empty and COL_TARGET_ID_HDR in filtered_df.columns:
            filtered_df[COL_TARGET_ID_HDR] = pd.to_numeric(filtered_df[COL_TARGET_ID_HDR], errors='coerce')
            initial_count_before_dropna = len(filtered_df)
            filtered_df.dropna(subset=[COL_TARGET_ID_HDR], inplace=True)
            if len(filtered_df) < initial_count_before_dropna:
                st.warning(f"{initial_count_before_dropna - len(filtered_df)} row(s) were removed due to invalid/empty Target_Pty_Id after consolidation.")
            
            if not filtered_df.empty:
                 filtered_df.loc[:, COL_TARGET_ID_HDR] = filtered_df[COL_TARGET_ID_HDR].astype(int)
        
        st.session_state.rows_filtered = len(filtered_df)
        status_placeholder.info(f"Finalized {st.session_state.rows_filtered} rows for SQL generation. Generating SQL...")

        if not filtered_df.empty:
            sql_blocks = []
            # Use original AIM Property Name from the filtered_df
            unique_property_names = filtered_df[COL_AIM_NAME_HDR].dropna().unique().tolist()
            valid_property_names = [name for name in unique_property_names if isinstance(name, str) and name.strip()]
            
            sql_blocks.append(generate_sql_property_name_check(valid_property_names))
            sql_blocks.append(generate_sql_mapping_checks(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR))
            sql_blocks.append(generate_sql_mapping_inserts(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR, COL_AIM_NAME_HDR))
            sql_blocks.append(generate_sql_mapping_checks(filtered_df, COL_SOURCE_ID_HDR, COL_TARGET_ID_HDR))

            final_sql_script = "\n\n".join(sql_blocks)
            st.session_state.processed_data = final_sql_script
            st.session_state.queries_generated = len(filtered_df) # Number of insert blocks
            status_placeholder.success("SQL script generated successfully!")
        else:
            status_placeholder.warning("No data rows remained after filtering and/or confirmation. No SQL script generated.")
            if not st.session_state.error_message: # Don't overwrite a more specific error
                 st.session_state.error_message = "No matching/confirmed rows found for Property Mapping."
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
        confirmation_ui_placeholder.empty() # Clear confirmation UI on error too


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
from CashFlow C --WITH removed as it was likely a typo and invalid SQL here
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

select *from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}' and bud_value IS NULL;

delete from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}' and bud_value IS NULL;

update line_item set act_value = null where item_typ_id in (select acct_id from account) and period = '{safe_period}' AND act_value IS NOT NULL and bud_value IS NOT NULL

select *from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}';

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
    # Property Mapping Confirmation State
    # 'pm_confirmation_decision': None, # e.g., 'yes', 'no' -> Handled by deletion/existence
    # 'pm_temp_processing_state': None, # Stores dict with DFs for confirmation -> Handled by deletion/existence
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

# Keys for Property Mapping confirmation state that need reset
PM_CONFIRMATION_STATE_KEYS = ['pm_confirmation_decision', 'pm_temp_processing_state']

def reset_state_on_operation_change():
    # Reset general state
    for key in defaults: # This resets to initial defaults
        st.session_state[key] = defaults[key]
    st.session_state.uploaded_file_key += 1 # Force re-render of file uploader

    # Specifically clear any lingering PM confirmation state if operation changes
    for key_to_clear in PM_CONFIRMATION_STATE_KEYS:
        if key_to_clear in st.session_state:
            del st.session_state[key_to_clear]
    pass # No return needed for on_change


previous_operation = st.session_state.current_operation # Not actively used but good for debugging
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
st.session_state.current_operation = selected_operation # Update current operation tracking

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
            6.  **Filtering Logic (Initial Strict):** Rows are considered for strict matching if **all** conditions met:
                *   `Source_Pty_Id` == `AIM Code`
                *   `Source_Pty_Id` == `Ext_Id`
                *   `Source_Pty_Id` is **not blank**.
                *   `Pty_iTarget_Pty_Idd` is a **valid number**.
                *   `Provider` is **not blank**.
            7.  **Confirmation for Differences:** If rows are found that are valid (non-blank Provider, Source_Pty_Id, valid Pty_iTarget_Pty_Idd) but where `Source_Pty_Id` is *not* identical to both `AIM Code` and `Ext_Id`, you will be shown these rows and asked to confirm (Yes/No) if they should be included in the script.
            8.  **Generate:** Click 'Generate Script' in Step 3.
            9.  **Download:** `.sql` script generated. Customize filename in Results.
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
        *   *Version:* 1.9 (Property Mapping Confirmation Dialog)
    """)

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
        key=f"uploader_prop_map_{st.session_state.uploaded_file_key}", # Key change forces reset
        help="Ensure the file follows the structure described in the instructions. Use the template."
    )
    if uploaded_file and uploaded_file.name != st.session_state.get('file_name_processed'):
         # New file uploaded or re-uploaded, reset relevant state
         st.session_state.update({
             'processed_data': None, 'error_message': None, 'queries_generated': 0,
             'rows_read': 0, 'rows_filtered': 0,
             'file_name_processed': None, # Will be set by process_property_mapping
             'sql_file_name_input': ""
         })
         # Crucially, reset PM confirmation state for the new file
         for key_to_clear in PM_CONFIRMATION_STATE_KEYS:
            if key_to_clear in st.session_state:
                del st.session_state[key_to_clear]

elif selected_operation == "DMG Data Cleanup":
    dmg_client_db = st.text_input(
        "Client Database Name:",
        key="dmg_client_db_input", # Ensure keys are unique if elements are conditionally rendered
        value=st.session_state.dmg_client_db,
        placeholder="e.g., AegonDQSI",
        help="Enter the exact name of the database."
    )
    st.session_state.dmg_client_db = dmg_client_db # Persist input

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
    try: # Robust index finding
        scope_index = dmg_cleanup_scope_options.index(st.session_state.dmg_cleanup_scope)
    except ValueError:
        scope_index = 1 # Default to "All Book Types" if state is somehow invalid

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
     if re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", aim_period.upper()): # Made AIM period check case-insensitive for MTH
        can_process = True

process_button = st.button(
    "⚙️ Generate Script",
    disabled=not can_process,
    help="Provide all required inputs in the correct format first." if not can_process else f"Click to generate the script for {selected_operation}"
)

if process_button and can_process:
    # Ensure current operation is correctly tracked for result display
    st.session_state.current_operation = selected_operation
    
    if selected_operation == "Property Mapping":
        st.session_state.sql_file_name_input = "" # Reset custom filename input
        # Crucially, reset PM confirmation state if "Generate Script" is clicked anew
        for key_to_clear in PM_CONFIRMATION_STATE_KEYS:
            if key_to_clear in st.session_state:
                del st.session_state[key_to_clear]

    # Spinner context should ideally wrap the call to the processing function
    with st.spinner(f"Processing '{selected_operation}'... Please wait."):
        if selected_operation == "Property Mapping":
            process_property_mapping(uploaded_file)
        elif selected_operation == "DMG Data Cleanup":
             process_dmg_cleanup(
                 st.session_state.dmg_client_db,
                 st.session_state.dmg_start_period,
                 st.session_state.dmg_end_period,
                 st.session_state.dmg_cleanup_scope
             )
        elif selected_operation == "AIM Data Cleanup":
             process_aim_cleanup(
                 st.session_state.aim_db_name,
                 st.session_state.aim_period # Pass the session state value
             )
        else: # Should not happen with current options
            st.warning(f"Processing logic for '{selected_operation}' is not implemented yet.")
            st.session_state.error_message = "Not implemented"
            st.session_state.processed_data = None
            st.session_state.queries_generated = 0
            # Set file_name_processed for non-file operations for consistency in results display
            if uploaded_file: st.session_state.file_name_processed = uploaded_file.name
            else: st.session_state.file_name_processed = "Input Parameters"


# --- Step 4: Results ---
st.divider()
st.subheader("📊 Results")

# Check if results are available AND belong to the currently selected operation type
# This prevents showing old results if the user changes operation type after generating a script.
results_available_for_current_op = (
    (st.session_state.get('processed_data') is not None or st.session_state.get('error_message') is not None) and
    st.session_state.get('current_operation_for_results') == selected_operation # Use a dedicated key
)
# If process_button was clicked, update the operation for which results are stored
if process_button and can_process:
    st.session_state.current_operation_for_results = selected_operation


if (st.session_state.get('processed_data') or st.session_state.get('error_message')) and \
   st.session_state.get('current_operation_for_results') == selected_operation:

    processed_identifier = st.session_state.get('file_name_processed', 'Input Parameters')

    if st.session_state.get('processed_data'):
        st.success(f"✅ Script generation complete for **{selected_operation}** using **{processed_identifier}**!")

        if selected_operation == "Property Mapping":
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Finalized for SQL", st.session_state.get('rows_filtered', 0)) # Renamed for clarity
            col3.metric("Mapping Inserts Generated", st.session_state.get('queries_generated', 0), help="Number of potential INSERT blocks generated based on finalized rows.")
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"]:
             scope_info = f" (Scope: {st.session_state.dmg_cleanup_scope})" if selected_operation == "DMG Data Cleanup" else ""
             st.metric("SQL Script Generated", "1 Block" if st.session_state.get('queries_generated', 0) > 0 else "0 Blocks", help=f"Indicates if the SQL script block was successfully generated{scope_info}.")

        st.subheader("Generated SQL Preview (First ~1000 chars)")
        preview_text = st.session_state.processed_data[:1000] + ("..." if len(st.session_state.processed_data) > 1000 else "")
        st.code(preview_text, language="sql")

        st.subheader("Download Script")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sanitized_operation = re.sub(r'\W+', '_', selected_operation) # Sanitize for filename
        default_filename_base = f"{sanitized_operation}_Script_{timestamp}"
        
        if selected_operation == "DMG Data Cleanup":
            scope_tag = "_ActualsOnly" if st.session_state.dmg_cleanup_scope == "Actuals Only" else "_AllBookTypes"
            default_filename_base = f"{sanitized_operation}{scope_tag}_Script_{timestamp}"

        if selected_operation == "Property Mapping":
            default_prop_map_filename = f"Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_{datetime.now().strftime('%Y%m%d')}.sql"
            # Use session state for text input to preserve edits
            current_filename_value = st.session_state.get('sql_file_name_input_val', default_prop_map_filename)
            user_filename = st.text_input(
                "Enter desired SQL file name (.sql will be added if missing):",
                value=current_filename_value,
                key="sql_file_name_input_val_widget", # Unique key for the widget
                on_change=lambda: st.session_state.update(sql_file_name_input_val=st.session_state.sql_file_name_input_val_widget), # Persist changes
                help="Suggested format: Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_YYYYMMDD.sql. Replace XXXXXX as needed."
            )
            st.session_state.sql_file_name_input = user_filename # Store for download button

            download_filename = user_filename if user_filename else default_prop_map_filename
            if not download_filename.lower().endswith('.sql'):
                download_filename += '.sql'
        else:
            download_filename = f"{default_filename_base}.sql"
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
        if selected_operation == "Property Mapping" and "User confirmation pending" in error_msg:
            st.info(f"ℹ️ Action Required for **{selected_operation}**: Please respond to the confirmation prompt above regarding rows with differing IDs.")
            # Metrics might not be fully relevant here, or show partial progress
            col1, col2 = st.columns(2)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Awaiting Confirmation", "See prompt")
        elif selected_operation == "Property Mapping" and ("No matching/confirmed rows" in error_msg or "No data rows remained" in error_msg):
            st.warning(f"⚠️ No data rows matched the filter criteria or were confirmed for **{selected_operation}** in file **{processed_identifier}**. No SQL script was generated.")
            col1, col2, col3 = st.columns(3)
            col1.metric("Rows Read from File", st.session_state.get('rows_read', 0))
            col2.metric("Rows Finalized for SQL", 0)
            col3.metric("Mapping Inserts Generated", 0)
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"] and "Input validation failed" in error_msg:
             st.error(f"❌ Script generation failed for **{selected_operation}** due to invalid inputs.")
             st.error(f"Error details: {error_msg}")
             st.info("Please correct the inputs in Step 2 and try generating the script again.")
        elif error_msg != "Not implemented": # General errors
             st.error(f"❌ Processing failed for **{selected_operation}** using **{processed_identifier}**.")
             st.error(f"Error: {error_msg}")
             if selected_operation == "Property Mapping" and st.session_state.get('rows_read', 0) > 0 :
                 # Show read rows even on error if applicable
                 col1, col2, col3 = st.columns(3)
                 col1.metric("Rows Read", st.session_state.get('rows_read', 0))
                 col2.metric("Rows Finalized", "N/A (error)")
                 col3.metric("Mapping Inserts", "N/A (error)")
    # else: No data and no error, but results_available_for_current_op was true (e.g. cleared error)
    # This case should be rare given the logic.

# If no results are shown because they belong to a *different* operation than selected
elif (st.session_state.get('processed_data') or st.session_state.get('error_message')) and \
     st.session_state.get('current_operation_for_results') != selected_operation:
    st.info(f"Results previously displayed were for '{st.session_state.get('current_operation_for_results')}'.")
    st.info(f"To see results for '{selected_operation}', please provide inputs and click 'Generate Script'.")
else: # No results processed yet at all, or state was cleared
    st.info("Select an operation, provide inputs, and click 'Generate Script' in Step 3 to see results here.")


# --- Footer ---
st.divider()
st.caption(f"SQL Generator Tool | Current Operation: {selected_operation} | Version 1.9")
