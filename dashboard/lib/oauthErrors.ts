export function oauthErrorMessage(code?: string | null): string {
  switch (code) {
    case "oauth_state_invalid":
    case "oauth_state_reused":
    case "oauth_state_internal_mismatch":
    case "oauth_state_generation_failed":
      return "Phiên OAuth không hợp lệ hoặc đã được sử dụng. Vui lòng bấm Kết nối lại để tạo phiên mới.";
    case "oauth_state_expired":
      return "Phiên OAuth đã hết hạn. Vui lòng bấm Kết nối lại.";
    case "oauth_state_destination_mismatch":
    case "oauth_state_pipeline_mismatch":
    case "oauth_state_invalid_target":
      return "Phiên OAuth không khớp với channel/pipeline đích. Không có thay đổi nào được lưu; hãy Kết nối lại từ đúng kênh.";
    case "oauth_tenant_mismatch":
      return "Phiên OAuth không thuộc workspace của kênh này. Không có thay đổi nào được lưu.";
    case "oauth_callback_missing_code":
      return "Google không trả về authorization code. Vui lòng Kết nối lại.";
    case "oauth_invalid_grant":
      return "Google từ chối authorization code (invalid_grant). Code có thể đã hết hạn hoặc đã được dùng. Vui lòng Kết nối lại.";
    case "oauth_missing_refresh_token":
      return "Google không trả refresh token nên kênh không thể tự upload lâu dài. Vui lòng Kết nối lại và chấp nhận quyền offline.";
    case "oauth_access_denied":
    case "oauth_denied":
      return "Bạn đã từ chối cấp quyền cho ứng dụng. Vui lòng Kết nối lại và chấp nhận các quyền cần thiết.";
    case "oauth_permission_denied":
      return "Tài khoản Google không có đủ quyền cho kênh này. Vui lòng kiểm tra quyền YouTube và Kết nối lại.";
    case "oauth_channel_not_found":
      return "Không tìm thấy kênh YouTube nào trên tài khoản Google này.";
    case "oauth_destination_not_found":
    case "oauth_pipeline_not_found":
      return "Channel/pipeline đích không còn tồn tại. Vui lòng tải lại dashboard.";
    case "oauth_config_invalid":
      return "Cấu hình OAuth phía server chưa hợp lệ (HTTPS/PUBLIC_BASE_URL). Vui lòng báo admin kiểm tra.";
    case "oauth_channel_lookup_failed":
    case "oauth_exchange_failed":
    case "oauth_save_failed":
    case "oauth_unexpected_error":
      return "Không hoàn tất được kết nối YouTube. Token cũ (nếu có) vẫn được giữ nguyên; vui lòng thử Kết nối lại.";
    default:
      return "Kết nối YouTube thất bại. Vui lòng bấm Kết nối lại; nếu vẫn lỗi, kiểm tra log backend.";
  }
}
