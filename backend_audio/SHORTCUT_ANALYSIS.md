# Phân Tích Shortcut "Snap Video"

## Thông Tin Shortcut

- **Name**: Snap Video
- **Shortcut ID**: a6268818464a439497076a2ab589e33b
- **Link**: https://www.icloud.com/shortcuts/a6268818464a439497076a2ab589e33b

## API Sử Dụng

**PHIMTAT API**:
- URL: `https://api.phimtat.vn/json/snapvideo.json`
- API Key: `JILx9BLUzuCnwpXaSAygF9X10hIW3rNN`
- Redirect: `https://api.phimtat.vn/snapvideo/red64.php`

## Chức Năng

Shortcut này chỉ **tải video từ Facebook** (download only), KHÔNG upload lên YouTube hay xử lý audio.

**Flow**:
1. Nhận Facebook URL từ Share Sheet
2. Gọi PHIMTAT API để resolve video URL
3. Download video về máy
4. Lưu vào Photos/Files

## So Sánh với Audio Truyện Backend

| Tính năng | Snap Video | Audio Truyện Backend |
|-----------|------------|---------------------|
| Tải video từ Facebook | ✅ | ✅ |
| Trích xuất audio | ❌ | ✅ |
| Ghép template | ❌ | ✅ |
| Render video loop | ❌ | ✅ |
| Upload YouTube | ❌ | ✅ |
| AI metadata | ❌ | ✅ |

## Cần Làm Gì?

**Shortcut này KHÔNG liên quan đến Audio Truyện backend**. Bạn cần tạo shortcut MỚI để:

1. Nhận Facebook URL
2. Chọn template
3. Gọi API: `POST https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual`
4. Theo dõi job status
5. Mở YouTube URL khi hoàn thành

## Tạo Shortcut Audio Truyện

Sử dụng hướng dẫn trong file: `/root/douyin-youtube/backend_audio/SHORTCUT_SETUP.md`

**API Endpoint**:
```
POST https://audio-api.toolnet.tech/api/audio/pipelines/apl_fb648f456bc0/manual

Headers:
  X-Admin-Token: Tan@230997
  Content-Type: application/json

Body:
{
  "facebook_url": "https://www.facebook.com/share/v/...",
  "background_asset_id": "amedia_b746325d27b8"
}
```

## Test API

```bash
cd /root/douyin-youtube/backend_audio
./test_api.sh "https://www.facebook.com/share/v/1CAodRX1d4/"
```

## Kết Luận

- ✅ Shortcut "Snap Video" chỉ tải video, không xử lý audio/YouTube
- ❌ Không phải shortcut cho Audio Truyện backend
- 📝 Cần tạo shortcut mới theo hướng dẫn trong `SHORTCUT_SETUP.md`
- 🔑 API key PHIMTAT: `JILx9BLUzuCnwpXaSAygF9X10hIW3rNN` (đã có trong backend .env)
