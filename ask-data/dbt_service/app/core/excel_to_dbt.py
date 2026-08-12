"""
Converts bni_dbt_definitions.xlsx into bni_dbt_schema.yaml
Path: /home/cdsw/ask-data/dbt_service/app/core/excel_to_dbt.py
"""
import sys
from pathlib import Path
import pandas as pd
import yaml

def convert_excel_to_dbt_yaml(excel_path: str, output_yaml_path: str) -> None:
    tables_df = pd.read_excel(excel_path, sheet_name="Tables")
    cols_df = pd.read_excel(excel_path, sheet_name="Columns")
    
    try:
        vals_df = pd.read_excel(excel_path, sheet_name="Value_Mappings")
    except Exception:
        vals_df = pd.DataFrame()

    semantic_models = []
    metrics = []

    for _, table in tables_df.iterrows():
        table_name = str(table["Table Name"]).strip()
        table_cols = cols_df[cols_df["Table Name"] == table_name]

        entities = []
        dimensions = []
        measures = []

        for _, col in table_cols.iterrows():
            col_name = str(col["Column Name"]).strip()
            is_pk = col.get("Is PK?", False)
            ref_fk = col.get("References (Foreign Keys)")
            custom_measures = col.get("Custom Measures (Optional)")
            
            # --- NEW: Extract Value Mode & Static Values ---
            val_mode = col.get("Distinct Value Mode")
            static_vals = col.get("Static Allowed Values")

            if is_pk:
                entities.append({"name": col_name, "type": "primary", "expr": col_name})
            elif pd.notna(ref_fk):
                foreign_entity = str(ref_fk).split(".")[-1].split(";")[0].strip()
                entities.append({"name": foreign_entity, "type": "foreign", "expr": col_name})
            else:
                dim_type = "time" if "DATE" in str(col["Data Type"]).upper() or "TIME" in str(col["Data Type"]).upper() else "categorical"
                dim_obj = {
                    "name": col_name, 
                    "type": dim_type, 
                    "expr": col_name, 
                    "description": str(col.get("Description", ""))
                }
                if dim_type == "time":
                    dim_obj["type_params"] = {"time_granularity": "day"}
                
                # --- NEW: Initialize meta dictionary ---
                meta_dict = {}

                if pd.notna(val_mode) and str(val_mode).strip() != "NONE":
                    meta_dict["value_mode"] = str(val_mode).strip()
                
                if pd.notna(static_vals):
                    meta_dict["allowed_values"] = [v.strip() for v in str(static_vals).split(",")]

                # Extract Synonyms from Value_Mappings
                if not vals_df.empty:
                    col_mappings = vals_df[(vals_df["Table Name"] == table_name) & (vals_df["Column Name"] == col_name)]
                    if not col_mappings.empty:
                        synonyms_list = []
                        for _, mapping_row in col_mappings.iterrows():
                            syns = [s.strip() for s in str(mapping_row.get("Synonyms / User Phrasing", "")).split(",") if s.strip()]
                            synonyms_list.extend(syns)
                        
                        if synonyms_list:
                            meta_dict["synonyms"] = list(set(synonyms_list))
                
                # Attach meta dictionary if it contains anything
                if meta_dict:
                    dim_obj["meta"] = meta_dict
                
                dimensions.append(dim_obj)

            if pd.notna(custom_measures):
                aggs = [a.strip() for a in str(custom_measures).split(",")]
                for agg in aggs:
                    m_name = f"{table_name}_{col_name}_{agg}"
                    measures.append({"name": m_name, "expr": col_name, "agg": agg})
                    metrics.append({
                        "name": f"{table_name}_{col_name}_{agg}_metric",
                        "label": f"{table_name} {col_name} {agg}".title(),
                        "description": str(col.get("Description", "")),
                        "type": "simple",
                        "type_params": {"measure": m_name}
                    })

        semantic_models.append({
            "name": table_name,
            "model": f"ref('{table_name}')",
            "entities": entities,
            "dimensions": dimensions,
            "measures": measures
        })

    dbt_schema = {
        "version": 2,
        "semantic_models": semantic_models,
        "metrics": metrics
    }

    out_path = Path(output_yaml_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.dump(dbt_schema, f, sort_keys=False, default_flow_style=False)


if __name__ == "__main__":
    print("🚀 Starting Standalone dbt Schema Generator...")
    
    try:
        ask_data_root = Path(__file__).resolve().parent.parent.parent.parent
        if ask_data_root.name != "ask-data":
            ask_data_root = Path("/home/cdsw/ask-data")
    except Exception:
        ask_data_root = Path("/home/cdsw/ask-data")

    input_excel = ask_data_root / "data" / "bni_dbt_definitions.xlsx"
    output_yaml = ask_data_root / "dbt_service" / "dbt_project" / "models" / "bni_dbt_schema.yaml"
    
    print(f"📂 Input Source: {input_excel}")
    print(f"📂 Target YAML : {output_yaml}")

    if not input_excel.exists():
        print(f"\n❌ Error: Cannot find the Excel file at {input_excel}")
        sys.exit(1)

    try:
        convert_excel_to_dbt_yaml(str(input_excel), str(output_yaml))
        print("\n✅ Successfully generated dbt bni_dbt_schema.yaml with synonyms and allowed values!")
    except Exception as e:
        print(f"\n❌ Generation failed: {str(e)}")
        sys.exit(1)