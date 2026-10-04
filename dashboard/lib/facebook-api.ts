// Server-side Facebook backend client. Never import from client components.
// Token stays on the server: browser polls the Next.js proxy route instead.

export type FacebookFlowStepState =
  | "idle"
  | "running"
  | "done"
  | "error"
  | "not_configured";

export interface FacebookFlowState {
  pipeline_id: string;
  live: boolean;
  sources: number;
  inventory: number;
  queued: number;
  processing: number;
  failed: number;
  steps: {
    source: FacebookFlowStepState;
    inventory: FacebookFlowStepState;
    ai_metadata: FacebookFlowStepState;
    scheduler: FacebookFlowStepState;
    publisher: FacebookFlowStepState;
    youtube_destination: FacebookFlowStepState;
  };
}

export class FacebookApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function baseUrl(): string {
  return (process.env.FACEBOOK_API_URL ?? "").trim().replace(/\/+$/, "");
}

function adminToken(): string {
  return (process.env.FACEBOOK_ADMIN_TOKEN ?? "").trim();
}

export async function getFacebookFlowState(pipelineId: string): Promise<FacebookFlowState> {
  const base = baseUrl();
  if (!base) throw new FacebookApiError(500, "FACEBOOK_API_URL chưa được cấu hình.");
  const token = adminToken();
  if (!token) throw new FacebookApiError(500, "FACEBOOK_ADMIN_TOKEN chưa được cấu hình.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(
      `${base}/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/flow-state`,
      { headers: { "X-Admin-Token": token }, cache: "no-store", signal: controller.signal },
    );
    if (!res.ok) {
      throw new FacebookApiError(
        res.status,
        res.status === 404 ? "Không tìm thấy pipeline." : `Backend lỗi (HTTP ${res.status}).`,
      );
    }
    return (await res.json()) as FacebookFlowState;
  } catch (err) {
    if (err instanceof FacebookApiError) throw err;
    throw new FacebookApiError(503, "Không kết nối được backend Facebook.");
  } finally {
    clearTimeout(timer);
  }
}
