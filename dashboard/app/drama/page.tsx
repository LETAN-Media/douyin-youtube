import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/ui";
import { DRAMA_MOCK } from "@/lib/drama-mock";
import { DramaLibraryClient } from "./DramaLibraryClient";

export default function DramaPage() {
  return (
    <Shell>
      <PageHeader title="Drama" description="Quản lý và xử lý phim ngắn" />
      <DramaLibraryClient series={DRAMA_MOCK} />
    </Shell>
  );
}
