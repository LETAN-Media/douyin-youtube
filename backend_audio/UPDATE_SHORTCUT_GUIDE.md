# Hướng Dẫn Update Shortcut "Snap Video" 

## Vấn Đề Hiện Tại

Shortcut "Snap Video" của bạn:
- ❌ Dùng PHIMTAT API (bị lỗi: "PHIMTAT response has no media URL")
- ❌ Chỉ tải video về máy
- ❌ KHÔNG upload lên YouTube
- ❌ KHÔNG có template

## Update Lên Phiên Bản Mới

### CÁCH 1: Tạo Mới (Khuyên dùng - 5 phút)

1. **Mở Shortcuts app** trên iPhone
2. **Import shortcut mới**:
   - Tải file `/tmp/audio_truyen_shortcut.plist` 
   - Hoặc tạo theo hướng dẫn bên dưới
3. **Đặt tên**: "Audio Truyện" 
4. **Xóa shortcut cũ** "Snap Video"
5. **Upload lên iCloud**: 
   - Tap vào shortcut → Share → Copy iCloud Link
   - Thay link cũ bằng link mới

---

### CÁCH 2: Edit Shortcut Hiện Tại (30 phút)

#### Bước 1: Mở Edit Shortcut "Snap Video"

1. Mở Shortcuts app
2. Tìm shortcut "Snap Video" 
3. Tap vào để edit

#### Bước 2: XÓA Actions Cũ Liên Quan PHIMTAT

Tìm và **XÓA** các actions sau:

- ❌ Action có URL: `https://api.phimtat.vn/json/snapvideo.json`
- ❌ Action có URL: `https://api.phimtat.vn/snapvideo/red64.php`
- ❌ Action có text: `api-key=JILx9BLUzuCnwpXaSAygF9X10hIW3rNN`
- ❌ Các action xử lý response từ PHIMTAT
- ❌ Action "Save to Photos" hoặc "Save File"

**GIỮ LẠI**:
- ✅ Action đầu tiên: "Get URLs from Input" hoặc "Receive URLs from Share Sheet"

#### Bước 3: THÊM Actions Mới

**Action 1: Set Variable (Facebook URL)**
```
Set variable [FacebookURL] to [Shortcut Input]
```

**Action 2: Choose from Menu (Template)**
```
Choose from Menu
Prompt: "Chọn Template"
Menu Items:
  - Template 1 (3.4M)
  - Template 2 (2.6M)
  - Template 3 (5.6M)
  - Template 4 (13M)
  - Mặc định
```

**Action 3-7: Menu Cases (Set Template ID)**

Trong mỗi case của menu:

Case "Template 1 (3.4M)":
```
Set variable [TemplateID] to "amedia_b746325d27b8"
```

Case "Template 2 (2.6M)":
```
Set variable [TemplateID] to "amedia_8b6d382358a8"
```

Case "Template 3 (5.6M)":
```
Set variable [TemplateID] to "amedia_4987553ac178"
```

Case "Template 4 (13M)":
```
Set variable [TemplateID] to "amedia_a50c2b39f4bc"
```

Case "Mặc định":
```
Set variable [TemplateID] to "amedia_b746325d27b8"
```

**Action 8: Dictionary (Request Body)**
```
Dictionary:
  facebook_url: [FacebookURL]
  background_asset_id: [TemplateID]
```

**Action 9: Get Contents of URL (Create Job)**
```
Get contents of:
  URL: https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual
  Method: POST
  Headers:
    X-Admin-Token: Tan@230997
    Content-Type: application/json
  Request Body: JSON
    [Dictionary from previous action]
```

**Action 10: Get Dictionary Value (Job ID)**
```
Get value for key "id" in [Contents of URL]
```

**Action 11: Set Variable (Job ID)**
```
Set variable [JobID] to [Dictionary Value]
```

**Action 12: Show Notification (Job Created)**
```
Show notification:
  Title: ✅ Job Created
  Body: Processing job [JobID]
        Đợi 2-40 phút...
```

**Action 13: Wait**
```
Wait 60 seconds
```

**Action 14: Repeat (Check Status)**
```
Repeat 15 times:
```

**Action 15: Get Contents of URL (Check Status)**
```
  Get contents of:
    URL: https://audio-api.toolnet.tech/api/audio/jobs/[JobID]
    Headers:
      X-Admin-Token: Tan@230997
```

**Action 16: Get Dictionary Value (Status)**
```
  Get value for key "status" in [Contents of URL]
```

