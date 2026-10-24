# Audio Truyện - iOS Shortcut (NEW)

## Download Shortcut

File đã được tạo tại: `/tmp/audio_truyen_shortcut.plist`

## Cách Cài Đặt

### Cách 1: Tạo Link iCloud (Khuyên dùng)

1. Mở **Shortcuts** app trên iPhone/iPad
2. Tap **+** để tạo shortcut mới
3. Import file `.plist` này
4. Hoặc tạo thủ công theo hướng dẫn dưới

### Cách 2: Tạo Thủ Công

**28 Actions:**

1. **Get Text** - Receive URLs from Share Sheet
2. **Set Variable** → `FacebookURL`
3. **Choose from Menu** - "Chọn Template"
   - Template 1 (3.4M)
   - Template 2 (2.6M)
   - Template 3 (5.6M)
   - Template 4 (13M)
   - Mặc định
4. **If** (Menu Item 1)
5. **Set Variable** → `TemplateID` = `amedia_b746325d27b8`
6. **Otherwise If** (Menu Item 2)
7. **Set Variable** → `TemplateID` = `amedia_8b6d382358a8`
8. **Otherwise If** (Menu Item 3)
9. **Set Variable** → `TemplateID` = `amedia_4987553ac178`
10. **Otherwise If** (Menu Item 4)
11. **Set Variable** → `TemplateID` = `amedia_a50c2b39f4bc`
12. **Otherwise** (Default)
13. **Set Variable** → `TemplateID` = `amedia_b746325d27b8`
14. **End If**
15. **Dictionary**:
    - `facebook_url`: `[FacebookURL]`
    - `background_asset_id`: `[TemplateID]`
16. **Get Contents of URL**:
    - URL: `https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual`
    - Method: `POST`
    - Headers:
      - `X-Admin-Token`: `Tan@230997`
      - `Content-Type`: `application/json`
    - Body: `JSON` → [Dictionary]
17. **Get Dictionary Value** → Key: `id`
18. **Set Variable** → `JobID`
19. **Show Notification**:
    - Title: `✅ Job Created`
    - Body: `Processing job [JobID]\nĐợi 2-40 phút...`
20. **Wait** 60 seconds
21. **Repeat** 15 times:
22.   **Get Contents of URL**:
      - URL: `https://audio-api.toolnet.tech/api/audio/jobs/[JobID]`
      - Headers: `X-Admin-Token`: `Tan@230997`
23.   **Get Dictionary Value** → Key: `status`
24.   **Set Variable** → `Status`
25.   **If** `Status` equals `completed`:
26.     **Get Contents of URL** (same as step 22)
27.     **Get Dictionary Value** → Key: `youtube_url`
28.     **Show Notification**: `✅ Hoàn thành!`
29.     **Open URLs**
30.     **Exit Shortcut**
31.   **End If**
32.   **Wait** 120 seconds
33. **End Repeat**

## Thông Tin API

**Backend API**: `https://audio-api.toolnet.tech`  
**Admin Token**: `Tan@230997`  
**Pipeline**: `apl_fb648f456bc0` (Audio Truyện)

## Templates

| ID | Size | Description |
|----|------|-------------|
| `amedia_b746325d27b8` | 3.4M | Template 1 (Default) |
| `amedia_8b6d382358a8` | 2.6M | Template 2 |
| `amedia_4987553ac178` | 5.6M | Template 3 |
| `amedia_a50c2b39f4bc` | 13M | Template 4 |

## Cách Sử Dụng

1. Mở Facebook, tìm video bạn muốn upload
2. Tap nút **Share** → chọn **Shortcuts**
3. Chọn **Audio Truyện**
4. Chọn template
5. Đợi notification "Job Created"
6. Sau 2-40 phút (tùy độ dài video), shortcut sẽ tự mở YouTube video

## Flow Diagram

```
Facebook URL → Choose Template → API Call → Job Created
                                              ↓
                                          Wait 60s
                                              ↓
                                    Check Status (x15)
                                    Every 120s
                                              ↓
                                    Status = completed?
                                              ↓
                                          Open YouTube
```

## So Sánh với Snap Video

| Feature | Snap Video (Cũ) | Audio Truyện (Mới) |
|---------|-----------------|-------------------|
| Tải video | ✅ PHIMTAT (lỗi) | ✅ FastSaver |
| Chọn template | ❌ | ✅ 4 options |
| Upload YouTube | ❌ | ✅ Auto |
| AI Metadata | ❌ | ✅ Auto |
| Theo dõi tiến trình | ❌ | ✅ Auto check |
| Mở YouTube | ❌ | ✅ Auto open |

## Troubleshooting

### Job không hoàn thành sau 30 phút
- Video có thể quá dài (>40 phút cần ~40 phút xử lý)
- Check thủ công: `curl -H "X-Admin-Token: Tan@230997" https://audio-api.toolnet.tech/api/audio/jobs/[JobID]`

### Lỗi "Incorrect API key"
- Check header `X-Admin-Token` = `Tan@230997`

### Video Facebook không tải được
- Đảm bảo video là **public**
- Link phải có format: `https://www.facebook.com/share/v/...`

## Test API

```bash
cd /root/douyin-youtube/backend_audio
./test_api.sh "https://www.facebook.com/share/v/1CAodRX1d4/"
```

## Upload to iCloud

Để share shortcut qua iCloud link:

1. Mở Shortcuts app trên Mac/iPhone
2. Import file `/tmp/audio_truyen_shortcut.plist`
3. Tap icon shortcut → **Share**
4. Chọn **Copy iCloud Link**
5. Share link đó với người khác

## Files Created

- `/tmp/audio_truyen_shortcut.plist` - Shortcut file (binary plist)
- `/root/douyin-youtube/backend_audio/SHORTCUT_SETUP.md` - Setup guide
- `/root/douyin-youtube/backend_audio/test_api.sh` - Test script

---

**Created**: 2026-10-17  
**Version**: 1.0  
**Status**: ✅ Ready to use
