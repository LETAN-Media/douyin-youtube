# iOS Shortcut Guide - Audio Truyện Backend

## API Information

- **Base URL**: `https://audio-api.toolnet.tech`
- **Admin Token**: `Tan@230997`
- **Pipeline ID**: `apl_fb648f456bc0` (Audio Truyện)

## Available Templates

| Template ID | File Name | Size |
|------------|-----------|------|
| amedia_b746325d27b8 | CC0199DC-DD54-4B6E-954C-F78ACAF0B933.mov | 3.4M |
| amedia_8b6d382358a8 | A4C4DCEF-57C1-4B48-AFE6-1FB246D4013C.mov | 2.6M |
| amedia_4987553ac178 | 5B07282B-21BC-496D-8BEB-9C0A8A706680.mov | 5.6M |
| amedia_a50c2b39f4bc | F487520A-7A9E-4581-967A-4271F30F784B.mov | 13.1M |
| amedia_850090d8ced8 | 74C09867-A855-487A-9B79-C3B49B46A37F.mov | 6.9M |
| amedia_ab8f9a95ffe6 | E8B62C99-1FCD-47D6-BE95-E1B6116EA448.mov | 12.1M |
| amedia_e3d0ef095883 | 5A2DDE8D-D572-478D-AF7B-2B19A7943618.mov | 11.5M |
| amedia_0f358b258cba | copy_D4113EBE-74D2-4E43-9ECE-002F6DD3CF97.MOV | 2.0M |

## iOS Shortcut Configuration

### Create Manual Job

**Endpoint**: `POST /api/audio/jobs`

**Headers**:
```
X-Admin-Token: Tan@230997
Content-Type: application/json
```

**Body**:
```json
{
  "pipeline_id": "apl_fb648f456bc0",
  "source_url": "https://www.facebook.com/share/v/...",
  "background_asset_id": "amedia_b746325d27b8"
}
```

**Example cURL**:
```bash
curl -X POST https://audio-api.toolnet.tech/api/audio/jobs \
  -H "X-Admin-Token: Tan@230997" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline_id": "apl_fb648f456bc0",
    "source_url": "https://www.facebook.com/share/v/1CAodRX1d4/",
    "background_asset_id": "amedia_b746325d27b8"
  }'
```

### Check Job Status

**Endpoint**: `GET /api/audio/jobs/{job_id}`

**Headers**:
```
X-Admin-Token: Tan@230997
```

**Example**:
```bash
curl https://audio-api.toolnet.tech/api/audio/jobs/ajob_2e1b7c505c1a \
  -H "X-Admin-Token: Tan@230997"
```

**Response**:
```json
{
  "id": "ajob_2e1b7c505c1a",
  "status": "completed",
  "stage": "completed:done",
  "progress_percent": 100,
  "ai_title": "AUDIO NGÔN TÌNH TỔNG TÀI...",
  "youtube_url": "https://www.youtube.com/watch?v=_D4RIYC7Nhs"
}
```

## iOS Shortcut Steps

### 1. Get Facebook URL from Share Sheet
- Add action: **Get URLs from Input**
- This captures the Facebook video URL

### 2. Choose Template (Optional)
- Add action: **Choose from Menu**
- Menu items: List of template IDs above
- Or use a default template

### 3. Create Job
- Add action: **Get Contents of URL**
- URL: `https://audio-api.toolnet.tech/api/audio/jobs`
- Method: `POST`
- Headers:
  - `X-Admin-Token`: `Tan@230997`
  - `Content-Type`: `application/json`
- Request Body: `JSON`
```json
{
  "pipeline_id": "apl_fb648f456bc0",
  "source_url": "[Facebook URL from step 1]",
  "background_asset_id": "[Selected template ID or amedia_b746325d27b8]"
}
```

### 4. Extract Job ID
- Add action: **Get Dictionary Value**
- Key: `id`
- Store in variable: `Job ID`

### 5. Show Notification
- Add action: **Show Notification**
- Title: "Job Created"
- Body: "Processing job [Job ID]. Check status later."

### 6. Wait and Check Status (Optional)
- Add action: **Wait** (60 seconds)
- Add action: **Repeat** (10 times)
  - Get Contents of URL: `https://audio-api.toolnet.tech/api/audio/jobs/[Job ID]`
  - Headers: `X-Admin-Token: Tan@230997`
  - Get Dictionary Value: `status`
  - If status = "completed":
    - Get Dictionary Value: `youtube_url`
    - Open URL: YouTube URL
    - Exit repeat
  - Otherwise:
    - Wait 30 seconds

## Shortcut Download Link

Since the old shortcut is deleted, create a new one using the steps above.

**Quick Setup**:
1. Open Shortcuts app
2. Create new shortcut
3. Add "Receive URLs from Share Sheet" 
4. Follow steps 2-6 above
5. Save as "Audio Truyện"
6. Enable in Share Sheet settings

## Testing

Test with this Facebook URL:
```
https://www.facebook.com/share/v/1CAodRX1d4/?mibextid=wwXIfr
```

Expected result:
- Job created within 2-3 seconds
- Video processed in 5-40 minutes (depending on length)
- YouTube URL returned when completed

## Troubleshooting

**Error: "Incorrect or missing API key"**
- Check X-Admin-Token header is set to `Tan@230997`

**Error: "SNAPVIDEO_UNRESOLVABLE"**
- Facebook URL may be private or expired
- Try a different public video

**Error: "File exceeds size cap"**
- Video is too large (>3GB)
- System automatically handles up to 3GB

## Support

For issues, check job status via API or contact admin.
