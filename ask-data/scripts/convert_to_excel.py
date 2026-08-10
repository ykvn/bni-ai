import pandas as pd
import re

# Paste your YAML content here
yaml_text = """
version: "1.0"
domain: "Bank Negara Indonesia Customer Analytics"
database_type: "Cloudera Impala"
database_name: "test"

tables:
  - name: cai_customers
... [REST OF YOUR YAML HERE] ...
"""

db_name = "test"
tables_rows, columns_rows = [], []

# Regex block matching
table_blocks = re.findall(r'-\s+name:\s+(cai_[a-z_]+)\s+description:\s+"(.*?)"\s+columns:(.*?)(?=\n\s+-\s+name:\s+cai_|\Z)', yaml_text, re.DOTALL)

for t_name, t_desc, cols_text in table_blocks:
    tables_rows.append({"Table Name": t_name.strip(), "Schema / Database": db_name, "Description": t_desc.strip()})
    
    col_blocks = re.findall(r'-\s+name:\s+([a-z_]+)(.*?)(?=\n\s+-\s+name:|\Z)', cols_text, re.DOTALL)
    for c_name, c_props in col_blocks:
        c_type = re.search(r'type:\s+"(.*?)"', c_props)
        c_type = c_type.group(1) if c_type else "STRING"
        
        is_pk = "TRUE" if "primary_key: true" in c_props else "FALSE"
        
        refs_match = re.search(r'references:\s+"(.*?)"', c_props)
        refs = refs_match.group(1) if refs_match else ""
        if " OR " in refs:
            refs = refs.replace(" OR ", "; ")
            
        c_desc_match = re.search(r'description:\s+"(.*?)"', c_props)
        c_desc = c_desc_match.group(1) if c_desc_match else ""
        
        custom_measures, distinct_mode, static_allowed = "", "NONE", ""
        
        # Auto-assign measures
        if any(t in c_type for t in ["DECIMAL", "INT", "FLOAT"]) and is_pk == "FALSE" and not refs:
            if "balance" in c_name or "amount" in c_name: custom_measures = "sum, avg, min, max"
            else: custom_measures = "sum, avg"
                
        # Auto-assign Distinct Value Modes
        if c_name == "status":
            distinct_mode = "STATIC_ENUM"
            if t_name == "cai_savings": static_allowed = "ACTIVE, DORMANT"
            elif t_name == "cai_deposits": static_allowed = "ACTIVE, MATURED, CANCELLED"
            elif t_name == "cai_loans": static_allowed = "ACTIVE, PAID_OFF, DEFAULTED"
            elif t_name == "cai_credit_cards": static_allowed = "ACTIVE, WARNING, BLOCKED"
        elif c_name == "transaction_type":
            distinct_mode, static_allowed = "STATIC_ENUM", "DEBIT, CREDIT"
        elif c_name == "loan_type":
            distinct_mode, static_allowed = "STATIC_ENUM", "Home, Auto, Personal"
        elif c_name in ["bank_name", "branch_name", "region"]:
            distinct_mode = "DYNAMIC_SQL_INDEX"
            
        columns_rows.append({
            "Table Name": t_name.strip(), "Column Name": c_name.strip(), "Data Type": c_type,
            "Is PK?": is_pk, "References (Foreign Keys)": refs, "Relationship": "belongs_to" if refs else "",
            "Custom Measures (Optional)": custom_measures, "Distinct Value Mode": distinct_mode,
            "Static Allowed Values": static_allowed, "Description": c_desc
        })

# Hardcode Base Value Mappings for BNI Context
value_mappings_rows = [
    {"Table Name": "cai_savings", "Column Name": "status", "Database Value": "ACTIVE", "Synonyms / User Phrasing": "aktif, live, berjalan, active, lancar", "Description / Context": "Account operating normally."},
    {"Table Name": "cai_savings", "Column Name": "status", "Database Value": "DORMANT", "Synonyms / User Phrasing": "pasif, mati, dormant, non-aktif, 180 hari", "Description / Context": "Inactive account."},
    {"Table Name": "cai_transactions", "Column Name": "transaction_type", "Database Value": "DEBIT", "Synonyms / User Phrasing": "debit, penarikan, tarik tunai, transfer keluar", "Description / Context": "Outflow ledger posting."},
    {"Table Name": "cai_transactions", "Column Name": "transaction_type", "Database Value": "CREDIT", "Synonyms / User Phrasing": "kredit, setoran, masuk, payroll, gaji", "Description / Context": "Inflow ledger posting."},
    {"Table Name": "cai_customers", "Column Name": "bank_name", "Database Value": "BNI", "Synonyms / User Phrasing": "Bank Negara Indonesia, BNI, Bank BNI", "Description / Context": "Core bank entity designation."}
]

# Write to Excel
excel_file = "schema_definitions_master.xlsx"
with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
    pd.DataFrame(tables_rows).to_excel(writer, sheet_name="Tables", index=False)
    pd.DataFrame(columns_rows).to_excel(writer, sheet_name="Columns", index=False)
    pd.DataFrame(value_mappings_rows).to_excel(writer, sheet_name="Value_Mappings", index=False)

print(f"Generated {excel_file} successfully!")