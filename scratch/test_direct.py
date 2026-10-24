import asyncio
import os
import sys

os.environ["AUDIO_ADMIN_TOKEN"] = "Tan@230997"

from app.routes.pipelines import get_flow_status
from app.db.repositories import pipelines as pipe_repo

async def run_test():
    pipes = pipe_repo.list_pipelines()
    pid = next((p["id"] for p in pipes if p["name"] == "Audio Truyện"), pipes[0]["id"] if pipes else None)
    
    if not pid:
        print("No pipeline found")
        return
        
    result = await get_flow_status(pid)
    
    print("--- DIRECT INVOCATION SUCCESS ---")
    print(f"Counts: {result['counts']}")
    print(f"Queue size: {len(result['queue_preview'])}")
    print(f"Failures size: {len(result['recent_failures'])}")

if __name__ == "__main__":
    asyncio.run(run_test())
