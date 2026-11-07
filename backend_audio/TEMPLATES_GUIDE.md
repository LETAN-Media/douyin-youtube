# Hướng dẫn Quản lý & Đồng bộ Template (Template Architecture Guide)

Tài liệu này quy chuẩn toàn bộ kiến trúc lưu trữ và đồng bộ Video Template giữa **VPS Local** và **Cloudflare R2** cho hệ thống `backend_audio`. Mọi AI Agent và Lập trình viên cần tuân thủ cấu trúc này.

---

## 1. Cấu trúc thư mục trên VPS Local
Tất cả video template tải lên VPS được tổ chức trong thư mục:
```text
/root/douyin-youtube/backend_audio/assets/template/
  ├── audio truyện/      # Chứa video template của Kênh "Audio Truyện" (ID: apl_fb648f456bc0)
  ├── Mao Sơn Audio/     # Chứa video template của Kênh "Mao Sơn Audio" (ID: apl_fb26d6b4c315)
  └── Chuyện Ma Nè/      # Chứa video template của Kênh "Chuyện Ma Nè"
```
- **Quy tắc**: Tên thư mục con đặt theo **Tên Kênh (tiếng Việt có dấu hoặc không dấu)** để người dùng dễ nhìn, dễ kéo thả file từ máy tính lên VPS.

---

## 2. Cấu trúc lưu trữ trên Cloudflare R2 (Object Storage)
Trên Cloudflare R2 (Bucket `backend-audio`), dữ liệu được tổ chức chuẩn theo **Pipeline ID**:
```text
audio/pipelines/{pipeline_id}/templates/
```
- **Ví dụ**:
  - Kênh `Audio Truyện`: `audio/pipelines/apl_fb648f456bc0/templates/`
  - Kênh `Mao Sơn Audio`: `audio/pipelines/apl_fb26d6b4c315/templates/`
- **Quy cách file**: 
  - Đã được chuẩn hóa H.264 MP4 720p 24fps.
  - Bitrate siêu nhẹ: `-crf 27 -maxrate 220k -bufsize 440k`.
  - Tên file chuẩn: `{asset_id}_landscape_nologo.mp4` (~160 - 250 KB/file).
  - Không còn sử dụng thư mục trung gian `templates_optimized/` hay file `.ts`.

---

## 3. Công cụ Nạp & Đồng bộ Tự động (`import_templates.py`)
File script: `/root/douyin-youtube/backend_audio/import_templates.py`

### Cách dùng 1: Tự động quét toàn bộ thư mục (Khuyên dùng)
```bash
cd /root/douyin-youtube/backend_audio
python3 import_templates.py
```
- Script tự động đọc mọi thư mục con trong `assets/template/`.
- Tự động map tên thư mục tiếng Việt (ví dụ `'audio truyện'`, `'Mao Sơn Audio'`) với Pipeline tương ứng trong Database Turso.
- Tự động nén chuẩn H.264 siêu nhẹ và upload thẳng lên R2: `audio/pipelines/{pipeline_id}/templates/`.
- Tự động đăng ký vào bảng `audio_media_assets` trong Turso DB.

### Cách dùng 2: Nạp cho 1 kênh cụ thể
```bash
python3 import_templates.py --pipeline "Mao Sơn Audio"
# Hoặc truyền ID:
python3 import_templates.py --pipeline apl_fb26d6b4c315
```

---

## 4. Cơ chế Fast Mux khi xuất bản Video
- Khi render video, hệ thống sử dụng module `app/services/template_cache.py` tải trực tiếp template đã chuẩn hóa từ `audio/pipelines/{pipeline_id}/templates/` (Cache HIT trong ~1-3s).
- Sử dụng FFmpeg Stream Copy (`-c copy`) ghép audio và video lặp loop:
  - Thời gian render (Fast Mux): **~2-3 giây** cho video 1 tiếng.
  - Tiêu thụ CPU: **0% CPU transcoding**.
  - Dung lượng video cuối: **~130 - 160 MB** cho video dài 1 tiếng.
- Upload YouTube chunked 32MB, hỗ trợ resumable upload và hiển thị % tiến độ upload.
