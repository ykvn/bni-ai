import sys
import os

# 1. Print out diagnostic path details
print("🕵️  Diagnostic starting...")
print(f"📍 Current Working Directory: {os.getcwd()}")
print(f"🐍 Python Executable: {sys.executable}\n")

try:
    # 2. Verify Config Loading First
    from app.config import settings
    print("✅ Configuration module loaded successfully.")
    print(f"📋 Target Host: {settings.impala_host}")
    print(f"📋 Target Database: {settings.db_name}")
    print(f"📋 Target Username: {settings.cdp_user}")
    print(f"🔒 Password configured: {'Yes' if settings.cdp_pass else 'No'}\n")
    
    # 3. Import Impala Connection Client
    from app.tools.impala_client import execute_query
    
    print("📡 Contacting Cloudera Impala Virtual Warehouse...")
    
    # Run a lightweight test query
    test_sql = "SELECT 1 AS connection_status"
    result = execute_query(test_sql)
    
    print("\n🎉 CONNECTION VERIFIED SUCCESSFULLY!")
    print(f"📦 Data Payload Received: {result}")

except ImportError as ie:
    print(f"❌ Python environment import error: {str(ie)}")
    print("\n💡 Troubleshooting Steps:")
    print("1. Did you activate your virtual environment?")
    print("2. Did you install dependencies? Run: pip install -r requirements.txt")
except Exception as e:
    print("\n❌ Connection Failed.")
    print("📋 Troubleshooting error trace details:")
    print(f"----------------------------------------\n{str(e)}\n----------------------------------------")