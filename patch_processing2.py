import re

with open('backend_audio/app/services/processing.py', 'r') as f:
    content = f.read()

target = """    # Template periodic overlay check (only if explicitly enabled AND distinct from background)
    periodic_overlay_asset = None
    if proc_settings.get("template_enabled"):
        manual_tid = proc_settings.get("template_asset_id")"""

replacement = """    # Template periodic overlay check (only if explicitly enabled AND distinct from background)
    periodic_overlay_asset = None
    if proc_settings.get("template_enabled") and (not bg_asset or bg_asset.get("kind") != "template"):
        manual_tid = proc_settings.get("template_asset_id")"""

if target in content:
    content = content.replace(target, replacement)
    with open('backend_audio/app/services/processing.py', 'w') as f:
        f.write(content)
    print("Patched processing.py successfully!")
else:
    print("Target not found in processing.py")

