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


# --- Property Mapping Processing Function (Internal logic unchanged from 1.9.1, called differently now) ---
def process_property_mapping(uploaded_file):
    """Handles the entire process for the Property Mapping option, including confirmation for differing IDs."""
    # Ensure file_name_processed is set for result display
    st.session_state.file_name_processed = uploaded_file.name

    # Initialize/clear results for this specific processing attempt
    st.session_state.processed_data = None
    st.session_state.error_message = None
    # rows_read, queries_generated, rows_filtered will be set during processing

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
    
    status_placeholder = st.empty()
    confirmation_ui_placeholder = st.container() # Dedicated container for confirmation dialog

    try:
        # --- Initial Data Reading and Validation (only if not already in a confirmation flow) ---
        # If pm_temp_processing_state exists, we assume data was already read and prepped.
        if 'pm_confirmation_decision' not in st.session_state or \
           not st.session_state.get('pm_temp_processing_state'):

            status_placeholder.info(f"Processing file: *{uploaded_file.name}*")
            file_content = io.BytesIO(uploaded_file.getvalue())
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
                st.session_state.error_message = f"Missing headers: {', '.join([h.split('**')[1] for h in missing_cols])}"
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
            status_placeholder.info(f"Read {st.session_state.rows_read} data rows. Pre-processing data...")

            reverse_header_map = {v: k for k, v in col_indices.items()}
            df_processed = df.rename(columns=reverse_header_map)

            for col in [COL_SOURCE_ID_HDR, COL_AIM_CODE_HDR, COL_EXT_ID_HDR, COL_AIM_NAME_HDR, COL_PROVIDER_HDR]:
                if col in df_processed.columns:
                    df_processed[col] = df_processed[col].astype(str).str.strip()
            if COL_TARGET_ID_HDR in df_processed.columns:
                df_processed[COL_TARGET_ID_HDR] = pd.to_numeric(df_processed[COL_TARGET_ID_HDR], errors='coerce')

            base_valid_mask = (
                (df_processed[COL_SOURCE_ID_HDR] != '') &
                df_processed[COL_TARGET_ID_HDR].notna()
            )
            strict_match_conditions_mask = (
                (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_AIM_CODE_HDR]) &
                (df_processed[COL_SOURCE_ID_HDR] == df_processed[COL_EXT_ID_HDR])
            )
            df_strict_matches = df_processed[base_valid_mask & strict_match_conditions_mask].copy()
            df_potential_discrepancies = df_processed[base_valid_mask & ~strict_match_conditions_mask].copy()
        
        # --- Confirmation Dialog Logic ---
        # This part is entered if discrepancies exist AND no decision has been made yet.
        if 'df_potential_discrepancies' in locals() and not df_potential_discrepancies.empty and \
           'pm_confirmation_decision' not in st.session_state:
            status_placeholder.empty() 
            with confirmation_ui_placeholder:
                st.warning(f"Found {len(df_potential_discrepancies)} row(s) where `Source_Pty_Id` may not be identical to both `AIM Code` and `Ext_Id` (but `Source_Pty_Id` is present and `Pty_iTarget_Pty_Idd` is a number).")
                st.markdown("Please review these rows:")
                display_cols = [COL_PROVIDER_HDR, COL_SOURCE_ID_HDR, COL_AIM_CODE_HDR, COL_AIM_NAME_HDR, COL_TARGET_ID_HDR, COL_EXT_ID_HDR]
                st.dataframe(df_potential_discrepancies[display_cols].reset_index(drop=True))
                st.markdown("**Do you want to include these specific rows in the SQL script generation?**")
                st.caption("Rows where IDs match strictly will be processed regardless.")

                col_yes, col_no, _ = st.columns([1,1,3]) 
                if col_yes.button("✅ Yes, include these rows", key="pm_confirm_yes"):
                    st.session_state.pm_confirmation_decision = "yes"
                    st.session_state.pm_temp_processing_state = {
                        "columns": list(df_processed.columns),
                        "strict_matches_records": df_strict_matches.to_dict('records'),
                        "potential_discrepancies_records": df_potential_discrepancies.to_dict('records')
                    }
                    confirmation_ui_placeholder.empty()
                    st.rerun() # This rerun will trigger the main script's `elif` block

                if col_no.button("❌ No, exclude these rows", key="pm_confirm_no"):
                    st.session_state.pm_confirmation_decision = "no"
                    st.session_state.pm_temp_processing_state = {
                        "columns": list(df_processed.columns),
                        "strict_matches_records": df_strict_matches.to_dict('records'),
                        "potential_discrepancies_records": df_potential_discrepancies.to_dict('records') 
                    }
                    confirmation_ui_placeholder.empty()
                    st.rerun() # This rerun will trigger the main script's `elif` block
            
            # If we showed the confirmation dialog, set a message and return.
            # The actual processing will happen after rerun.
            st.session_state.processed_data = None 
            st.session_state.error_message = "User confirmation pending for rows with differing IDs."
            st.session_state.queries_generated = 0
            return # IMPORTANT: Stop processing here for this run

        # --- Post-Confirmation or No-Discrepancy Path ---
        # This part is entered if:
        # 1. No discrepancies were found in the first place.
        # 2. A confirmation decision ('yes' or 'no') has been made (i.e., we are in a rerun after button click).
        confirmation_ui_placeholder.empty() 
        filtered_df_list = []

        if 'pm_confirmation_decision' in st.session_state:
            status_placeholder.info("Processing based on user confirmation...")
            processing_state = st.session_state.get('pm_temp_processing_state')
            if not processing_state: # Should not happen if decision is set
                st.error("Critical error: Processing state not found after confirmation.")
                st.session_state.error_message = "Internal error: Missing processing state."
                # Clean up to prevent loop
                if 'pm_confirmation_decision' in st.session_state: del st.session_state.pm_confirmation_decision
                return

            cols_for_reconstruction = processing_state["columns"]
            reconstructed_strict_matches = pd.DataFrame.from_records(processing_state["strict_matches_records"], columns=cols_for_reconstruction)
            reconstructed_potential_discrepancies = pd.DataFrame.from_records(processing_state["potential_discrepancies_records"], columns=cols_for_reconstruction)

            if not reconstructed_strict_matches.empty:
                filtered_df_list.append(reconstructed_strict_matches)

            if st.session_state.pm_confirmation_decision == "yes":
                status_placeholder.info("User confirmed 'Yes' for differing rows. Including them.")
                if not reconstructed_potential_discrepancies.empty:
                    filtered_df_list.append(reconstructed_potential_discrepancies)
            else: 
                status_placeholder.info("User confirmed 'No' for differing rows. Excluding them.")
            
            # Crucially, clean up confirmation state *after* using it
            del st.session_state.pm_confirmation_decision
            if 'pm_temp_processing_state' in st.session_state: del st.session_state.pm_temp_processing_state
        
        else: # No discrepancies were found initially (and no confirmation decision was made)
            status_placeholder.info("Processing strictly matching rows (no differing IDs found or confirmation not applicable).")
            # df_strict_matches would have been defined from the initial processing block
            if 'df_strict_matches' in locals() and not df_strict_matches.empty:
                filtered_df_list.append(df_strict_matches)
            elif not filtered_df_list: # If df_strict_matches was not formed for some reason
                # This case implies an issue if we reach here without a decision and without strict matches.
                # However, the logic should populate df_strict_matches if initial processing occurred.
                pass


        if filtered_df_list:
            filtered_df = pd.concat(filtered_df_list).drop_duplicates().reset_index(drop=True)
        else:
            df_cols_ref = locals().get('df_processed', pd.DataFrame(columns=REQUIRED_HEADERS))
            filtered_df = pd.DataFrame(columns=df_cols_ref.columns)

        if not filtered_df.empty and COL_TARGET_ID_HDR in filtered_df.columns:
            filtered_df[COL_TARGET_ID_HDR] = pd.to_numeric(filtered_df[COL_TARGET_ID_HDR], errors='coerce')
            initial_count_before_dropna = len(filtered_df)
            filtered_df.dropna(subset=[COL_TARGET_ID_HDR], inplace=True)
            
            if len(filtered_df) < initial_count_before_dropna:
                st.warning(f"{initial_count_before_dropna - len(filtered_df)} row(s) removed due to invalid/empty Target_Pty_Id after consolidation.")
            
            if not filtered_df.empty:
                 filtered_df.loc[:, COL_TARGET_ID_HDR] = filtered_df[COL_TARGET_ID_HDR].astype(int)
        
        st.session_state.rows_filtered = len(filtered_df)
        # Set rows_read if it wasn't set (e.g., if we skipped initial processing due to existing temp_state)
        if 'rows_read' not in st.session_state or st.session_state.rows_read == 0:
            if 'df_processed' in locals():
                 st.session_state.rows_read = len(df_processed)
            elif processing_state: # Estimate from stored records if possible
                st.session_state.rows_read = len(processing_state["strict_matches_records"]) + len(processing_state["potential_discrepancies_records"])


        status_placeholder.info(f"Finalized {st.session_state.rows_filtered} rows for SQL generation. Generating SQL...")

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
            status_placeholder.warning("No data rows remained after filtering and/or confirmation. No SQL script generated.")
            if not st.session_state.error_message: 
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
        confirmation_ui_placeholder.empty()
        # Clean up confirmation state on error to prevent loops
        if 'pm_confirmation_decision' in st.session_state: del st.session_state.pm_confirmation_decision
        if 'pm_temp_processing_state' in st.session_state: del st.session_state.pm_temp_processing_state


