import { proxyAudio } from "@/lib/audio-proxy";

export async function GET() {
  return proxyAudio("/api/audio/pipelines");
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  return proxyAudio("/api/audio/pipelines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
