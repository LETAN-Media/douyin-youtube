import re

with open('backend_audio/app/services/processing.py', 'r') as f:
    content = f.read()

target = """    avoid_bg_id = None
    for rj in jobs_repo.list_jobs(pipeline_id, limit=5):
        if rj["id"] != job_id and rj.get("background_asset_id"):
            avoid_bg_id = rj["background_asset_id"]
            break"""

replacement = """    avoid_bg_id = None
    for rj in jobs_repo.list_jobs(pipeline_id, limit=10):
        if rj["id"] != job_id and rj.get("background_asset_id") and rj.get("status") == "completed":
            avoid_bg_id = rj["background_asset_id"]
            break
    if not avoid_bg_id:
        for rj in jobs_repo.list_jobs(pipeline_id, limit=5):
            if rj["id"] != job_id and rj.get("background_asset_id"):
                avoid_bg_id = rj["background_asset_id"]
                break"""

if target in content:
    content = content.replace(target, replacement)
    with open('backend_audio/app/services/processing.py', 'w') as f:
        f.write(content)
    print("Patched processing.py successfully!")
else:
    print("Target not found in processing.py")

