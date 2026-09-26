"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  createDestination,
  createPipeline,
  createSource,
  deleteDestination,
  deletePipeline,
  deleteSource,
  getYoutubeOauthUrl,
  publishNow,
  reschedulePublication,
  retryJob,
  retryPublication,
  skipPublication,
  syncPipeline,
  syncSource,
  updateDestination,
  updatePipeline,
  updateSource,
} from "./api";
import { ApiError } from "./api";
import { slugify, parseSlots } from "./format";
import type { ActionResult } from "./types";

function err(e: unknown): ActionResult {
  if (e instanceof ApiError) return { ok: false, error: e.message };
  return { ok: false, error: e instanceof Error ? e.message : "Thao tác thất bại." };
}

// Targeted revalidation only: never revalidate "/" for pipeline-tab actions.
// Per-tab fetching makes `/pipelines/${id}` refresh cheap (1-3 requests).
// Full dashboard ("/") is only revalidated on create/delete pipeline.
function revalidatePipeline(id: string) {
  revalidatePath(`/pipelines/${id}`);
}

// ---------- Pipelines ----------

export async function actionCreatePipeline(
  form: FormData,
): Promise<ActionResult & { id?: string }> {
  try {
    const name = String(form.get("name") ?? "").trim();
    if (!name) return { ok: false, error: "Thiếu tên pipeline." };
    const slugRaw = String(form.get("slug") ?? "").trim();
    const slug = slugRaw ? slugify(slugRaw) : slugify(name);
    if (!slug) return { ok: false, error: "Slug không hợp lệ." };
    const strat = String(form.get("publishing_strategy") ?? "immediate").trim();
    const pipeline = await createPipeline({
      name,
      slug,
      niche: String(form.get("niche") ?? "").trim() || undefined,
      language: String(form.get("language") ?? "").trim() || undefined,
      default_privacy: String(form.get("default_privacy") ?? "public"),
      timezone: String(form.get("timezone") ?? "Asia/Ho_Chi_Minh").trim() || "Asia/Ho_Chi_Minh",
      daily_upload_limit: Number(form.get("daily_upload_limit") ?? 6) || 6,
      upload_slots: parseSlots(String(form.get("upload_slots") ?? "09:00,12:00,18:00,21:00")),
      youtube_default_publish_mode: strat === "scheduled" ? "scheduled" : "immediate",
    } as never);
    revalidatePath("/");
    return { ok: true, id: pipeline.id };
  } catch (e) {
    return err(e);
  }
}

