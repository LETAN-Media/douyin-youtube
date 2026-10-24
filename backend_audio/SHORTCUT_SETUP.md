# iOS Shortcut Configuration for Audio Truyện

## Shortcut không tồn tại
Link shortcut bạn cung cấp không còn hoạt động:
- https://www.icloud.com/shortcuts/33a1a1d4ebaa4d3aadbfed7c8763528d ❌
- https://www.icloud.com/shortcuts/5a98d9118efa47c48429f04a04c669fd ❌

## API Endpoint Chính Xác

**Endpoint**: `POST /api/audio/pipelines/{pipeline_id}/manual`

**Full URL**: `https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual`

**Headers**:
```
X-Admin-Token: Tan@230997
Content-Type: application/json
```

**Request Body**:
```json
{
  "facebook_url": "https://www.facebook.com/share/v/...",
  "background_asset_id": "amedia_b746325d27b8",
  "title": "Optional custom title",
  "description": "Optional description",
  "hashtags": ["optional", "tags"]
}
```

## Test Script

Đã tạo script test tại: `/root/douyin-youtube/backend_audio/test_api.sh`

**Usage**:
```bash
cd /root/douyin-youtube/backend_audio
./test_api.sh "https://www.facebook.com/share/v/..." "amedia_b746325d27b8"
```

## Tạo iOS Shortcut Mới

### Bước 1: Tạo Shortcut Mới
1. Mở app **Shortcuts** trên iPhone/iPad
2. Tap **+** để tạo shortcut mới
3. Đặt tên: **Audio Truyện**

### Bước 2: Thêm Actions

#### Action 1: Nhận URL từ Share Sheet
- Tìm và thêm: **Receive URLs from Input**
- Hoặc: **Receive Any Input from Share Sheet**

#### Action 2: Chọn Template (Tùy chọn)
- Thêm: **Choose from Menu**
- Prompt: "Chọn template"
- Menu items:
  - **Template 1 (3.4M)** → Set variable `Template` = `amedia_b746325d27b8`
  - **Template 2 (2.6M)** → Set variable `Template` = `amedia_8b6d382358a8`
  - **Template 3 (5.6M)** → Set variable `Template` = `amedia_4987553ac178`
  - **Template 4 (13.1M)** → Set variable `Template` = `amedia_a50c2b39f4bc`
  - **Mặc định** → Set variable `Template` = `amedia_b746325d27b8`

#### Action 3: Tạo Request Body
- Thêm: **Dictionary**
- Keys:
  - `facebook_url` = `[URLs from Input]`
  - `background_asset_id` = `[Template variable]`

#### Action 4: Gọi API
- Thêm: **Get Contents of URL**
- URL: `https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual`
- Method: **POST**
- Headers:
  - Add `X-Admin-Token` = `Tan@230997`
  - Add `Content-Type` = `application/json`
- Request Body: **JSON** → Select dictionary từ bước 3

#### Action 5: Parse Response
- Thêm: **Get Dictionary Value**
- Key: `id`
- Dictionary: `[Contents of URL]`
- Set variable: `JobID`

#### Action 6: Hiển thị Kết Quả
- Thêm: **Show Notification**
- Title: `✅ Job Created`
- Body: `Job ID: [JobID]`

#### Action 7: Đợi và Kiểm Tra (Tùy chọn)
- Thêm: **Wait** 60 seconds
- Thêm: **Repeat** 20 times:
  - **Get Contents of URL**: `https://audio-api.toolnet.tech/api/audio/jobs/[JobID]`
  - Headers: `X-Admin-Token` = `Tan@230997`
  - **Get Dictionary Value**: `status` → Set variable `Status`
  - **If** `Status` = `completed`:
    - **Get Dictionary Value**: `youtube_url` → Set variable `YouTubeURL`
    - **Get Dictionary Value**: `ai_title` → Set variable `Title`
    - **Show Notification**: Title=`✅ Hoàn thành!`, Body=`[Title]`
    - **Open URLs**: `[YouTubeURL]`
    - **Exit Shortcut**
  - **If** `Status` = `failed`:
    - **Get Dictionary Value**: `last_error_message` → Set variable `Error`
    - **Show Notification**: Title=`❌ Lỗi`, Body=`[Error]`
    - **Exit Shortcut**
  - **Otherwise**:
    - **Wait** 30 seconds