# --- DMG Data Cleanup Specific Functions --- (Unchanged)
def generate_dmg_cleanup_sql(client_db, start_period, end_period, cleanup_scope):
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
    safe_client_db = f"[{client_db.replace(']', ']]')}]"
    if cleanup_scope == "Actuals Only":
        sql_template = f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: DMG Data Cleanup (Actuals Only)
-- Target Database: {safe_client_db}
-- Filter: EntityType = 'Asset' AND Period BETWEEN {start_period} AND {end_period} AND BookType = 'Actual'
-- ======================================================================
USE {safe_client_db}; GO
select c.* from CashFlow C inner join Entity E ON C.EntityKey = E.EntityKey INNER JOIN Lookup.Value AS BT ON C.BookTypeKey=BT.ValueKey AND BT.ValueID='Actual' WHERE  E.EntityType = 'Asset' and C.Period between {start_period} and {end_period}; GO
delete C from CashFlow C inner join Entity E ON C.EntityKey = E.EntityKey INNER JOIN Lookup.Value AS BT ON C.BookTypeKey=BT.ValueKey AND BT.ValueID='Actual' WHERE  E.EntityType = 'Asset' and C.Period between {start_period} and {end_period}; GO
select c.* from CashFlow C inner join Entity E ON C.EntityKey = E.EntityKey INNER JOIN Lookup.Value AS BT ON C.BookTypeKey=BT.ValueKey AND BT.ValueID='Actual' WHERE  E.EntityType = 'Asset' and C.Period between {start_period} and {end_period}; GO"""
    elif cleanup_scope == "All Book Types":
        sql_template = f"""
