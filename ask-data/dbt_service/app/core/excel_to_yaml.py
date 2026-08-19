import sys
import json
from pathlib import Path
import pandas as pd

def convert_excel_to_custom_yaml(excel_path: str, output_yaml_path: str) -> None:
    """Generates the bni_schema_definitions.yaml from the Excel file."""
    tables_df = pd.read_excel(excel_path, sheet_name="Tables")
    cols_df = pd.read_excel(excel_path, sheet_name="Columns")
    
    try:
        vals_df = pd.read_excel(excel_path, sheet_name="Value_Mappings")
    except Exception:
        vals_df = pd.DataFrame()
        
    # --- AUTO-SCHEMA RESOLUTION MAP ---
    # Build a lookup map of Table Name -> Schema from the Tables sheet
    table_schema_map = {}
    for _, table in tables_df.iterrows():
        t_name = str(table.get("Table Name", "")).strip()
        custom_schema = str(table.get("Schema / Database", "")).strip()
        if t_name and t_name.lower() != 'nan':
            if custom_schema and custom_schema.lower() != 'nan':
                table_schema_map[t_name] = custom_schema
            else:
                table_schema_map[t_name] = ""
    
    yaml_lines = [
        'version: "2.0"',
        'domain: "Bank Negara Indonesia Customer Analytics"',
        'database_type: "Cloudera Impala"',
        'database_name: "test"',
        '',
        'tables:'
    ]

    for _, table in tables_df.iterrows():
        table_name = str(table.get("Table Name", "")).strip()
        custom_schema = str(table.get("Schema / Database", "")).strip()
        
        if not table_name or table_name.lower() == 'nan':
            continue

        if custom_schema and custom_schema.lower() != 'nan':
            full_table_name = f"{custom_schema}.{table_name}"
        else:
            full_table_name = table_name

        table_desc_raw = table.get("Description")
        table_desc = str(table_desc_raw) if pd.notna(table_desc_raw) else ""
        table_desc = table_desc.replace('"', '\\"').replace('\n', '\\n')

        yaml_lines.append(f'  - name: {full_table_name}')
        yaml_lines.append(f'    description: "{table_desc}"')
        yaml_lines.append('    columns:')

        table_cols = cols_df[cols_df["Table Name"].astype(str).str.strip() == table_name]

        for _, col in table_cols.iterrows():
            col_name = str(col.get("Column Name", "")).strip()
            if not col_name or col_name.lower() == 'nan':
                continue
                
            data_type = str(col.get("Data Type", "")).strip()
            
            # Robust boolean parsing for PKs (matches excel_to_dbt.py)
            is_pk = col.get("Is PK?", False)
            if isinstance(is_pk, str):
                is_pk = is_pk.strip().upper() in ['TRUE', 'YES', '1']
            else:
                is_pk = bool(is_pk and not pd.isna(is_pk))
                
            ref_fk = col.get("References (Foreign Keys)")
            
            val_mode = col.get("Distinct Value Mode")
            static_vals = col.get("Static Allowed Values")

            col_desc_raw = col.get("Description")
            col_desc = str(col_desc_raw) if pd.notna(col_desc_raw) else ""

            meta_parts = []
            
            if pd.notna(val_mode) and str(val_mode).strip() != "NONE":
                meta_parts.append(f"Mode: {str(val_mode).strip()}")
            
            if pd.notna(static_vals) and str(static_vals).strip() and str(static_vals).strip().lower() != "nan":
                meta_parts.append(f"Allowed: [{str(static_vals).strip()}]")

            if not vals_df.empty:
                col_mappings = vals_df[(vals_df["Table Name"] == table_name) & (vals_df["Column Name"] == col_name)]
                if not col_mappings.empty:
                    value_entries = []
                    for _, mapping_row in col_mappings.iterrows():
                        db_val = str(mapping_row.get("Database Value", "")).strip()
                        syns = str(mapping_row.get("Synonyms / User Phrasing", "")).strip()
                        ctx = str(mapping_row.get("Description / Context", "")).strip()
                        
                        if db_val and db_val.lower() != "nan":
                            entry = f"{db_val}"
                            syn_list = [s.strip() for s in syns.split(",") if s.strip() and s.lower() != "nan"]
                            if syn_list:
                                entry += f" (Synonyms: {', '.join(syn_list)})"
                            if ctx and ctx.lower() != "nan":
                                entry += f" - {ctx}"
                            value_entries.append(entry)
                    
                    if value_entries:
                        meta_parts.append(f"Value Mappings: [{'; '.join(value_entries)}]")

            if meta_parts:
                col_desc += f" [LLM Context: {' | '.join(meta_parts)}]"

            col_desc = col_desc.replace('"', '\\"').replace('\n', '\\n')

            yaml_lines.append(f'      - name: {col_name}')
            yaml_lines.append(f'        type: "{data_type}"')
            
            if is_pk:
                yaml_lines.append('        primary_key: true')
            
            # --- AUTO-SCHEMA INJECTION FOR REFERENCES ---
            if pd.notna(ref_fk) and str(ref_fk).strip() and str(ref_fk).strip().lower() != 'nan':
                raw_refs = [r.strip() for r in str(ref_fk).split(";") if r.strip()]
                resolved_refs = []
                
                for r in raw_refs:
                    parts = r.split('.')
                    # If user provided table.column, auto-inject the schema from the Tables sheet
                    if len(parts) == 2:
                        target_table, target_col = parts
                        target_schema = table_schema_map.get(target_table, "")
                        if target_schema:
                            resolved_refs.append(f"{target_schema}.{target_table}.{target_col}")
                        else:
                            resolved_refs.append(r)
                    else:
                        # If user explicitly provided schema.table.column, leave it as is
                        resolved_refs.append(r)
                        
                clean_refs = "; ".join(resolved_refs)
                yaml_lines.append(f'        references: "{clean_refs}"')
                
            yaml_lines.append(f'        description: "{col_desc}"')

        yaml_lines.append('')
        
    models_dir = Path(output_yaml_path).parent
    models_dir.mkdir(parents=True, exist_ok=True)

    final_yaml = "\n".join(yaml_lines).strip() + "\n"

    with open(output_yaml_path, "w", encoding="utf-8") as f:
        f.write(final_yaml)


