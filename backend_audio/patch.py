with open("app/services/ai_metadata.py", "r") as f:
    content = f.read()

content = content.replace(
    'raise MetadataError(UPSTREAM_ERROR, f"ToolNet HTTP {resp.status_code}.")',
    'last_error = MetadataError(UPSTREAM_ERROR, f"ToolNet HTTP {resp.status_code}."); break'
)
content = content.replace(
    'raise MetadataError(INVALID_RESPONSE, "ToolNet response has no content.")',
    'last_error = MetadataError(INVALID_RESPONSE, "ToolNet response has no content."); break'
)
content = content.replace(
    'raise MetadataError(INVALID_RESPONSE, "Empty title after template.")',
    'last_error = MetadataError(INVALID_RESPONSE, "Empty title after template."); break'
)

with open("app/services/ai_metadata.py", "w") as f:
    f.write(content)
