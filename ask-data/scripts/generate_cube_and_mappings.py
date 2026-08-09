import pandas as pd
import json
import os

# --- PATH CONFIGURATION BASED ON YOUR FOLDER STRUCTURE ---
# Since this script runs from ask-data/scripts/, we go up one level (../)
EXCEL_INPUT_PATH = "/home/cdsw/ask-data/data/bni_schema_definitions.xlsx"
CUBE_YAML_OUTPUT = "/home/cdsw/ask-data/cube_service/model/cubes/bni_schema_definitions.yaml"
MAPPINGS_JSON_OUTPUT = "/home/cdsw/ask-data/data/value_mappings.json"

def dict_to_yaml(data, indent=0):
    """Custom simple YAML exporter"""
    lines = []
    ind = " " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                if not v:
                    lines.append(f"{ind}{k}: []" if isinstance(v, list) else f"{ind}{k}: {{}}")
                else:
                    lines.append(f"{ind}{k}:")
                    lines.append(dict_to_yaml(v, indent + 2))
            else:
                if isinstance(v, bool):
                    v_str = "true" if v else "false"
                elif isinstance(v, str):
                    if "\n" in v or ":" in v or "'" in v or '"' in v or "{" in v or "}" in v:
                        v_str = json.dumps(v)
                    else:
                        v_str = v
                else:
                    v_str = str(v)
                lines.append(f"{ind}{k}: {v_str}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                item_yaml = dict_to_yaml(item, indent + 2).lstrip()
                lines.append(f"{ind}- {item_yaml}")
            else:
                lines.append(f"{ind}- {item}")
    return "\n".join(lines)

def generate_pipeline_files():
    print(f"Reading Master Excel: {EXCEL_INPUT_PATH}")
    
    # Read the 3 sheets
    df_tables = pd.read_excel(EXCEL_INPUT_PATH, sheet_name="Tables").fillna("")
    df_columns = pd.read_excel(EXCEL_INPUT_PATH, sheet_name="Columns").fillna("")
    df_mappings = pd.read_excel(EXCEL_INPUT_PATH, sheet_name="Value_Mappings").fillna("")

    cubes = []

    # Process Tables & Columns for Cube Core Data Model
    for _, table_row in df_tables.iterrows():
        table_name = str(table_row["Table Name"]).strip()
        db_schema = str(table_row.get("Schema / Database", "test")).strip()
        table_desc = str(table_row.get("Description", "")).strip()

        cube_entry = {
            "name": table_name,
            "sql_table": f"{db_schema}.{table_name}",
            "description": table_desc,
            "joins": [],
            "measures": [
                {"name": "count", "type": "count", "description": f"Total record count for {table_name}."}
            ],
            "dimensions": []
        }

        table_cols = df_columns[df_columns["Table Name"].str.strip() == table_name]

        for _, col_row in table_cols.iterrows():
            col_name = str(col_row["Column Name"]).strip()
            data_type = str(col_row["Data Type"]).upper().strip()
            is_pk = str(col_row.get("Is PK?", "FALSE")).upper().strip() == "TRUE"
            raw_ref = str(col_row.get("References (Foreign Keys)", "")).strip()
            relationship = str(col_row.get("Relationship", "belongs_to")).strip() or "belongs_to"
            col_desc = str(col_row.get("Description", "")).strip()
            custom_measures = str(col_row.get("Custom Measures (Optional)", "")).strip()
            distinct_mode = str(col_row.get("Distinct Value Mode", "NONE")).upper().strip()
            static_values = str(col_row.get("Static Allowed Values", "")).strip()

            if distinct_mode == "STATIC_ENUM" and static_values:
                col_desc += f" Expected values: {static_values}."

            # Parse physical SQL joins
            if raw_ref:
                for target in [r.strip() for r in raw_ref.split(";") if r.strip()]:
                    if "." in target:
                        ref_table, ref_col = target.split(".")[:2]
                        cube_entry["joins"].append({
                            "name": ref_table,
                            "sql": f"{{CUBE}}.{col_name} = {{{ref_table}.{ref_col}}}",
                            "relationship": relationship
                        })

            # Process Dimensions
            dim_type = "number" if any(t in data_type for t in ["INT", "DECIMAL", "FLOAT", "DOUBLE"]) else (
                "time" if any(t in data_type for t in ["DATE", "TIMESTAMP"]) else "string"
            )
            dim_entry = {"name": col_name, "sql": col_name, "type": dim_type, "description": col_desc}
            if is_pk:
                dim_entry["primary_key"] = True
            cube_entry["dimensions"].append(dim_entry)

            # Process Measures
            if dim_type == "number" and not is_pk and not raw_ref:
                aggs = [m.strip() for m in custom_measures.split(",") if m.strip()] if custom_measures else ["sum", "avg"]
                for agg in aggs:
                    cube_entry["measures"].append({
                        "name": f"{agg}_{col_name}",
                        "sql": col_name,
                        "type": agg,
                        "description": f"Calculates {agg.upper()} of {col_name}."
                    })

        cubes.append(cube_entry)

    # 1. Output Cube Data Model
    os.makedirs(os.path.dirname(CUBE_YAML_OUTPUT), exist_ok=True)
    with open(CUBE_YAML_OUTPUT, "w", encoding="utf-8") as f:
        f.write(dict_to_yaml({"cubes": cubes}))
    print(f"✅ Generated Cube Schema: {CUBE_YAML_OUTPUT}")

    # 2. Output Value Mappings JSON for Qdrant
    os.makedirs(os.path.dirname(MAPPINGS_JSON_OUTPUT), exist_ok=True)
    with open(MAPPINGS_JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(df_mappings.to_dict(orient="records"), f, indent=2)
    print(f"✅ Generated Value Mappings: {MAPPINGS_JSON_OUTPUT}")

if __name__ == "__main__":
    generate_pipeline_files()