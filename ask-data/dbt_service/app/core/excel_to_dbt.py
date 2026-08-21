"""
Converts bni_dbt_definitions.xlsx into bni_dbt_schema.yaml and generates stub SQL files.
Path: /home/cdsw/ask-data/dbt_service/app/core/excel_to_dbt.py
"""
import sys
from pathlib import Path
import pandas as pd
import yaml
import re
from collections import defaultdict

def sanitize_dbt_name(name: str) -> str:
    """Ensures dbt names start with a letter and contain valid characters."""
    name = str(name).strip().lower()
    if not name or name == 'nan':
        return ""
    if name[0].isdigit():
        name = f"d_{name}"
    # Replace non-alphanumeric with underscore and truncate to 60 characters for dbt limits
    return re.sub(r'[^a-z0-9_]', '_', name)[:60]

def convert_excel_to_dbt_yaml(excel_path: str, output_yaml_path: str) -> None:
    tables_df = pd.read_excel(excel_path, sheet_name="Tables")
    cols_df = pd.read_excel(excel_path, sheet_name="Columns")
    
    try:
        vals_df = pd.read_excel(excel_path, sheet_name="Value_Mappings")
    except Exception:
        vals_df = pd.DataFrame()

    # --- AUTO-ROLE-PLAYING RESOLUTION ENGINE ---
    
    # 1. Map all explicit Primary Keys to their globally unique base entity names
    pk_base_name = {}
    target_entities = defaultdict(list)  # target_table.target_col -> [entity1, entity2, ...]
    
    for _, row in cols_df.iterrows():
        is_pk = row.get("Is PK?", False)
        if isinstance(is_pk, str):
            is_pk = is_pk.strip().upper() in ['TRUE', 'YES', '1']
        else:
            is_pk = bool(is_pk and not pd.isna(is_pk))
            
        if is_pk:
            t_name = sanitize_dbt_name(str(row["Table Name"]))
            c_name = sanitize_dbt_name(str(row["Column Name"]))
            
            # Auto-generate base PK entity name (e.g., funding_account_number)
            base_name = sanitize_dbt_name(f"{t_name}_{c_name}")
                
            pk_ref = f"{t_name}.{c_name}"
            pk_base_name[pk_ref] = base_name
            # The first entity appended to a target is its 'primary' entity
            target_entities[pk_ref].append(base_name)

    # 2. Discover Foreign Keys and Auto-Generate Unique Role-Playing Names
    fk_entity_map = defaultdict(list) # local_table.local_col -> [entity1, entity2, ...]
    global_entities = set() # Standard fallback for flat tables
    
    for _, row in cols_df.iterrows():
        t_name = sanitize_dbt_name(str(row["Table Name"]))
        c_name = sanitize_dbt_name(str(row["Column Name"]))
        raw_ref = row.get("References (Foreign Keys)")
        
        if pd.notna(raw_ref) and str(raw_ref).strip() and str(raw_ref).strip().lower() not in ['nan', 'none']:
            refs = [r.strip().lower() for r in str(raw_ref).split(';') if r.strip()]
            
            for r in refs:
                if "." not in r: continue
                target_t, target_c = r.split('.')
                target_t = sanitize_dbt_name(target_t)
                target_c = sanitize_dbt_name(target_c)
                
                # Check for Role-Playing (Local column name differs from target column name)
                if c_name == target_c:
                    # Generic join: use the target's primary entity name
                    ent_name = pk_base_name.get(r, sanitize_dbt_name(f"{target_t}_{target_c}"))
                else:
                    # Role-playing join: Append target table name to disambiguate
                    ent_name = sanitize_dbt_name(f"{c_name}_{target_t}")
                
                # Register the foreign entity on the local table
                fk_entity_map[f"{t_name}.{c_name}"].append(ent_name)
                
                # Register the unique entity on the target table (if not already there)
                if ent_name not in target_entities[r]:
                    target_entities[r].append(ent_name)
                    
            global_entities.add(c_name)

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

    # 2. Process Business Tables
    for _, table in tables_df.iterrows():
        table_name = str(table["Table Name"]).strip().lower()
        if table_name == 'nan' or not table_name: continue
        
        custom_schema = str(table.get("Schema / Database", "")).strip()

        # 🌟 NEW: Extract Availability Date for MetricFlow context
        avail_date_raw = table.get("Availability Date")
        avail_date = str(avail_date_raw).strip() if pd.notna(avail_date_raw) and str(avail_date_raw).strip().lower() != 'nan' else ""

        table_cols = cols_df[cols_df["Table Name"].astype(str).str.strip().str.lower() == table_name]

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
        
        explicit_time_dim = None
        first_time_dim = None

        for _, col in table_cols.iterrows():
            raw_col_name = str(col["Column Name"]).strip()
            if raw_col_name == "nan" or not raw_col_name:
                continue
            
            c_name_lower = raw_col_name.lower()
            safe_col_name = sanitize_dbt_name(raw_col_name)
            
            is_pk = col.get("Is PK?", False)
            if isinstance(is_pk, str):
                is_pk = is_pk.strip().upper() in ['TRUE', 'YES', '1']
            else:
                is_pk = bool(is_pk and not pd.isna(is_pk))
                
            local_ref_key = f"{table_name}.{c_name_lower}"
            custom_measures = col.get("Custom Measures (Optional)")
            
            val_mode = col.get("Distinct Value Mode")
            static_vals = col.get("Static Allowed Values")
            base_desc = str(col.get("Description", "")).strip()
            if base_desc.lower() == 'nan': base_desc = ""

            # 1. Entity Resolution (Supports Auto Role-Playing)
            if local_ref_key in target_entities:
                assigned_entities = target_entities[local_ref_key]
                for i, ent in enumerate(assigned_entities):
                    e_type = "primary" if (is_pk and i == 0) else "unique"
                    entities.append({"name": ent, "type": e_type, "expr": raw_col_name})
                    
            elif local_ref_key in fk_entity_map:
                for ent in fk_entity_map[local_ref_key]:
                    entities.append({"name": ent, "type": "foreign", "expr": raw_col_name})
                    
            # Implicit Global Keys
            elif c_name_lower in global_entities:
                entities.append({"name": safe_col_name, "type": "foreign", "expr": raw_col_name})
            
            # 2. Standard Dimensions
            else:
                col_type_str = str(col.get("Data Type", "")).upper()
                
                # Robust time dimension detection
                is_time_col = (
                    "DATE" in col_type_str or 
                    "TIME" in col_type_str or 
                    c_name_lower == "as_of_date" or 
                    c_name_lower.endswith("_date") or 
                    c_name_lower.endswith("_time")
                )
                dim_type = "time" if is_time_col else "categorical"
                
                # Explicit Agg Time Dimension Check
                is_agg_time = col.get("Agg Time Dimension", False)
                if isinstance(is_agg_time, str):
                    is_agg_time = is_agg_time.strip().upper() in ['TRUE', 'YES', '1']
                else:
                    is_agg_time = bool(is_agg_time and not pd.isna(is_agg_time))

                meta_parts = []
                if is_agg_time and avail_date:
                    meta_parts.append(f"Availability Date: {avail_date}")

                if pd.notna(val_mode) and str(val_mode).strip() != "NONE":
                    meta_parts.append(f"Mode: {str(val_mode).strip()}")
                
                if pd.notna(static_vals):
                    meta_parts.append(f"Allowed: [{str(static_vals).strip()}]")

                # Map value-level Database Values, Synonyms, and Context
                if not vals_df.empty:
                    col_mappings = vals_df[(vals_df["Table Name"].str.lower() == table_name) & (vals_df["Column Name"].str.lower() == c_name_lower)]
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
                    "name": safe_col_name, 
                    "type": dim_type, 
                    "expr": raw_col_name, 
                    "description": base_desc.strip()
                }
                
                if dim_type == "time":
                    dim_obj["type_params"] = {"time_granularity": "day"}
                    if not first_time_dim:
                        first_time_dim = safe_col_name
                    if is_agg_time:
                        explicit_time_dim = safe_col_name
                
                dimensions.append(dim_obj)

            if pd.notna(custom_measures) and str(custom_measures).strip() != "nan":
                aggs = [a.strip().lower() for a in str(custom_measures).split(",")]
                for agg in aggs:
                    dbt_agg_type = "average" if agg == "avg" else agg
                    m_name = sanitize_dbt_name(f"{table_name}_{safe_col_name}_{agg}")
                    
                    measures.append({
                        "name": m_name, 
                        "expr": f"NVL({raw_col_name}, 0)",
                        "agg": dbt_agg_type,
                        "_base_desc": base_desc,
                        "_col_name": safe_col_name,
                        "_agg": agg
                    })

        # Determine the final agg time dimension to use
        chosen_time_dim = explicit_time_dim if explicit_time_dim else first_time_dim

        # Fallback: If model has measures but no date column, inject dummy time dimension
        if measures and not chosen_time_dim:
            dimensions.append({
                "name": "dbt_dummy_time",
                "type": "time",
                "expr": "CAST('2020-01-01' AS TIMESTAMP)",
                "type_params": {"time_granularity": "day"}
            })
            chosen_time_dim = "dbt_dummy_time"

        # Fallback for Impala/Flat tables
        has_primary_entity = any(e.get("type") == "primary" for e in entities)
        if not has_primary_entity and (dimensions or measures):
            entities.append({
                "name": sanitize_dbt_name(f"{table_name}_id"),
                "type": "primary",
                "expr": "1"
            })

        # Attach agg_time_dimension to measures and construct metrics
        formatted_measures = []
        for m in measures:
            base_desc = m.pop("_base_desc")
            col_name = m.pop("_col_name")
            agg = m.pop("_agg")
            
            if chosen_time_dim:
                m["agg_time_dimension"] = chosen_time_dim
                
            formatted_measures.append(m)
            
            metric_desc = base_desc
            if avail_date and "Availability Date:" not in metric_desc:
                metric_desc += f" [LLM Context: Availability Date: {avail_date}]"

            metric_name = sanitize_dbt_name(f"{table_name}_{col_name}_{agg}_metric")
            metrics.append({
                "name": metric_name,
                "label": f"{table_name} {col_name} {agg}".title()[:100],
                "description": metric_desc,
                "type": "simple",
                "type_params": {"measure": m["name"]}
            })

        sm_dict = {
            "name": table_name,
            "model": f"ref('{table_name}')",
            "entities": entities,
            "dimensions": dimensions,
            "measures": formatted_measures
        }
        if avail_date:
            sm_dict["availability_date"] = avail_date

        semantic_models.append(sm_dict)

    # Assemble the final schema
    dbt_schema = {
        "version": 2,
        "models": [
            {
                "name": "metricflow_time_spine",
                "description": "Required time spine for MetricFlow aggregations",
                "time_spine": {
                    "standard_granularity_column": "date_day"
                },
                "columns": [
                    {
                        "name": "date_day",
                        "granularity": "day"
                    }
                ]
            }
        ],
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