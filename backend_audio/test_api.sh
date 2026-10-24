#!/bin/bash
# Test API for iOS Shortcut
# Usage: ./test_api.sh <facebook_url> [template_id]

set -e

# Configuration
API_BASE="https://audio-api.toolnet.tech"
ADMIN_TOKEN="Tan@230997"
PIPELINE_ID="apl_fb648f456bc0"

# Input
FACEBOOK_URL="${1:-https://www.facebook.com/share/v/1CAodRX1d4/?mibextid=wwXIfr}"
TEMPLATE_ID="${2:-amedia_b746325d27b8}"

echo "=========================================="
echo "Creating Manual Job"
echo "=========================================="
echo "Facebook URL: $FACEBOOK_URL"
echo "Template ID: $TEMPLATE_ID"
echo "Pipeline: $PIPELINE_ID"
echo ""

# Create job
RESPONSE=$(curl -s -X POST "$API_BASE/api/audio/pipelines/$PIPELINE_ID/manual" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"facebook_url\": \"$FACEBOOK_URL\",
    \"background_asset_id\": \"$TEMPLATE_ID\"
  }")

echo "Response:"
echo "$RESPONSE" | python3 -m json.tool

# Extract job ID
JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))")

if [ -z "$JOB_ID" ]; then
  echo ""
  echo "❌ Failed to create job"
  exit 1
fi

echo ""
echo "✅ Job created: $JOB_ID"
echo ""
echo "Check status:"
echo "  curl -H 'X-Admin-Token: $ADMIN_TOKEN' $API_BASE/api/audio/jobs/$JOB_ID"
echo ""
echo "Checking status in 10 seconds..."
sleep 10

# Check status
for i in {1..5}; do
  echo ""
  echo "[$i] Checking status..."
  STATUS_RESPONSE=$(curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "$API_BASE/api/audio/jobs/$JOB_ID")
  
  STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")
  STAGE=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('stage', ''))")
  PROGRESS=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('progress_percent', 0))")
  
  echo "Status: $STATUS | Stage: $STAGE | Progress: $PROGRESS%"
  
  if [ "$STATUS" = "completed" ]; then
    YOUTUBE_URL=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('youtube_url', ''))")
    TITLE=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('ai_title', ''))")
    echo ""
    echo "=========================================="
    echo "✅ COMPLETED!"
    echo "=========================================="
    echo "Title: $TITLE"
    echo "YouTube: $YOUTUBE_URL"
    echo "=========================================="
    exit 0
  elif [ "$STATUS" = "failed" ]; then
    ERROR_CODE=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('last_error_code', ''))")
    ERROR_MSG=$(echo "$STATUS_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('last_error_message', ''))")
    echo ""
    echo "❌ FAILED!"
    echo "Error: $ERROR_CODE - $ERROR_MSG"
    exit 1
  fi
  
  sleep 30
done

echo ""
echo "Job is still processing. Check manually:"
echo "  curl -H 'X-Admin-Token: $ADMIN_TOKEN' $API_BASE/api/audio/jobs/$JOB_ID"
