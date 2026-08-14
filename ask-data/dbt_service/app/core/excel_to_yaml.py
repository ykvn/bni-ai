import sys
import json
from pathlib import Path
import pandas as pd

def convert_excel_to_custom_yaml(excel_path: str, output_yaml_path: str) -> None:
    """Generates the bni_schema_definitions.yaml from the Excel file."""
    # Read the Tables and Columns sheets from the Excel file
    tables_df = pd.read_excel(excel_path, sheet_name="Tables")
    cols_df = pd.read_excel(excel_path, sheet_name="Columns")
    
    # Initialize the YAML with top-level properties and explicit quotes
    yaml_lines = [
        'version: "1.0"',
        'domain: "Bank Negara Indonesia Customer Analytics"',
        'database_type: "Cloudera Impala"',
        'database_name: "test"',
        '',
        'tables:'
    ]

    # Process Business Tables
    for _, table in tables_df.iterrows():
        table_name = str(table.get("Table Name", "")).strip()
        
        if not table_name or table_name.lower() == 'nan':
            continue

        # Get description exactly as is, without stripping
        table_desc_raw = table.get("Description")
        table_desc = str(table_desc_raw) if pd.notna(table_desc_raw) else ""
        
        # Safely escape quotes and newlines for double-quoted YAML strings
        table_desc = table_desc.replace('"', '\\"').replace('\n', '\\n')

        # Add table level properties with quoted descriptions
        yaml_lines.append(f'  - name: {table_name}')
        yaml_lines.append(f'    description: "{table_desc}"')
        yaml_lines.append('    columns:')

        table_cols = cols_df[cols_df["Table Name"] == table_name]

        for _, col in table_cols.iterrows():
            col_name = str(col.get("Column Name", "")).strip()
            if not col_name or col_name.lower() == 'nan':
                continue
                
            data_type = str(col.get("Data Type", "")).strip()
            is_pk = col.get("Is PK?", False)
            ref_fk = col.get("References (Foreign Keys)")
            
            # Get description exactly as is, without stripping
            col_desc_raw = col.get("Description")
            col_desc = str(col_desc_raw) if pd.notna(col_desc_raw) else ""
            
            # Safely escape quotes and newlines for double-quoted YAML strings
            col_desc = col_desc.replace('"', '\\"').replace('\n', '\\n')

            # Append column properties maintaining the exact quote and spacing format
            yaml_lines.append(f'      - name: {col_name}')
            yaml_lines.append(f'        type: "{data_type}"')
            
            if str(is_pk).strip().lower() == 'true' or is_pk is True:
                yaml_lines.append('        primary_key: true')
            
            if pd.notna(ref_fk) and str(ref_fk).strip() and str(ref_fk).strip().lower() != 'nan':
                yaml_lines.append(f'        references: "{str(ref_fk).strip()}"')
                
            yaml_lines.append(f'        description: "{col_desc}"')

        # Add a new line after each table item
        yaml_lines.append('')
        
    models_dir = Path(output_yaml_path).parent
    models_dir.mkdir(parents=True, exist_ok=True)

    # Join all lines and remove any excessive trailing empty lines at the end of the file
    final_yaml = "\n".join(yaml_lines).strip() + "\n"

    # Write directly to the file to bypass PyYAML's automatic quote stripping
    with open(output_yaml_path, "w", encoding="utf-8") as f:
        f.write(final_yaml)


def convert_excel_to_golden_queries(excel_path: str, output_json_path: str) -> None:
    """Generates the bni_golden_queries.json from the Excel file."""
    # Attempt to read the Golden Queries sheet, falling back to variations of the name
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
        # Check standard column names, falling back to the JSON key formats
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

    # Ensure output directory exists
    json_dir = Path(output_json_path).parent
    json_dir.mkdir(parents=True, exist_ok=True)

    # Output as JSON with exactly matched quotes and indentations
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(queries_list, f, indent=2)


if __name__ == "__main__":
    print("🚀 Starting Standalone Definitions Generator...")
    
    # Establish root path based on the standard project directory layout
    try:
        ask_data_root = Path(__file__).resolve().parent.parent.parent.parent
        if ask_data_root.name != "ask-data":
            ask_data_root = Path("/home/cdsw/ask-data")
    except Exception:
        ask_data_root = Path("/home/cdsw/ask-data")

    # Target specific bni_dbt_definitions.xlsx input file
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