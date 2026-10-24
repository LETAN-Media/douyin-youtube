import asyncio
import os
import boto3
from pathlib import Path
from app.config import settings
from app.db.repositories import audio

endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
s3 = boto3.client(
    "s3",
    endpoint_url=endpoint_url,
    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    region_name="auto"
)

def main():
    template_dir = Path("assets/template")
    
    prefix = "audio/pipelines/apl_fb648f456bc0/templates/"
    
    objs = s3.list_objects_v2(Bucket=settings.R2_BUCKET, Prefix=prefix)
    r2_keys = {o["Key"] for o in objs.get("Contents", [])}

    assets = audio.list_assets(pipeline_id="apl_fb648f456bc0", kind="template")
    turso_keys = {a["object_key"]: a for a in assets}

    for f in template_dir.glob("*.MOV"):
        obj_key = f"{prefix}{f.name}"
        
        # 1. Upload to R2 if missing
        if obj_key not in r2_keys:
            print(f"Uploading {f.name} to R2 ({obj_key})...")
            s3.upload_file(str(f), settings.R2_BUCKET, obj_key)
        
        # 2. Register in Turso if missing
        if obj_key not in turso_keys:
            print(f"Registering {f.name} in Turso...")
            audio.add_asset(
                pipeline_id="apl_fb648f456bc0",
                kind="template",
                object_key=obj_key,
                file_name=f.name,
                enabled=1
            )

if __name__ == "__main__":
    main()
