/**
 * Resolve a YouTube channel avatar URL server-side.
 *
 * YouTube has no keyless avatar API, so we read the channel page's
 * og:image (which *is* the channel avatar). Short in-memory TTL cache,
 * small timeout, null on any failure — callers always fall back to an
 * initial-letter avatar. Server-only: never import from client components.
 */

const CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const cache = new Map<string, { url: string | null; at: number }>();

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

function extractOgImage(html: string): string | null {
  const m =
    html.match(/<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']/i) ||
    html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image["']/i);
  const url = m?.[1]?.trim();
  if (!url || !/^https:\/\//.test(url)) return null;
  return url;
}

export async function getChannelAvatarUrl(channelId: string | null | undefined): Promise<string | null> {
  const id = (channelId || "").trim();
  if (!id) return null;
  const hit = cache.get(id);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) return hit.url;
  let url: string | null = null;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await fetch(`https://www.youtube.com/channel/${encodeURIComponent(id)}`, {
        headers: { "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9" },
        signal: ctrl.signal,
        cache: "no-store",
      });
      if (res.ok) {
        const html = await res.text();
        url = extractOgImage(html);
      }
    } finally {
      clearTimeout(timer);
    }
  } catch {
    url = null;
  }
  cache.set(id, { url, at: Date.now() });
  return url;
}
