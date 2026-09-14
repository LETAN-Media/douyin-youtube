import { SkeletonCard } from "@/components/ui";
import { Shell } from "@/components/Shell";

export default function Loading() {
  return (
    <Shell>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    </Shell>
  );
}
