"""Import and optimize templates from a local VPS directory into Cloudflare R2 and Turso DB.

Usage:
    python3 import_templates.py --pipeline <pipeline_id> --dir /root/templates_new
"""

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Add backend_audio to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db.client import get_client
from app.db.repositories import audio as audio_repo
from app.services import r2_storage, template_cache, audio_extractor

def main():
    parser = argparse.ArgumentParser(description="Ingest templates into R2 & Turso")
    parser.add_argument("--pipeline", required=True, help="Pipeline ID (e.g. apl_fb648f456bc0)")
    parser.add_argument("--dir", default="/root/templates_new", help="Path to local directory with video files")
    parser.add_argument("--orientation", default="landscape", help="landscape or portrait")
    args = parser.parse_args()

    pipeline_id = args.pipeline.strip()
    src_dir = Path(args.dir)

    if not src_dir.exists():
        print(f"❌ Error: Directory not found: {src_dir}")
        sys.exit(1)

    db = get_client()
    pipe = db.execute("SELECT id, name FROM audio_pipelines WHERE id = ?", (pipeline_id,)).fetchone()
    if not pipe:
        print(f"❌ Error: Pipeline {pipeline_id} not found in database!")
        sys.exit(1)

    print(f"🚀 Ingesting templates for Pipeline: {pipe['name']} ({pipeline_id})")
    
    # Collect video files
    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
    files = [f for f in sorted(src_dir.iterdir()) if f.is_file() and f.suffix.lower() in video_extensions]

    if not files:
        print(f"⚠️ No video files found in {src_dir}")
        return

    print(f"📂 Found {len(files)} video files in {src_dir}")

    success_count = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for i, src_file in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] Processing: {src_file.name} ({src_file.stat().st_size / (1024*1024):.1f} MB)...", flush=True)
            
            # 1. Register asset in DB first to get a standardized ID
            asset = audio_repo.add_asset(
                pipeline_id=pipeline_id,
                kind="template",
                object_key=f"audio/pipelines/{pipeline_id}/templates/pending_{src_file.name}",
                file_name=src_file.name,
                mime="video/mp4",
                enabled=1
            )
            asset_id = asset["id"]

            # 2. Normalize & optimize video
            norm_mp4 = tmp_path / f"{asset_id}_landscape_nologo.mp4"
            try:
                template_cache.normalize_template_video(
                    input_path=src_file,
                    output_path=norm_mp4,
                    orientation=args.orientation,
                    threads=2
                )
            except Exception as exc:
                print(f"  ❌ Error optimizing {src_file.name}: {exc}")
                db.execute("DELETE FROM audio_media_assets WHERE id = ?", (asset_id,))
                continue

            # 3. Upload optimized MP4 to R2
            target_key = f"audio/pipelines/{pipeline_id}/templates/{norm_mp4.name}"
            try:
                r2_storage.upload_file(norm_mp4, target_key, content_type="video/mp4")
            except Exception as exc:
                print(f"  ❌ Error uploading to R2: {exc}")
                db.execute("DELETE FROM audio_media_assets WHERE id = ?", (asset_id,))
                norm_mp4.unlink(missing_ok=True)
                continue

            # 4. Probe video & update DB with finalized object_key and size
            probe = audio_extractor.probe_video(norm_mp4)
            norm_size = norm_mp4.stat().st_size
            db.execute("""
                UPDATE audio_media_assets
                SET object_key = ?, file_name = ?, bytes = ?, width = ?, height = ?, duration_seconds = ?
                WHERE id = ?
            """, (target_key, norm_mp4.name, norm_size, probe.get("width"), probe.get("height"), probe.get("duration"), asset_id))

            print(f"  ✅ Uploaded to R2: {target_key} ({norm_size / 1024:.1f} KB)")
            norm_mp4.unlink(missing_ok=True)
            success_count += 1

    print(f"\n🎉 Successfully ingested {success_count}/{len(files)} templates into Pipeline {pipeline_id}!")

if __name__ == "__main__":
    main()
