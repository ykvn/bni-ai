import os
    
def get_database_schema() -> str:
    """
    Safely locates and reads the master domain configuration blueprint 
    using absolute system routing paths to bypass container directory shifts.
    """
    # 🔒 Absolute enterprise path matching your repository layout
    primary_production_path = "/home/cdsw/ask-data/backend/domain_config.yaml"
    local_development_fallback = "../backend/domain_config.yaml"
    
    # Choose whichever path actively exists in the current container context
    target_path = primary_production_path if os.path.exists(primary_production_path) else local_development_fallback
    
    try:
        with open(target_path, "r", encoding="utf-8") as file:
            schema_content = file.read().strip()
            
        if not schema_content:
            return "Error: The domain_config.yaml file was found but it is completely empty."
            
        return schema_content
        
    except Exception as e:
        # Returns a detailed tracking message to identify the failure point immediately
        return f"Error: Enterprise configuration mapping file could not be read at {target_path}. System Details: {str(e)}"