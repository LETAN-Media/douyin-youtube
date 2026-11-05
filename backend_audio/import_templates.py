"""Import and optimize templates from local VPS directories into Cloudflare R2 and Turso DB.

Usage:
    # 1. Single pipeline:
    python3 import_templates.py --pipeline <pipeline_id> [--dir /root/templates/<pipeline_id>]

    # 2. Batch all subdirectories inside /root/templates/:
    # (Where each subfolder is named after the pipeline_id or slug)
    python3 import_templates.py --auto-scan /root/templates
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

def process_pipeline_templates(pipeline_id: str, src_dir: Path, orientation: str = "landscape"):
    db = get_client()
    pipe = db.execute("SELECT id, name, slug FROM audio_pipelines WHERE id = ? OR slug = ?", (pipeline_id, pipeline_id)).fetchone()
    if not pipe:
        print(f"❌ Error: Pipeline '{pipeline_id}' not found in database!")
        return 0

    real_pipeline_id = pipe["id"]
    print(f"\n=======================================================")
    print(f"🚀 Processing templates for: {pipe['name']} ({real_pipeline_id})")
    print(f"📂 Folder: {src_dir}")
    print(f"=======================================================")

    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
    files = [f for f in sorted(src_dir.iterdir()) if f.is_file() and f.suffix.lower() in video_extensions]

    if not files:
        print(f"⚠️ No video files found in {src_dir}")
        return 0

    print(f"Found {len(files)} video files.")
    success_count = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for i, src_file in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] Processing: {src_file.name} ({src_file.stat().st_size / (1024*1024):.1f} MB)...", flush=True)
            
            # 1. Register asset in DB
            asset = audio_repo.add_asset(
                pipeline_id=real_pipeline_id,
                kind="template",
                object_key=f"audio/pipelines/{real_pipeline_id}/templates/pending_{src_file.name}",
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
                    orientation=orientation,
                    threads=2
                )
            except Exception as exc:
                print(f"  ❌ Error optimizing {src_file.name}: {exc}")
                db.execute("DELETE FROM audio_media_assets WHERE id = ?", (asset_id,))
                continue

            # 3. Upload to R2
            target_key = f"audio/pipelines/{real_pipeline_id}/templates/{norm_mp4.name}"
            try:
                r2_storage.upload_file(norm_mp4, target_key, content_type="video/mp4")
            except Exception as exc:
                print(f"  ❌ Error uploading to R2: {exc}")
                db.execute("DELETE FROM audio_media_assets WHERE id = ?", (asset_id,))
                norm_mp4.unlink(missing_ok=True)
                continue

            # 4. Probe & update DB
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

    print(f"\n🎉 Finished {pipe['name']}: {success_count}/{len(files)} templates uploaded successfully!")
    return success_count

def main():
    parser = argparse.ArgumentParser(description="Ingest templates into R2 & Turso")
    parser.add_argument("--pipeline", help="Pipeline ID or Slug (e.g. apl_fb648f456bc0)")
    parser.add_argument("--dir", help="Path to local directory with video files")
    parser.add_argument("--auto-scan", help="Scan parent directory (e.g. /root/templates) where subfolders are pipeline IDs")
    parser.add_argument("--orientation", default="landscape", help="landscape or portrait")
    args = parser.parse_args()

    if args.auto-scan if hasattr(args, 'auto_scan') else args.auto_scan:
        scan_dir = Path(args.auto_scan)
        if not scan_dir.exists() or not scan_dir.is_dir():
            print(f"❌ Scan directory not found: {scan_dir}")
            sys.exit(1)
        subdirs = [d for d in sorted(scan_dir.iterdir()) if d.is_dir()]
        if not subdirs:
            print(f"⚠️ No subdirectories found in {scan_dir}")
            sys.exit(0)
        total = 0
        for d in subdirs:
            total += process_pipeline_templates(d.name, d, orientation=args.orientation)
        print(f"\n🌟 ALL DONE! Processed {total} templates across {len(subdirs)} pipelines.")
    elif args.pipeline:
        src_dir = Path(args.dir) if args.dir else Path(f"/root/templates/{args.pipeline}")
        if not src_dir.exists():
            print(f"❌ Error: Directory not found: {src_dir}")
            sys.exit(1)
        process_pipeline_templates(args.pipeline, src_dir, orientation=args.orientation)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
