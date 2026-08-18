"""
Converts bni_dbt_definitions.xlsx into bni_dbt_schema.yaml and generates stub SQL files.
Path: /home/cdsw/ask-data/dbt_service/app/core/excel_to_dbt.py
"""
import sys
from pathlib import Path
import pandas as pd
import yaml
import re

def sanitize_dbt_name(name: str) -> str:
    """Ensures dbt names start with a letter and contain valid characters."""
    name = str(name).strip().lower()
    if not name or name == 'nan':
        return ""
    if name[0].isdigit():
        name = f"d_{name}"
    name = re.sub(r'[^a-z0-9_]', '_', name)
    return name

def convert_excel_to_dbt_yaml(excel_path: str, output_yaml_path: str) -> None:
    tables_df = pd.read_excel(excel_path, sheet_name="Tables")
    cols_df = pd.read_excel(excel_path, sheet_name="Columns")
    
    try:
        vals_df = pd.read_excel(excel_path, sheet_name="Value_Mappings")
    except Exception:
        vals_df = pd.DataFrame()

    alias_col = "Alias (Optional)"

    # Pre-pass 1: Find global entities (PKs or FKs across all tables) to prevent entity vs dimension collisions
    global_entities = set()
    for _, col in cols_df.iterrows():
        if col.get("Is PK?", False) or pd.notna(col.get("References (Foreign Keys)")):
            global_entities.add(str(col["Column Name"]).strip())

    # Pre-pass 2: Build a map of all target Primary Keys to their final Alias names
    target_pk_map = {}
    for _, table in tables_df.iterrows():
        t_name = str(table["Table Name"]).strip()
        if t_name == 'nan' or not t_name: continue
        
        t_cols = cols_df[cols_df["Table Name"] == t_name]
        for _, c in t_cols.iterrows():
            c_name = str(c["Column Name"]).strip()
            
            is_pk = c.get("Is PK?", False)
            if isinstance(is_pk, str):
                is_pk = is_pk.strip().upper() in ['TRUE', 'YES', '1']
            else:
                is_pk = bool(is_pk and not pd.isna(is_pk))
                
            if is_pk:
                raw_al = c.get(alias_col)
                if pd.notna(raw_al) and str(raw_al).strip() != "" and str(raw_al).strip().lower() != "nan":
                    alias_list = [sanitize_dbt_name(a.strip()) for a in re.split(r'[;,]', str(raw_al)) if a.strip()]
                    f_name = alias_list[0]
                else:
                    f_name = sanitize_dbt_name(c_name)
                
                target_pk_map[f"{t_name}.{c_name}".lower()] = f_name
                target_pk_map[c_name.lower()] = f_name

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
            raw_col_name = str(col["Column Name"]).strip()
            if raw_col_name == "nan" or not raw_col_name:
                continue
            safe_col_name = sanitize_dbt_name(raw_col_name)
            
            is_pk = col.get("Is PK?", False)
            if isinstance(is_pk, str):
                is_pk = is_pk.strip().upper() in ['TRUE', 'YES', '1']
            else:
                is_pk = bool(is_pk and not pd.isna(is_pk))
            
            ref_fk = col.get("References (Foreign Keys)")
            custom_measures = col.get("Custom Measures (Optional)")
            
            # --- SMART ALIAS LOGIC ---
            raw_alias = col.get(alias_col)
            str_ref = str(ref_fk).strip() if pd.notna(ref_fk) else ""
            
            alias_list = []
            if pd.notna(raw_alias) and str(raw_alias).strip() != "" and str(raw_alias).strip().lower() != "nan":
                alias_list = [sanitize_dbt_name(a.strip()) for a in re.split(r'[;,]', str(raw_alias)) if a.strip()]

            if alias_list:
                final_name = alias_list[0]
            else:
                final_name = safe_col_name
            # -------------------------
            
            val_mode = col.get("Distinct Value Mode")
            static_vals = col.get("Static Allowed Values")
            base_desc = str(col.get("Description", "")).strip()

            # 1. Primary Key Declaration (Supports multiple primary/unique aliases)
            if is_pk:
                if alias_list:
                    for i, al in enumerate(alias_list):
                        e_type = "primary" if i == 0 else "unique"
                        entities.append({"name": al, "type": e_type, "expr": raw_col_name})
                else:
                    entities.append({"name": safe_col_name, "type": "primary", "expr": raw_col_name})
            
            # 2. Explicit Foreign Keys (Handles semicolons, commas, dots, and multi-aliases)
            elif pd.notna(ref_fk) and str_ref.lower() not in ["", "nan", "true", "yes", "1"]:
                refs = [r.strip() for r in re.split(r'[;,]', str_ref) if r.strip()]
                for i, r in enumerate(refs):
                    lookup_key = r.lower()
                    
                    if i < len(alias_list):
                        fk_name = alias_list[i]
                    elif lookup_key in target_pk_map:
                        fk_name = target_pk_map[lookup_key]
                    else:
                        fk_name = r.split(".")[-1] if "." in r else r
                        
                    entities.append({"name": sanitize_dbt_name(fk_name), "type": "foreign", "expr": raw_col_name})
            
            # 3. Implicit Global Keys
            elif raw_col_name in global_entities:
                entities.append({"name": final_name, "type": "foreign", "expr": raw_col_name})
            
            # 4. Standard Dimensions
            else:
                col_type_str = str(col.get("Data Type", "")).upper()
                col_name_str = raw_col_name.lower()
                
                # Robust time dimension detection to prevent categorical vs time conflicts
                is_time_col = (
                    "DATE" in col_type_str or 
                    "TIME" in col_type_str or 
                    col_name_str == "as_of_date" or 
                    col_name_str.endswith("_date") or 
                    col_name_str.endswith("_time")
                )
                dim_type = "time" if is_time_col else "categorical"
                
                meta_parts = []
                if pd.notna(val_mode) and str(val_mode).strip() != "NONE":
                    meta_parts.append(f"Mode: {str(val_mode).strip()}")
                
                if pd.notna(static_vals):
                    meta_parts.append(f"Allowed: [{str(static_vals).strip()}]")

                # ✅ Map value-level Database Values, Synonyms, and Context
                if not vals_df.empty:
                    col_mappings = vals_df[(vals_df["Table Name"] == table_name) & (vals_df["Column Name"] == raw_col_name)]
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
                    "name": final_name, 
                    "type": dim_type, 
                    "expr": raw_col_name, 
                    "description": base_desc.strip()
                }
                
                if dim_type == "time":
                    dim_obj["type_params"] = {"time_granularity": "day"}
                    if not first_time_dim:
                        first_time_dim = final_name
                
                dimensions.append(dim_obj)

            if pd.notna(custom_measures):
                aggs = [a.strip().lower() for a in str(custom_measures).split(",")]
                for agg in aggs:
                    dbt_agg_type = "average" if agg == "avg" else agg
                    m_name = f"{table_name}_{final_name}_{agg}"
                    
                    measures.append({
                        "name": m_name, 
                        "expr": raw_col_name, 
                        "agg": dbt_agg_type,
                        "_base_desc": base_desc,
                        "_col_name": final_name,
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

        # Fallback for Impala/Flat tables: If no PRIMARY entity exists,
        # inject a synthetic primary entity to satisfy MetricFlow's semantic parser.
        has_primary_entity = any(e.get("type") == "primary" for e in entities)
        if not has_primary_entity and (dimensions or measures):
            entities.append({
                "name": f"{table_name}_id",
                "type": "primary",
                "expr": "1"
            })

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