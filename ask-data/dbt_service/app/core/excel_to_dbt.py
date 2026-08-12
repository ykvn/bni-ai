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

    # Pre-pass: Find global entities (PKs or FKs across all tables) to prevent entity vs dimension collisions
    global_entities = set()
    for _, col in cols_df.iterrows():
        if col.get("Is PK?", False) or pd.notna(col.get("References (Foreign Keys)")):
            global_entities.add(str(col["Column Name"]).strip())

    semantic_models = []
    metrics = []
    
    models_dir = Path(output_yaml_path).parent
    models_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate MetricFlow Time Spine SQL
    time_spine_sql_path = models_dir / "metricflow_time_spine.sql"
    with open(time_spine_sql_path, "w") as sql_file:
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

    # 2. Register Time Spine Model
    semantic_models.append({
        "name": "metricflow_time_spine",
        "description": "Required time spine for MetricFlow aggregations",
        "model": "ref('metricflow_time_spine')",
        "entities": [{
            "name": "date_id",           # ✅ Renamed entity to avoid namespace collision
            "type": "primary",
            "expr": "date_day"           # ✅ Points to the correct SQL column
        }],
        "dimensions": [{
            "name": "date_day",
            "type": "time",
            "expr": "date_day",
            "type_params": {"time_granularity": "day"}
        }]
    })

    # 3. Process Business Tables
    for _, table in tables_df.iterrows():
        table_name = str(table["Table Name"]).strip()
        custom_schema = str(table.get("Schema / Database", "")).strip()
        table_cols = cols_df[cols_df["Table Name"] == table_name]

        # Generate dbt stub SQL file with dynamic schema support
        sql_path = models_dir / f"{table_name}.sql"
        with open(sql_path, "w") as sql_file:
            if custom_schema and custom_schema.lower() != "nan":
                sql_file.write(f"{{{{ config(schema='{custom_schema}') }}}}\n")
                sql_file.write(f"select * from {custom_schema}.{table_name}\n")
            else:
                sql_file.write(f"select * from {{{{ target.schema }}}}.{table_name}\n")

        entities = []
        dimensions = []
        measures = []
        
        first_time_dim = None

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
            elif pd.notna(ref_fk) or col_name in global_entities:
                entities.append({"name": col_name, "type": "foreign", "expr": col_name})
            else:
                dim_type = "time" if "DATE" in str(col["Data Type"]).upper() or "TIME" in str(col["Data Type"]).upper() else "categorical"
                
                meta_parts = []
                if pd.notna(val_mode) and str(val_mode).strip() != "NONE":
                    meta_parts.append(f"Mode: {str(val_mode).strip()}")
                
                if pd.notna(static_vals):
                    meta_parts.append(f"Allowed: [{str(static_vals).strip()}]")

                # ✅ FIX: Map value-level Database Values, Synonyms, and Context
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
                    base_desc += f" [LLM Context: {' | '.join(meta_parts)}]"

                dim_obj = {
                    "name": col_name, 
                    "type": dim_type, 
                    "expr": col_name, 
                    "description": base_desc.strip()
                }
                
                if dim_type == "time":
                    dim_obj["type_params"] = {"time_granularity": "day"}
                    if not first_time_dim:
                        first_time_dim = col_name
                
                dimensions.append(dim_obj)

            if pd.notna(custom_measures):
                aggs = [a.strip().lower() for a in str(custom_measures).split(",")]
                for agg in aggs:
                    dbt_agg_type = "average" if agg == "avg" else agg
                    m_name = f"{table_name}_{col_name}_{agg}"
                    
                    measures.append({
                        "name": m_name, 
                        "expr": col_name, 
                        "agg": dbt_agg_type,
                        "_base_desc": base_desc,
                        "_col_name": col_name,
                        "_agg": agg
                    })

        # Fallback: If model has measures but no date column, inject dummy time dimension
        if measures and not first_time_dim:
            dimensions.append({
                "name": "dbt_dummy_time",
                "type": "time",
                "expr": "CAST('2020-01-01' AS TIMESTAMP)",
                "type_params": {"time_granularity": "day"}
            })
            first_time_dim = "dbt_dummy_time"

        # Attach agg_time_dimension to measures and construct metrics
        formatted_measures = []
        for m in measures:
            base_desc = m.pop("_base_desc")
            col_name = m.pop("_col_name")
            agg = m.pop("_agg")
            
            if first_time_dim:
                m["agg_time_dimension"] = first_time_dim
                
            formatted_measures.append(m)
            
            metrics.append({
                "name": f"{table_name}_{col_name}_{agg}_metric",
                "label": f"{table_name} {col_name} {agg}".title(),
                "description": base_desc,
                "type": "simple",
                "type_params": {"measure": m["name"]}
            })

        semantic_models.append({
            "name": table_name,
            "model": f"ref('{table_name}')",
            "entities": entities,
            "dimensions": dimensions,
            "measures": formatted_measures
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
        print("\n✅ Successfully generated dbt bni_dbt_schema.yaml from bni_dbt_definitions.xlsx!")
    except Exception as e:
        print(f"\n❌ Generation failed: {str(e)}")
        sys.exit(1)