**Action 17: Set Variable (Status)**
```
  Set variable [Status] to [Dictionary Value]
```

**Action 18: If (Status = completed)**
```
  If [Status] is "completed":
```

**Action 19: Get Contents of URL (Get Result)**
```
    Get contents of:
      URL: https://audio-api.toolnet.tech/api/audio/jobs/[JobID]
      Headers:
        X-Admin-Token: Tan@230997
```

**Action 20: Get Dictionary Value (YouTube URL)**
```
    Get value for key "youtube_url" in [Contents of URL]
```

**Action 21: Show Notification (Success)**
```
    Show notification:
      Title: ✅ Hoàn thành!
      Body: Video đã upload lên YouTube
```

**Action 22: Open URLs**
```
    Open [Dictionary Value] (YouTube URL)
```

**Action 23: Exit Shortcut**
```
    Exit Shortcut
```

**Action 24: End If**
```
  End If
```

**Action 25: Wait (Before Next Check)**
```
  Wait 120 seconds
```

**Action 26: End Repeat**
```
End Repeat
```

#### Bước 4: Configure Shortcut Settings

1. Tap icon **i** (Settings)
2. **Show in Share Sheet**: ON
3. **Share Sheet Types**: URLs
4. **Icon**: Chọn icon bạn thích
5. **Color**: Chọn màu

#### Bước 5: Test Shortcut

1. Mở Facebook, chọn 1 video public
2. Tap Share → Shortcuts → "Snap Video"
3. Chọn template
4. Đợi notification "Job Created"
5. Sau vài phút sẽ tự mở YouTube

---

## CÁCH 3: Import Từ File (Nhanh nhất - 2 phút)

### Trên iPhone/iPad:

1. **Download file** `/tmp/audio_truyen_shortcut.plist` về iPhone
   - Dùng iCloud Drive
   - Hoặc AirDrop từ Mac
   - Hoặc email file cho chính bạn

2. **Mở file** bằng Shortcuts app

3. **Đổi tên** thành "Snap Video" (nếu muốn giữ tên cũ)

4. **Xóa shortcut cũ**

5. **Done!** Link iCloud sẽ tự cập nhật (nếu bạn re-upload)

### Trên Mac:

```bash
# Copy file sang iPhone qua AirDrop
# Hoặc upload lên iCloud Drive
cp /tmp/audio_truyen_shortcut.plist ~/Library/Mobile\ Documents/com~apple~CloudDocs/
```

---

## So Sánh Trước/Sau Update

| Feature | Trước (Snap Video) | Sau (Updated) |
|---------|-------------------|---------------|
| API | PHIMTAT (lỗi ❌) | Backend API (✅) |
| Tải video | ✅ Về máy | ✅ Lên YouTube |
| Template | ❌ | ✅ 4 options |
| AI Metadata | ❌ | ✅ Auto |
| Render loop | ❌ | ✅ Auto |
| Theo dõi tiến trình | ❌ | ✅ Auto check |
| Mở YouTube | ❌ | ✅ Auto open |

---

## Troubleshooting

### "Shortcut quá dài, không edit được"
→ Dùng CÁCH 3: Import file mới

### "Không tìm thấy action X"
→ Tìm trong Search: "Get Contents of URL", "Dictionary", "Wait"...

### "Lỗi khi test"
→ Check:
- Header `X-Admin-Token: Tan@230997` đúng chưa
- URL đúng: `https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual`
- Facebook URL phải public

### "Job không hoàn thành"
→ Video dài cần thời gian xử lý:
- 10 phút video → ~10-15 phút
- 30 phút video → ~30-40 phút

---

## Files Cần Thiết

1. **Shortcut file**: `/tmp/audio_truyen_shortcut.plist`
2. **Hướng dẫn chi tiết**: `/root/douyin-youtube/backend_audio/AUDIO_TRUYEN_SHORTCUT.md`
3. **Test script**: `/root/douyin-youtube/backend_audio/test_api.sh`

---

## Khuyến Nghị

**DÙNG CÁCH 3** (Import file mới) vì:
- ✅ Nhanh nhất (2 phút)
- ✅ Không sợ sai
- ✅ Đầy đủ tính năng
- ✅ Đã test kỹ

Edit thủ công (CÁCH 2) rất dễ sai và mất thời gian.

---

**Created**: 2026-10-18  
**Status**: Ready to update  
**Recommend**: CÁCH 3 - Import file mới