-- SQL Script Generated by Streamlit Tool on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: DMG Data Cleanup (All Book Types)
-- Target Database: {safe_client_db}
-- Filter: EntityType = 'Asset' AND Period BETWEEN {start_period} AND {end_period}
-- ======================================================================
USE {safe_client_db}; GO
select * from CashFlow C inner join Entity E ON C.EntityKey = E.EntityKey WHERE E.EntityType = 'Asset' and Period between {start_period} and {end_period}; GO
delete C from CashFlow C inner join Entity E ON C.EntityKey = E.EntityKey WHERE E.EntityType = 'Asset' and C.Period between {start_period} and {end_period}; GO
select * from CashFlow C inner join Entity E ON C.EntityKey = E.EntityKey WHERE E.EntityType = 'Asset' and Period between {start_period} and {end_period}; GO"""
    else:
        raise ValueError(f"Unsupported cleanup scope: {cleanup_scope}")
    return sql_template

def process_dmg_cleanup(client_db, start_period, end_period, cleanup_scope):
    st.session_state.processed_data = None; st.session_state.error_message = None
    st.session_state.queries_generated = 0; st.session_state.file_name_processed = None
    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for DMG Cleanup...")
        final_sql_script = generate_dmg_cleanup_sql(client_db, start_period, end_period, cleanup_scope)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1
        status_placeholder.success("DMG Cleanup SQL script generated successfully!")
    except ValueError as ve:
        st.error(f"Input validation failed: {ve}"); st.session_state.error_message = f"Input validation failed: {ve}"
        if status_placeholder: status_placeholder.warning("Script generation failed.")
    except Exception as e:
        st.error(f"An error occurred: {e}"); st.error(f"Traceback: {traceback.format_exc()}")
        st.session_state.error_message = f"Unexpected error: {e}"
        if status_placeholder: status_placeholder.error("Processing failed.")

# --- AIM Data Cleanup Specific Functions --- (Unchanged)
def generate_aim_cleanup_sql(aim_db, period):
    if not aim_db or not period: raise ValueError("AIM Database Name and Period cannot be empty.")
    if not re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", period): raise ValueError("Period must be YYYYMTHMM.")
    safe_aim_db = f"[{aim_db.replace(']', ']]')}]"; safe_period = escape_sql_string(period)
    return f"""
