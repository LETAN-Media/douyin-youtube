import { proxyAudio } from "@/lib/audio-proxy";

export async function GET(request: Request) {
  const { search } = new URL(request.url);
  return proxyAudio(`/api/audio/pipelines${search}`);
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  return proxyAudio("/api/audio/pipelines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
