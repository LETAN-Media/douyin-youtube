#!/usr/bin/env python3
"""Export all Supabase data to SQL inserts for backup/verification."""
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv('.env')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("DATABASE_URL not set")
    sys.exit(1)

parsed = urlparse(DATABASE_URL)
PGUSER = parsed.username
PGPASSWORD = parsed.password
PGHOST = parsed.hostname
PGPORT = parsed.port or 5432
PGDB = parsed.path.lstrip('/')

# Use the database URL directly with SQLAlchemy
engine = create_engine(DATABASE_URL, pool_pre_ping=True, isolation_level="AUTOCOMMIT")

BACKUP_DIR = "/root/douyin-youtube/backups"
os.makedirs(BACKUP_DIR, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_file = os.path.join(BACKUP_DIR, f"supabase-before-turso-{timestamp}.sql")

# Get all tables
with engine.connect() as conn:
    tables = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)).fetchall()
    
    table_names = [t[0] for t in tables]
    print(f"Found {len(table_names)} tables")
    
    with open(backup_file, 'w') as f:
        f.write(f"-- Supabase backup exported at {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"-- Source: {PGHOST}:{PGPORT}/{PGDB}\n")
        f.write(f"-- Tables: {len(table_names)}\n\n")
        
        for table in table_names:
            count = conn.execute(text(f'SELECT COUNT(*) FROM {table}')).fetchone()[0]
            if count == 0:
                print(f"  {table}: 0 rows (skipped)")
                continue
            
            print(f"  {table}: {count} rows")
            f.write(f"-- Table: {table} ({count} rows)\n")
            
            rows = conn.execute(text(f'SELECT * FROM {table}')).fetchall()
            cols = [desc[0] for desc in conn.execute(text(f'SELECT * FROM {table} LIMIT 0')).cursor.description]
            
            for row in rows:
                values = []
                for val in row:
                    if val is None:
                        values.append('NULL')
                    elif isinstance(val, str):
                        escaped = val.replace("'", "''")
                        values.append(f"'{escaped}'")
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    elif isinstance(val, bool):
                        values.append('TRUE' if val else 'FALSE')
                    elif isinstance(val, datetime):
                        values.append(f"'{val.astimezone(timezone.utc).isoformat()}'")
                    else:
                        escaped = str(val).replace("'", "''")
                        values.append(f"'{escaped}'")
                
                col_list = ', '.join(cols)
                val_list = ', '.join(values)
                f.write(f"INSERT INTO {table} ({col_list}) VALUES ({val_list});\n")
            
            f.write("\n")
    
    print(f"\nBackup saved to: {backup_file}")
    print(f"Backup size: {os.path.getsize(backup_file) / 1024 / 1024:.2f} MB")