export async function actionTogglePipeline(
  id: string,
  enabled: boolean,
): Promise<ActionResult> {
  try {
    await updatePipeline(id, { enabled });
    revalidatePipeline(id);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionUpdatePipelineSettings(
  id: string,
  form: FormData,
): Promise<ActionResult> {
  try {
    const payload: Record<string, unknown> = {};
    const name = String(form.get("name") ?? "").trim();
    if (name) payload.name = name;
    const niche = String(form.get("niche") ?? "");
    payload.niche = niche.trim() || null;
    const language = String(form.get("language") ?? "").trim();
    if (language) payload.language = language;
    payload.default_privacy = String(form.get("default_privacy") ?? "public");
    payload.timezone = String(form.get("timezone") ?? "UTC").trim() || "UTC";
    payload.daily_upload_limit = Number(form.get("daily_upload_limit") ?? 6) || 6;
    payload.upload_slots = parseSlots(String(form.get("upload_slots") ?? ""));
    payload.backlog_slots_per_day = Number(form.get("backlog_slots_per_day") ?? 4);
    payload.new_slots_per_day = Number(form.get("new_slots_per_day") ?? 2);
    payload.backlog_order = String(form.get("backlog_order") ?? "asc");
    payload.backlog_threshold_days = Number(form.get("backlog_threshold_days") ?? 7) || 7;
    await updatePipeline(id, payload);
    revalidatePipeline(id);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionUpdateAiProfile(
  id: string,
  form: FormData,
): Promise<ActionResult> {
  try {
    const split = (v: FormDataEntryValue | null) =>
      String(v ?? "")
        .split(/[\n,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    await updatePipeline(id, {
      niche: String(form.get("niche") ?? "").trim() || null,
      language: String(form.get("language") ?? "").trim() || null,
      fixed_hashtags: split(form.get("fixed_hashtags")),
      adaptive_hashtags: split(form.get("adaptive_hashtags")),
      prompt_profile: String(form.get("prompt_profile") ?? ""),
    });
    revalidatePipeline(id);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionDeletePipeline(id: string): Promise<ActionResult> {
  try {
    await deletePipeline(id);
    revalidatePath("/");
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

// ---------- Sources ----------

export async function actionCreateSource(
  pipelineId: string,
  form: FormData,
): Promise<ActionResult> {
  try {
    const name = String(form.get("name") ?? "").trim();
    const profileUrl = String(form.get("profile_url") ?? "").trim();
    if (!name) return { ok: false, error: "Thiếu tên source." };
    if (!profileUrl) return { ok: false, error: "Thiếu profile URL." };
    await createSource(pipelineId, { name, profile_url: profileUrl });
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionToggleSource(
  pipelineId: string,
  id: string,
  enabled: boolean,
): Promise<ActionResult> {
  try {
    await updateSource(id, { enabled });
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionDeleteSource(
  pipelineId: string,
  id: string,
): Promise<ActionResult> {
  try {
    await deleteSource(id);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionSyncSource(
  pipelineId: string,
  id: string,
): Promise<ActionResult & { status?: string }> {
  try {
    // Backend returns 202 queued immediately (<500ms); worker runs in background.
    const r = await syncSource(id);
    revalidatePipeline(pipelineId);
    const status =
      typeof (r as { status?: unknown }).status === "string"
        ? (r as { status: string }).status
        : "queued";
    return { ok: true, status };
  } catch (e) {
    return err(e);
  }
}

export async function actionSyncPipeline(pipelineId: string): Promise<ActionResult> {
  try {
    // 202 queued immediately; dashboard polls source statuses in background.
    await syncPipeline(pipelineId);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

// Polling helper for the realtime flow graph: no revalidation, tiny GET.
export async function actionGetFlowState(
  pipelineId: string,
): Promise<
  { ok: true; flow: import("./types").FlowState } | { ok: false; error: string }
> {
  try {
    const { getFlowState } = await import("./api");
    const flow = await getFlowState(pipelineId);
    return { ok: true, flow };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e.message };
    return { ok: false, error: e instanceof Error ? e.message : "Không tải được flow state." };
  }
}

// Polling helper for background sync: no revalidation, tiny GET (8s timeout).
export async function actionGetSourceStatus(
  id: string,
): Promise<ActionResult & { status?: string; errorDetail?: string }> {
  try {
    const { getSource } = await import("./api");
    const s = await getSource(id);
    return {
      ok: true,
      status: s.inventory_sync_status,
      errorDetail: s.inventory_sync_error ?? undefined,
    };
  } catch (e) {
    return err(e);
  }
}

// ---------- Destinations ----------

export type CreateDestinationResult =
  | { ok: true; id: string; oauthUrl?: string }
  | {
      ok: false;
      error: string;
      destinationCreated?: boolean;
      destinationId?: string;
      destinationName?: string;
    };

export async function actionCreateDestination(
  pipelineId: string,
  form: FormData,
): Promise<CreateDestinationResult> {
  try {
    const name = String(form.get("name") ?? "").trim();
    if (!name) return { ok: false, error: "Thiếu tên destination." };
    const dest = await createDestination(pipelineId, {
      platform: String(form.get("platform") ?? "youtube"),
      name,
      publish_strategy: String(form.get("publish_strategy") ?? "broadcast"),
      daily_upload_limit: Number(form.get("daily_upload_limit") ?? 6) || 6,
      timezone: String(form.get("timezone") ?? "UTC").trim() || "UTC",
      upload_slots: parseSlots(
        String(form.get("upload_slots") ?? "08:00,11:00,14:00,17:00,20:00,23:00"),
      ),
      metadata_language: String(form.get("metadata_language") ?? "").trim() || undefined,
      metadata_profile: String(form.get("metadata_profile") ?? "").trim() || undefined,
    });
    revalidatePipeline(pipelineId);
    // For YouTube, fetch the REAL OAuth URL right away so the wizard can
    // redirect immediately. NEVER swallow this error: the destination exists
    // but Google login cannot start, and the user must see why.
    if (dest.platform === "youtube") {
      try {
        const oauth = await getYoutubeOauthUrl(dest.id);
        if (!oauth.url) {
          return {
            ok: false,
            error: "Backend không trả YouTube OAuth URL.",
            destinationCreated: true,
            destinationId: dest.id,
            destinationName: dest.name,
          };
        }
        return { ok: true, id: dest.id, oauthUrl: oauth.url };
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Lỗi không xác định.";
        return {
          ok: false,
          error: `Không tạo được YouTube OAuth URL: ${msg}`,
          destinationCreated: true,
          destinationId: dest.id,
          destinationName: dest.name,
        };
      }
    }
    return { ok: true, id: dest.id };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, error: e.message };
    return { ok: false, error: e instanceof Error ? e.message : "Tạo destination thất bại." };
  }
}

export async function actionToggleDestination(
  pipelineId: string,
  id: string,
  enabled: boolean,
): Promise<ActionResult> {
  try {
    await updateDestination(id, { enabled });
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionUpdateDestination(
  pipelineId: string,
  id: string,
  form: FormData,
): Promise<ActionResult> {
  try {
    const payload: Record<string, unknown> = {};
    const name = String(form.get("name") ?? "").trim();
    if (name) payload.name = name;
    payload.daily_upload_limit = Number(form.get("daily_upload_limit") ?? 6) || 6;
    payload.timezone = String(form.get("timezone") ?? "UTC").trim() || "UTC";
    const slots = parseSlots(String(form.get("upload_slots") ?? ""));
    if (slots.length > 0) payload.upload_slots = slots;
    payload.publish_strategy = String(form.get("publish_strategy") ?? "broadcast");
    const lang = String(form.get("metadata_language") ?? "").trim();
    if (lang) payload.metadata_language = lang;
    const profile = String(form.get("metadata_profile") ?? "").trim();
    if (profile) payload.metadata_profile = profile;
    await updateDestination(id, payload);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionDeleteDestination(
  pipelineId: string,
  id: string,
): Promise<ActionResult> {
  try {
    await deleteDestination(id);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionGetOauthUrl(
  destinationId: string,
): Promise<ActionResult & { url?: string }> {
  try {
    const data = await getYoutubeOauthUrl(destinationId);
    return { ok: true, url: data.url };
  } catch (e) {
    const r = err(e);
    return { ...r, url: undefined };
  }
}

export async function actionGetDouyinSession(): Promise<
  ActionResult & {
    configured?: boolean;
    cookieConfigured?: boolean;
    anonymousAccess?: boolean | null;
    cookieRequired?: boolean | null;
    valid?: boolean;
    errorDetail?: string;
    lastValidation?: string | null;
  }
> {
  try {
    const { getDouyinSession } = await import("./api");
    const data = await getDouyinSession();
    const cookieRequired = (data as { cookie_required?: boolean | null }).cookie_required ?? null;
    const anonymousAccess = (data as { anonymous_access?: boolean | null }).anonymous_access ?? null;
    const cookieConfigured = (data as { cookie_configured?: boolean }).cookie_configured ?? data.configured;
    if (!data.valid) {
      // Cookies are optional: only a hard auth wall makes them required.
      if (!data.configured && cookieRequired !== true) {
        return {
          ok: true,
          configured: false,
          cookieConfigured: false,
          anonymousAccess,
          cookieRequired,
          valid: false,
          errorDetail: data.error ?? undefined,
          lastValidation: data.last_validation ?? null,
        };
      }
      return {
        ok: false,
        error: data.error || "Douyin session expired",
        configured: data.configured,
        cookieConfigured,
        anonymousAccess,
        cookieRequired,
        valid: false,
        errorDetail: data.error ?? undefined,
        lastValidation: data.last_validation ?? null,
      };
    }
    return {
      ok: true,
      configured: data.configured,
      cookieConfigured,
      anonymousAccess,
      cookieRequired,
      valid: true,
      lastValidation: data.last_validation ?? null,
    };
  } catch (e) {
    const r = err(e);
    return { ...r };
  }
}

// ---------- Publications ----------

export async function actionPublishNow(
  pipelineId: string,
  videoId: string,
  destinationId: string,
): Promise<ActionResult> {
  try {
    await publishNow(pipelineId, videoId, destinationId);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionRetryPublication(
  pipelineId: string,
  publicationId: string,
): Promise<ActionResult> {
  try {
    await retryPublication(publicationId);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionSkipPublication(
  pipelineId: string,
  publicationId: string,
): Promise<ActionResult> {
  try {
    await skipPublication(publicationId);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionReschedulePublication(
  pipelineId: string,
  publicationId: string,
  scheduledAt: string,
): Promise<ActionResult> {
  try {
    const iso = new Date(scheduledAt).toISOString();
    await reschedulePublication(publicationId, iso);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionRetryJob(
  pipelineId: string,
  jobId: string,
): Promise<ActionResult> {
  try {
    await retryJob(jobId);
    revalidatePipeline(pipelineId);
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionStartDouyinSession(): Promise<
  ActionResult & { sessionId?: string; qrImageB64?: string; expiresAt?: string | null }
> {
  try {
    const { startDouyinSession } = await import("./api");
    const data = await startDouyinSession();
    return {
      ok: true,
      sessionId: data.session_id,
      qrImageB64: data.qr_image_b64,
      expiresAt: data.expires_at ?? null,
    };
  } catch (e) {
    return err(e);
  }
}

export async function actionGetDouyinSessionFlow(
  sessionId: string,
): Promise<
  ActionResult & {
    status?: string;
    accountName?: string | null;
    errorDetail?: string;
    qrImageB64?: string | null;
  }
> {
  try {
    const { getDouyinSessionFlow } = await import("./api");
    const data = await getDouyinSessionFlow(sessionId);
    return {
      ok: true,
      status: data.status,
      accountName: data.account_name ?? null,
      errorDetail: data.error ?? undefined,
      qrImageB64: data.qr_image_b64 ?? null,
    };
  } catch (e) {
    return err(e);
  }
}

export async function actionGetDouyinSessionAggregate(): Promise<
  ActionResult & {
    connected?: boolean;
    valid?: boolean;
    accountName?: string | null;
    lastValidatedAt?: string | null;
  }
> {
  try {
    const { getDouyinSessionAggregate } = await import("./api");
    const data = await getDouyinSessionAggregate();
    return {
      ok: true,
      connected: data.connected,
      valid: data.valid,
      accountName: data.account_name ?? null,
      lastValidatedAt: data.last_validated_at ?? null,
    };
  } catch (e) {
    return err(e);
  }
}

export async function actionValidateDouyinSessionFull(): Promise<ActionResult> {
  try {
    const { validateDouyinSession } = await import("./api");
    const data = await validateDouyinSession();
    if (data.valid) return { ok: true };
    return { ok: false, error: data.error || "Douyin session expired" };
  } catch (e) {
    return err(e);
  }
}

export async function actionDisconnectDouyinSession(): Promise<ActionResult> {
  try {
    const { disconnectDouyinSession } = await import("./api");
    await disconnectDouyinSession();
    revalidatePath("/");
    return { ok: true };
  } catch (e) {
    return err(e);
  }
}

export async function actionLogout(): Promise<never> {  const { cookies } = await import("next/headers");
  const { SESSION_COOKIE } = await import("./session");
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  redirect("/login");
}
