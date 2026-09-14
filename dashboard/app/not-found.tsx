import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Card } from "@/components/ui";

export default function NotFound() {
  return (
    <Shell>
      <Card className="p-8 text-center">
        <p className="text-lg font-bold text-slate-900">Không tìm thấy trang</p>
        <Link href="/" className="mt-3 inline-block text-sm font-semibold text-indigo-600">
          ← Về Dashboard
        </Link>
      </Card>
    </Shell>
  );
}