### Bước 3: Cấu Hình Share Sheet
1. Tap vào icon **i** (info) của shortcut
2. Bật **Show in Share Sheet**
3. Chọn **URLs** trong Share Sheet Types
4. Tap **Done**

## Template IDs

| ID | File | Size |
|----|------|------|
| `amedia_b746325d27b8` | CC0199DC...mov | 3.4M |
| `amedia_8b6d382358a8` | A4C4DCEF...mov | 2.6M |
| `amedia_4987553ac178` | 5B07282B...mov | 5.6M |
| `amedia_a50c2b39f4bc` | F487520A...mov | 13.1M |
| `amedia_850090d8ced8` | 74C09867...mov | 6.9M |
| `amedia_ab8f9a95ffe6` | E8B62C99...mov | 12.1M |
| `amedia_e3d0ef095883` | 5A2DDE8D...mov | 11.5M |
| `amedia_0f358b258cba` | copy_D41...MOV | 2.0M |

## Kiểm Tra API bằng cURL

```bash
# Tạo job
curl -X POST https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual \
  -H "X-Admin-Token: Tan@230997" \
  -H "Content-Type: application/json" \
  -d '{
    "facebook_url": "https://www.facebook.com/share/v/1CAodRX1d4/",
    "background_asset_id": "amedia_b746325d27b8"
  }'

# Kiểm tra status
curl -H "X-Admin-Token: Tan@230997" \
  https://audio-api.toolnet.tech/api/audio/jobs/ajob_xxxxx
```

## Response Examples

### Success Response (Job Created)
```json
{
  "id": "ajob_2e1b7c505c1a",
  "pipeline_id": "apl_fb648f456bc0",
  "status": "queued",
  "stage": "pending",
  "progress_percent": 0,
  "mode": "manual",
  "manual_url": "https://www.facebook.com/share/v/...",
  "background_asset_id": "amedia_b746325d27b8",
  "created_at": "2026-10-17T12:40:41Z"
}
```

### Status Check Response (Completed)
```json
{
  "id": "ajob_2e1b7c505c1a",
  "status": "completed",
  "stage": "completed:done",
  "progress_percent": 100,
  "ai_title": "AUDIO NGÔN TÌNH TỔNG TÀI...",
  "ai_description": "...",
  "youtube_video_id": "_D4RIYC7Nhs",
  "youtube_url": "https://www.youtube.com/watch?v=_D4RIYC7Nhs"
}
```

### Status Check Response (Failed)
```json
{
  "id": "ajob_xxxxx",
  "status": "failed",
  "stage": "downloading:failed",
  "progress_percent": 12,
  "last_error_code": "SNAPVIDEO_UNRESOLVABLE",
  "last_error_message": "PHIMTAT response has no media URL."
}
```

## Troubleshooting

### Error: "Pipeline không tồn tại"
- Check pipeline_id = `apl_fb648f456bc0`

### Error: "Incorrect or missing API key"
- Check header `X-Admin-Token: Tan@230997`

### Error: "INVALID_URL"
- Facebook URL phải có format hợp lệ
- Ví dụ: `https://www.facebook.com/share/v/1CAodRX1d4/`

### Job failed với "SNAPVIDEO_UNRESOLVABLE"
- Video có thể là private hoặc bị xóa
- Thử lại với video public khác

### Job stuck ở "queued"
- Worker có thể chưa chạy
- Đợi vài phút hoặc liên hệ admin

## Các Job Đã Xử Lý Thành Công

1. ✅ ajob_de115dde8ac1 → https://www.youtube.com/watch?v=MO-H96NaZjM
2. ✅ ajob_48e5cb794890 → https://www.youtube.com/watch?v=R_hHeNVeYsI
3. ✅ ajob_f9770fce93d5 → https://www.youtube.com/watch?v=oPC2JBna4f4
4. ✅ ajob_20491189f080 → https://www.youtube.com/watch?v=hPM6MUXVqCU
5. ✅ ajob_146aa6932cdf → https://www.youtube.com/watch?v=6St1MUpyi_Y
6. ✅ ajob_2e1b7c505c1a → https://www.youtube.com/watch?v=_D4RIYC7Nhs
7. ✅ ajob_6d2c1541decc → https://www.youtube.com/watch?v=ODBbvJ5ozPQ

Tổng: 7 videos đã upload thành công lên YouTube qua pipeline Audio Truyện.
