"""
Converts bni_dbt_definitions.xlsx into bni_dbt_schema.yaml and generates stub SQL files.
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
    
    models_dir = Path(output_yaml_path).parent
    models_dir.mkdir(parents=True, exist_ok=True)

    # --- NEW: Auto-generate MetricFlow Time Spine ---
    time_spine_sql_path = models_dir / "metricflow_time_spine.sql"
    with open(time_spine_sql_path, "w") as sql_file:
        # Generates a 10,000 day calendar in Impala starting from 2015
        sql_file.write("""
WITH numbers AS (
  SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 
  UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
)
SELECT CAST('2015-01-01' AS TIMESTAMP) + INTERVAL (a.n + b.n*10 + c.n*100 + d.n*1000) DAY AS date_day
FROM numbers a 
CROSS JOIN numbers b 
CROSS JOIN numbers c 
CROSS JOIN numbers d
        """.strip())

    semantic_models.append({
        "name": "metricflow_time_spine",
        "description": "Required time spine for MetricFlow aggregations",
        "model": "ref('metricflow_time_spine')",
        "dimensions": [{
            "name": "date_day",
            "type": "time",
            "expr": "date_day",
            "type_params": {"time_granularity": "day"}
        }]
    })
    # ------------------------------------------------

    for _, table in tables_df.iterrows():
        table_name = str(table["Table Name"]).strip()
        table_cols = cols_df[cols_df["Table Name"] == table_name]

        sql_path = models_dir / f"{table_name}.sql"
        with open(sql_path, "w") as sql_file:
            sql_file.write(f"select * from {{{{ target.schema }}}}.{table_name}\n")

        entities = []
        dimensions = []
        measures = []

        for _, col in table_cols.iterrows():
            col_name = str(col["Column Name"]).strip()
            is_pk = col.get("Is PK?", False)
            ref_fk = col.get("References (Foreign Keys)")
            custom_measures = col.get("Custom Measures (Optional)")
            
            val_mode = col.get("Distinct Value Mode")
            static_vals = col.get("Static Allowed Values")
            base_desc = str(col.get("Description", "")).strip()

            if is_pk:
                entities.append({"name": col_name, "type": "primary", "expr": col_name})
            elif pd.notna(ref_fk):
                foreign_entity = str(ref_fk).split(".")[-1].split(";")[0].strip()
                entities.append({"name": foreign_entity, "type": "foreign", "expr": col_name})
            else:
                dim_type = "time" if "DATE" in str(col["Data Type"]).upper() or "TIME" in str(col["Data Type"]).upper() else "categorical"
                
                meta_parts = []
                if pd.notna(val_mode) and str(val_mode).strip() != "NONE":
                    meta_parts.append(f"Mode: {str(val_mode).strip()}")
                
                if pd.notna(static_vals):
                    meta_parts.append(f"Allowed: [{str(static_vals).strip()}]")

                if not vals_df.empty:
                    col_mappings = vals_df[(vals_df["Table Name"] == table_name) & (vals_df["Column Name"] == col_name)]
                    if not col_mappings.empty:
                        synonyms_list = []
                        for _, mapping_row in col_mappings.iterrows():
                            syns = [s.strip() for s in str(mapping_row.get("Synonyms / User Phrasing", "")).split(",") if s.strip()]
                            synonyms_list.extend(syns)
                        
                        if synonyms_list:
                            meta_parts.append(f"Synonyms: [{', '.join(set(synonyms_list))}]")
                
                if meta_parts:
                    base_desc += f" [LLM Context: {' | '.join(meta_parts)}]"

                dim_obj = {
                    "name": col_name, 
                    "type": dim_type, 
                    "expr": col_name, 
                    "description": base_desc.strip()
                }
                
                if dim_type == "time":
                    dim_obj["type_params"] = {"time_granularity": "day"}
                
                dimensions.append(dim_obj)

            if pd.notna(custom_measures):
                aggs = [a.strip().lower() for a in str(custom_measures).split(",")]
                for agg in aggs:
                    dbt_agg_type = "average" if agg == "avg" else agg
                    m_name = f"{table_name}_{col_name}_{agg}"
                    measures.append({"name": m_name, "expr": col_name, "agg": dbt_agg_type})
                    metrics.append({
                        "name": f"{table_name}_{col_name}_{agg}_metric",
                        "label": f"{table_name} {col_name} {agg}".title(),
                        "description": base_desc,
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

    with open(output_yaml_path, "w") as f:
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

    if not input_excel.exists():
        print(f"\n❌ Error: Cannot find the Excel file at {input_excel}")
        sys.exit(1)

    try:
        convert_excel_to_dbt_yaml(str(input_excel), str(output_yaml))
        print("\n✅ Successfully generated dbt bni_dbt_schema.yaml AND Time Spine!")
    except Exception as e:
        print(f"\n❌ Generation failed: {str(e)}")
        sys.exit(1)