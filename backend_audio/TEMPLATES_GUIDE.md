# Hướng dẫn Quản lý & Đồng bộ Template (Template Architecture Guide)

Tài liệu này quy chuẩn toàn bộ kiến trúc lưu trữ và đồng bộ Video Template giữa **VPS Local** và **Cloudflare R2** cho hệ thống `backend_audio`. Mọi AI Agent và Lập trình viên cần tuân thủ cấu trúc này.

---

## 1. Cấu trúc thư mục trên VPS Local
Tất cả video template tải lên VPS được tổ chức trong thư mục chuẩn `snake_case` (chữ thường, không dấu, nối bằng gạch dưới):
```text
/root/douyin-youtube/backend_audio/assets/template/
  ├── audio_truyen/      # Kênh "Audio Truyện" (ID: apl_fb648f456bc0)
  ├── mao_son_audio/     # Kênh "Mao Sơn Audio" (ID: apl_fb26d6b4c315)
  └── chuyen_ma_ne/      # Kênh "Chuyện Ma Nè"
```
- **Quy tắc**: Tên thư mục con đặt theo dạng `snake_case` không dấu (`audio_truyen`, `mao_son_audio`, `chuyen_ma_ne`) giúp gõ lệnh terminal dễ dàng, không bị lỗi khoảng trắng hay ký tự Unicode.

---

## 2. Cấu trúc lưu trữ trên Cloudflare R2 (Object Storage)
Trên Cloudflare R2 (Bucket `backend-audio`), dữ liệu được tổ chức chuẩn theo **Pipeline Slug (snake_case)** đồng bộ 1:1 với thư mục VPS:
```text
audio/pipelines/{pipeline_slug}/templates/
```
- **Ví dụ**:
  - Kênh `Audio Truyện`: `audio/pipelines/audio_truyen/templates/`
  - Kênh `Mao Sơn Audio`: `audio/pipelines/mao_son_audio/templates/`
  - Kênh `Chuyện Ma Nè`: `audio/pipelines/chuyen_ma_ne/templates/`
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