def convert_excel_to_golden_queries(excel_path: str, output_json_path: str) -> None:
    """Generates the bni_golden_queries.json from the Excel file."""
    try:
        try:
            queries_df = pd.read_excel(excel_path, sheet_name="Golden Queries")
        except Exception:
            queries_df = pd.read_excel(excel_path, sheet_name="Golden_Queries")
    except Exception:
        print("⚠️ Warning: Could not find 'Golden Queries' or 'Golden_Queries' sheet. Skipping JSON generation.")
        return

    queries_list = []
    for _, row in queries_df.iterrows():
        intent = str(row.get("User Intent", row.get("user_intent", ""))).strip()
        sql = str(row.get("SQL Template", row.get("sql_template", ""))).strip()
        complexity = str(row.get("Complexity", row.get("complexity", ""))).strip()
        
        if not intent or intent.lower() == 'nan':
            continue
            
        queries_list.append({
            "user_intent": intent,
            "sql_template": sql,
            "complexity": complexity
        })

    json_dir = Path(output_json_path).parent
    json_dir.mkdir(parents=True, exist_ok=True)

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(queries_list, f, indent=2)


if __name__ == "__main__":
    print("🚀 Starting Standalone Definitions Generator...")
    
    try:
        ask_data_root = Path(__file__).resolve().parent.parent.parent.parent
        if ask_data_root.name != "ask-data":
            ask_data_root = Path("/home/cdsw/ask-data")
    except Exception:
        ask_data_root = Path("/home/cdsw/ask-data")

    input_excel = ask_data_root / "data" / "bni_dbt_definitions.xlsx"
    output_yaml = ask_data_root / "data" / "bni_schema_definitions.yaml"
    output_json = ask_data_root / "data" / "bni_golden_queries.json"

    if not input_excel.exists():
        print(f"\n❌ Error: Cannot find the Excel file at {input_excel}")
        sys.exit(1)

    try:
        convert_excel_to_custom_yaml(str(input_excel), str(output_yaml))
        print("\n✅ Successfully generated properly formatted YAML definitions!")
        
        convert_excel_to_golden_queries(str(input_excel), str(output_json))
        print(f"✅ Successfully generated {output_json.name}!")
        
    except Exception as e:
        print(f"\n❌ Generation failed: {str(e)}")
        sys.exit(1)