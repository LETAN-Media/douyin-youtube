export interface DramaSeries {
  seriesId: string;
  title: string;
  episodeCount: number;
  genre: string;
}

export interface DramaEpisode {
  episodeId: string;
  episodeNumber: number;
  title: string;
  duration: string;
  status: "ready" | "processing" | "error" | "published";
}

export const DRAMA_MOCK: DramaSeries[] = [
  { seriesId: "6a469b12d3f5c65f7f095b8a", title: "You've Been Replaced, First Love", episodeCount: 73, genre: "Romance" },
  { seriesId: "67773dcf3d3252065f0e5651", title: "Love Me Two Times", episodeCount: 52, genre: "Romance" },
  { seriesId: "69d91b111840476dfa0eba40", title: "Hate to Love You", episodeCount: 68, genre: "Melodrama" },
  { seriesId: "6a699568fb5bf17ebc05c95f", title: "Love You 1,000 Years", episodeCount: 82, genre: "Fantasy" },
  { seriesId: "6a880a1758adcf20550a8502", title: "My Protective Mafia Lover", episodeCount: 49, genre: "Mafia" },
  { seriesId: "67565449d20d47d9fa082eb4", title: "Love Me Before I Go", episodeCount: 85, genre: "Drama" },
];

export function getDramaSeries(seriesId: string): DramaSeries | undefined {
  return DRAMA_MOCK.find((s) => s.seriesId === seriesId);
}

export function getMockEpisodes(seriesId: string): DramaEpisode[] {
  const series = getDramaSeries(seriesId);
  if (!series) return [];
  const statuses: DramaEpisode["status"][] = ["ready", "ready", "ready", "ready", "processing", "published", "error"];
  const prefix = series.title.split(" ").slice(0, 3).join(" ");
  return Array.from({ length: Math.min(series.episodeCount, 24) }).map((_, idx) => {
    const num = idx + 1;
    const status = statuses[idx % statuses.length];
    return {
      episodeId: `${seriesId}-ep-${num}`,
      episodeNumber: num,
      title: `${prefix} - Tập ${num}`,
      duration: status === "ready" || status === "published" ? "3:42" : status === "processing" ? "Đang xử lý…" : "Lỗi",
      status,
    };
  });
}