-- SQL Script Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Operation Type: AIM Data Cleanup, Target DB: {safe_aim_db}, Period: '{safe_period}'
-- ======================================================================
USE {safe_aim_db}; GO
select * from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}' and bud_value IS NULL;
delete from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}' and bud_value IS NULL;
update line_item set act_value = null where item_typ_id in (select acct_id from account) and period = '{safe_period}' AND act_value IS NOT NULL and bud_value IS NOT NULL;
select * from line_item where item_typ_id in (select acct_id from account) and period = '{safe_period}'; GO"""

def process_aim_cleanup(aim_db, period):
    st.session_state.processed_data = None; st.session_state.error_message = None
    st.session_state.queries_generated = 0; st.session_state.file_name_processed = None
    status_placeholder = st.empty()
    try:
        status_placeholder.info(f"Validating inputs for AIM Cleanup...")
        final_sql_script = generate_aim_cleanup_sql(aim_db, period)
        st.session_state.processed_data = final_sql_script
        st.session_state.queries_generated = 1
        status_placeholder.success("AIM Cleanup SQL script generated successfully!")
    except ValueError as ve:
        st.error(f"Input validation failed: {ve}"); st.session_state.error_message = f"Input validation failed: {ve}"
        if status_placeholder: status_placeholder.warning("Script generation failed.")
    except Exception as e:
        st.error(f"An error occurred: {e}"); st.error(f"Traceback: {traceback.format_exc()}")
        st.session_state.error_message = f"Unexpected error: {e}"
        if status_placeholder: status_placeholder.error("Processing failed.")

# --- Streamlit App UI ---
st.set_page_config(page_title="SQL Generator Tool", layout="wide")

defaults = {
    'processed_data': None, 'error_message': None, 'queries_generated': 0,
    'rows_read': 0, 'rows_filtered': 0, 'file_name_processed': None,
    'current_operation': "Property Mapping",
    'dmg_client_db': "", 'dmg_start_period': "", 'dmg_end_period': "",
    'dmg_cleanup_scope': "All Book Types",
    'aim_db_name': "", 'aim_period': "",
    'uploaded_file_key': 0, 'sql_file_name_input': "",
    'current_operation_for_results': None, 'sql_file_name_input_val': "",
    'file_name_processed_for_confirmation_state': None # Tracks file for PM confirmation context
}
PM_CONFIRMATION_STATE_KEYS = ['pm_confirmation_decision', 'pm_temp_processing_state']

for key, value in defaults.items():
    if key not in st.session_state: st.session_state[key] = value

st.title("🏢 SQL Script Generator")
st.markdown("Automate SQL script creation from Excel files or inputs for specific operations.")
st.divider()

st.subheader("Step 1: Select Operation Type")
operation_options = ["Property Mapping", "DMG Data Cleanup", "AIM Data Cleanup"]

def reset_state_on_operation_change():
    current_op_sel = st.session_state.operation_selector # Get the new selection
    for key in defaults:
        if key not in ['current_operation', 'operation_selector']: # Preserve selection
             st.session_state[key] = defaults[key]
    st.session_state.uploaded_file_key += 1 
    for key_to_clear in PM_CONFIRMATION_STATE_KEYS:
        if key_to_clear in st.session_state: del st.session_state[key_to_clear]
    st.session_state.current_operation_for_results = None
    st.session_state.current_operation = current_op_sel # Apply new selection

default_index = 0
if st.session_state.current_operation in operation_options:
    default_index = operation_options.index(st.session_state.current_operation)

selected_operation = st.selectbox(
    "Select the task you want to perform:", options=operation_options, index=default_index,
    key="operation_selector", on_change=reset_state_on_operation_change 
)
# Ensure current_operation is synced if not changed by selectbox (e.g. initial load)
if "current_operation" not in st.session_state or st.session_state.current_operation != selected_operation:
    st.session_state.current_operation = selected_operation

with st.expander("ℹ Instructions and Inputs", expanded=True):
    st.markdown(f"**Selected Operation: {selected_operation}**\n---")
    if selected_operation == "Property Mapping":
        pm_headers = [ "Provider", "Source_Pty_Id", "AIM Code", "AIM Property Name", "Pty_iTarget_Pty_Idd", "Ext_Id"]
        st.markdown(f"""
            **Instructions for Property Mapping:**
            1.  **Excel File:** `.xlsx` or `.xls`. Headers in **Row {HEADER_ROW_ZERO_INDEXED + 1}**.
                *   Required: `{', '.join([f'**{h}**' for h in pm_headers])}`
            2.  **Upload & Generate:** Use 'Browse files' then 'Generate Script'.
            3.  **Filtering (Strict):** `Source_Pty_Id` == `AIM Code` == `Ext_Id`, `Source_Pty_Id` not blank, `Pty_iTarget_Pty_Idd` is number.
            4.  **Confirmation for Differences:** If valid rows (`Source_Pty_Id` not blank, `Pty_iTarget_Pty_Idd` number) have `Source_Pty_Id` not matching `AIM Code` AND `Ext_Id`, you'll be asked to confirm. Clicking 'Yes' generates the script including these.
        """)
        st.download_button("📄 Download Property Mapping Template (.xlsx)", get_template_excel(), "PropertyMapping_Template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    elif selected_operation == "DMG Data Cleanup": st.markdown("DMG Cleanup: Provide DB, YYYYMMDD periods, Scope (Actuals Only/All Book Types).")
    elif selected_operation == "AIM Data Cleanup": st.markdown("AIM Cleanup: Provide DB, YYYYMTHMM period.")
    st.markdown("---\n**General Support:** *Developed by:* Monish & Sanju | *Version:* 1.9.2 (PM Auto-continue)")

st.divider()
st.subheader(f"Step 2: Provide Inputs for '{selected_operation}'")

uploaded_file = None
if selected_operation == "Property Mapping":
    uploaded_file = st.file_uploader(
        "Upload Excel file:", type=['xlsx', 'xls'], key=f"uploader_prop_map_{st.session_state.uploaded_file_key}"
    )
    if uploaded_file and uploaded_file.name != st.session_state.get('file_name_processed_for_confirmation_state'):
         st.session_state.update({
             'processed_data': None, 'error_message': None, 'queries_generated': 0,
             'rows_read': 0, 'rows_filtered': 0,
             'sql_file_name_input': "", 'sql_file_name_input_val': "" 
         })
         for key_to_clear in PM_CONFIRMATION_STATE_KEYS:
            if key_to_clear in st.session_state: del st.session_state[key_to_clear]
         st.session_state.file_name_processed_for_confirmation_state = uploaded_file.name
         st.session_state.current_operation_for_results = None

elif selected_operation == "DMG Data Cleanup":
    st.text_input("Client Database Name:", key="dmg_client_db_input", value=st.session_state.dmg_client_db, on_change=lambda: st.session_state.update(dmg_client_db=st.session_state.dmg_client_db_input))
    c1,c2 = st.columns(2)
    c1.text_input("Start Period (YYYYMMDD):", key="dmg_start_period_input", value=st.session_state.dmg_start_period, on_change=lambda: st.session_state.update(dmg_start_period=st.session_state.dmg_start_period_input), max_chars=8)
    c2.text_input("End Period (YYYYMMDD):", key="dmg_end_period_input", value=st.session_state.dmg_end_period, on_change=lambda: st.session_state.update(dmg_end_period=st.session_state.dmg_end_period_input), max_chars=8)
    st.radio("Cleanup Scope:", ["Actuals Only", "All Book Types"], index=["Actuals Only", "All Book Types"].index(st.session_state.dmg_cleanup_scope), key="dmg_cleanup_scope_radio", on_change=lambda: st.session_state.update(dmg_cleanup_scope=st.session_state.dmg_cleanup_scope_radio), horizontal=True)

elif selected_operation == "AIM Data Cleanup":
    st.text_input("AIM Database Name:", key="aim_db_name_input", value=st.session_state.aim_db_name, on_change=lambda: st.session_state.update(aim_db_name=st.session_state.aim_db_name_input))
    st.text_input("Period (YYYYMTHMM):", key="aim_period_input", value=st.session_state.aim_period, on_change=lambda: st.session_state.update(aim_period=st.session_state.aim_period_input), max_chars=9)

st.divider()
st.subheader("Step 3: Generate SQL Script")

can_process = False
if selected_operation == "Property Mapping" and uploaded_file: can_process = True
elif selected_operation == "DMG Data Cleanup" and all([st.session_state.dmg_client_db, st.session_state.dmg_start_period, st.session_state.dmg_end_period, st.session_state.dmg_cleanup_scope]) and re.fullmatch(r"^\d{8}$", st.session_state.dmg_start_period) and re.fullmatch(r"^\d{8}$", st.session_state.dmg_end_period): can_process = True
elif selected_operation == "AIM Data Cleanup" and all([st.session_state.aim_db_name, st.session_state.aim_period]) and re.fullmatch(r"^\d{4}[Mm][Tt][Hh]\d{2}$", st.session_state.aim_period): can_process = True

process_button = st.button("⚙️ Generate Script", disabled=not can_process)

# --- Main Processing Logic ---
if process_button and can_process:
    st.session_state.current_operation_for_results = selected_operation
    spinner_message = f"Processing '{selected_operation}'..."
    
    if selected_operation == "Property Mapping":
        st.session_state.sql_file_name_input = ""; st.session_state.sql_file_name_input_val = ""
        for key_to_clear in PM_CONFIRMATION_STATE_KEYS:
            if key_to_clear in st.session_state: del st.session_state[key_to_clear]
        if uploaded_file: st.session_state.file_name_processed_for_confirmation_state = uploaded_file.name
        
        with st.spinner(spinner_message): process_property_mapping(uploaded_file)

    elif selected_operation == "DMG Data Cleanup":
        with st.spinner(spinner_message): process_dmg_cleanup(st.session_state.dmg_client_db, st.session_state.dmg_start_period, st.session_state.dmg_end_period, st.session_state.dmg_cleanup_scope)
    elif selected_operation == "AIM Data Cleanup":
        with st.spinner(spinner_message): process_aim_cleanup(st.session_state.aim_db_name, st.session_state.aim_period)
    else: st.warning("Not implemented.")

# Property Mapping continuation after Yes/No click (triggered by rerun)
elif selected_operation == "Property Mapping" and \
     'pm_confirmation_decision' in st.session_state and \
     uploaded_file and \
     st.session_state.get('file_name_processed_for_confirmation_state') == uploaded_file.name:
    
    st.session_state.current_operation_for_results = selected_operation
    with st.spinner(f"Finalizing Property Mapping based on your confirmation..."):
        process_property_mapping(uploaded_file)

# --- Step 4: Results ---
st.divider(); st.subheader("📊 Results")
if (st.session_state.get('processed_data') or st.session_state.get('error_message')) and \
   st.session_state.get('current_operation_for_results') == selected_operation:
    processed_identifier = st.session_state.get('file_name_processed', 'Input Parameters')
    if st.session_state.get('processed_data'):
        st.success(f"✅ Script generation complete for **{selected_operation}** using **{processed_identifier}**!")
        if selected_operation == "Property Mapping":
            c1,c2,c3=st.columns(3); c1.metric("Rows Read", st.session_state.get('rows_read',0))
            c2.metric("Rows Finalized", st.session_state.get('rows_filtered',0))
            c3.metric("Mappings Generated", st.session_state.get('queries_generated',0))
        elif selected_operation in ["DMG Data Cleanup", "AIM Data Cleanup"]: st.metric("SQL Script Generated", "1 Block" if st.session_state.get('queries_generated',0)>0 else "0 Blocks")
        
        st.code(st.session_state.processed_data[:1000] + ("..." if len(st.session_state.processed_data)>1000 else ""), language="sql")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        s_op = re.sub(r'\W+', '_', selected_operation)
        df_name = f"{s_op}_Script_{timestamp}"
        if selected_operation == "DMG Data Cleanup": df_name = f"{s_op}{'_ActualsOnly' if st.session_state.dmg_cleanup_scope == 'Actuals Only' else '_AllBookTypes'}_Script_{timestamp}"
        
        if selected_operation == "Property Mapping":
            def_pm_fname = f"Integrations_DF_ARES_Additional_Property_Mapping_PME-XXXXXX_{datetime.now().strftime('%Y%m%d')}.sql"
            st.session_state.sql_file_name_input_val = st.session_state.get('sql_file_name_input', def_pm_fname)
            uf_widget_val = st.text_input("SQL file name:", value=st.session_state.sql_file_name_input_val, key="sql_fname_widget")
            if uf_widget_val != st.session_state.sql_file_name_input_val:
                st.session_state.sql_file_name_input = uf_widget_val
                st.session_state.sql_file_name_input_val = uf_widget_val
            dl_fname = st.session_state.sql_file_name_input if st.session_state.sql_file_name_input else def_pm_fname
            if not dl_fname.lower().endswith('.sql'): dl_fname += '.sql'
        else:
            dl_fname = f"{df_name}.sql"; st.info(f"Download filename: `{dl_fname}`")
        
        st.download_button(f"📥 Download SQL Script ({dl_fname})", st.session_state.processed_data, dl_fname, "text/plain")

    elif st.session_state.get('error_message'):
        err_msg = st.session_state.error_message
        if selected_operation == "Property Mapping" and "User confirmation pending" in err_msg:
            st.info(f"ℹ️ Action Required for **{selected_operation}**: Respond to the confirmation prompt above.")
        elif "No matching/confirmed rows" in err_msg or "No data rows remained" in err_msg :
            st.warning(f"⚠️ No data rows for **{selected_operation}** in **{processed_identifier}**. No script generated.")
        else: st.error(f"❌ Processing failed for **{selected_operation}**: {err_msg}")

elif (st.session_state.get('processed_data') or st.session_state.get('error_message')) and \
     st.session_state.get('current_operation_for_results') != selected_operation:
    st.info(f"Results previously shown were for '{st.session_state.get('current_operation_for_results')}'. Generate script for '{selected_operation}'.")
else: st.info("Select operation, provide inputs, and click 'Generate Script'.")

st.divider(); st.caption(f"SQL Generator Tool | {selected_operation} | Version 1.9.2")
