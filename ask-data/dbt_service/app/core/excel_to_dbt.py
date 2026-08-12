"""
Converts bni_dbt_definitions.xlsx into bni_dbt_schema.yaml
Path: /home/cdsw/ask-data/dbt_service/app/core/excel_to_dbt.py
"""
import sys
from pathlib import Path
import pandas as pd
import yaml


def convert_excel_to_dbt_yaml(excel_path: str, output_yaml_path: str) -> None:
    """Reads Excel definitions and generates a dbt semantic layer YAML file."""
    tables_df = pd.read_excel(excel_path, sheet_name="Tables") #[cite: 4]
    cols_df = pd.read_excel(excel_path, sheet_name="Columns") #[cite: 4]

    semantic_models = [] #[cite: 4]
    metrics = [] #[cite: 4]

    for _, table in tables_df.iterrows(): #[cite: 4]
        table_name = str(table["Table Name"]).strip() #[cite: 4]
        table_cols = cols_df[cols_df["Table Name"] == table_name] #[cite: 4]

        entities = [] #[cite: 4]
        dimensions = [] #[cite: 4]
        measures = [] #[cite: 4]

        for _, col in table_cols.iterrows(): #[cite: 4]
            col_name = str(col["Column Name"]).strip() #[cite: 4]
            is_pk = col.get("Is PK?", False) #[cite: 4]
            ref_fk = col.get("References (Foreign Keys)") #[cite: 4]
            custom_measures = col.get("Custom Measures (Optional)") #[cite: 4]

            if is_pk: #[cite: 4]
                entities.append({"name": col_name, "type": "primary", "expr": col_name}) #[cite: 4]
            elif pd.notna(ref_fk): #[cite: 4]
                foreign_entity = str(ref_fk).split(".")[-1].split(";")[0].strip() #[cite: 4]
                entities.append({"name": foreign_entity, "type": "foreign", "expr": col_name}) #[cite: 4]
            else: #[cite: 4]
                dim_type = "time" if "DATE" in str(col["Data Type"]).upper() or "TIME" in str(col["Data Type"]).upper() else "categorical" #[cite: 4]
                dim_obj = {"name": col_name, "type": dim_type, "expr": col_name, "description": str(col.get("Description", ""))} #[cite: 4]
                if dim_type == "time": #[cite: 4]
                    dim_obj["type_params"] = {"time_granularity": "day"} #[cite: 4]
                dimensions.append(dim_obj) #[cite: 4]

            if pd.notna(custom_measures): #[cite: 4]
                aggs = [a.strip() for a in str(custom_measures).split(",")] #[cite: 4]
                for agg in aggs: #[cite: 4]
                    m_name = f"{table_name}_{col_name}_{agg}" #[cite: 4]
                    measures.append({"name": m_name, "expr": col_name, "agg": agg}) #[cite: 4]
                    metrics.append({ #[cite: 4]
                        "name": f"{table_name}_{col_name}_{agg}_metric", #[cite: 4]
                        "label": f"{table_name} {col_name} {agg}".title(), #[cite: 4]
                        "description": str(col.get("Description", "")), #[cite: 4]
                        "type": "simple", #[cite: 4]
                        "type_params": {"measure": m_name} #[cite: 4]
                    }) #[cite: 4]

        semantic_models.append({ #[cite: 4]
            "name": table_name, #[cite: 4]
            "model": f"ref('{table_name}')", #[cite: 4]
            "entities": entities, #[cite: 4]
            "dimensions": dimensions, #[cite: 4]
            "measures": measures #[cite: 4]
        }) #[cite: 4]

    dbt_schema = { #[cite: 4]
        "version": 2, #[cite: 4]
        "semantic_models": semantic_models, #[cite: 4]
        "metrics": metrics #[cite: 4]
    } #[cite: 4]

    out_path = Path(output_yaml_path) #[cite: 4]
    out_path.parent.mkdir(parents=True, exist_ok=True) #[cite: 4]
    with open(out_path, "w") as f: #[cite: 4]
        yaml.dump(dbt_schema, f, sort_keys=False, default_flow_style=False) #[cite: 4]


if __name__ == "__main__":
    print("🚀 Starting Standalone dbt Schema Generator...")
    
    # Resolve the root ask-data directory
    try:
        # If run from anywhere inside ask-data, this finds the root
        ask_data_root = Path(__file__).resolve().parent.parent.parent.parent
        if ask_data_root.name != "ask-data":
            ask_data_root = Path("/home/cdsw/ask-data")
    except Exception:
        ask_data_root = Path("/home/cdsw/ask-data")

    # Define exact input and output paths
    input_excel = ask_data_root / "data" / "bni_dbt_definitions.xlsx"
    output_yaml = ask_data_root / "dbt_service" / "dbt_project" / "models" / "bni_dbt_schema.yaml"
    
    print(f"📂 Input Source: {input_excel}")
    print(f"📂 Target YAML : {output_yaml}")

    if not input_excel.exists():
        print(f"\n❌ Error: Cannot find the Excel file at {input_excel}")
        sys.exit(1)

    try:
        convert_excel_to_dbt_yaml(str(input_excel), str(output_yaml))
        print("\n✅ Successfully generated dbt bni_dbt_schema.yaml!")
    except Exception as e:
        print(f"\n❌ Generation failed: {str(e)}")
        sys.exit(1)