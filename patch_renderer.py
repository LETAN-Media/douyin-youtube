import re

with open('backend_audio/app/services/loop_renderer.py', 'r') as f:
    content = f.read()

target = """    if template_idx is not None:
        marks = _template_marks(duration, template_interval_s,
                                template_duration_s or 30.0)
        parts.append(
            f"[{template_idx}:v]scale={size},fps={fps},format=yuv420p[tmpl]")
        if marks:
            parts.append(f"[{current}][tmpl]overlay=0:0:enable='{marks}'[tbg]")
            current = "tbg"
        else:
            current = "bg\"\"\""""

target2 = """    if template_idx is not None:
        marks = _template_marks(duration, template_interval_s,
                                template_duration_s or 30.0)
        parts.append(
            f"[{template_idx}:v]scale={size},fps={fps},format=yuv420p[tmpl]")
        if marks:
            parts.append(f"[{current}][tmpl]overlay=0:0:enable='{marks}'[tbg]")
            current = "tbg"
        else:
            current = "bg"
"""

replacement = """    if template_idx is not None:
        marks = _template_marks(duration, template_interval_s,
                                template_duration_s or 30.0)
        if marks:
            parts.append(f"[{template_idx}:v]scale={size},fps={fps},format=yuv420p[tmpl]")
            parts.append(f"[{current}][tmpl]overlay=0:0:enable='{marks}'[tbg]")
            current = "tbg"
        else:
            current = "bg"
"""

if target2 in content:
    content = content.replace(target2, replacement)
    with open('backend_audio/app/services/loop_renderer.py', 'w') as f:
        f.write(content)
    print("Patched loop_renderer.py successfully!")
else:
    print("Target not found in loop_renderer.py")

