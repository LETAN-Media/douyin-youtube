"use client";

import { useRouter } from "next/navigation";
import { btnPrimary } from "@/components/ui";

export function TikTokRetryButton({ className }: { className?: string }) {
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() => router.refresh()}
      className={className || btnPrimary}
    >
      Thử lại
    </button>
  );
}
