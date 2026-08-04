import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Database Credentials Configuration
# In Cloudera (CML), it's best practice to set these as Environment Variables
# Change DB_HOST to point to the local port exposed by your tunnel
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "Od!gVP7f98hDuYXmXN&P&gB98XGp")
DB_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")  # <-- Change this to local loopback
DB_PORT = os.getenv("MYSQL_PORT", "3306")
DB_NAME = os.getenv("MYSQL_DATABASE", "bank_abc_analytics")

# 2. Build connection URL (Clean & Python-native)
# PyMySQL natively handles the RSA key exchange via the 'cryptography' package 
# without requiring any extra URL flags.
SQLALCHEMY_DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# 3. Initialize Engine and Session Factory
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_pre_ping=True,  # Automatically checks/reconnects if connection drops
    pool_size=10, 
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency provider to inject database sessions into FastAPI routes safely
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
