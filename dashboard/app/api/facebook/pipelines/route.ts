import { NextResponse } from "next/server";
import { createFacebookPipeline } from "@/lib/facebook-api";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const result = await createFacebookPipeline(body);
    return NextResponse.json(result);
  } catch (err: any) {
    return NextResponse.json(
      { error: err.message || "Failed to create pipeline" },
      { status: err.status || 500 }
    );
  }
}
