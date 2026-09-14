export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function slugify(input: string): string {
  return input
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)+/g, "")
    .slice(0, 80);
}

export function parseSlots(input: string): string[] {
  return input
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => /^([01]?\d|2[0-3]):[0-5]\d$/.test(s));
}

export function platformLabel(platform: string): string {
  const p = platform.toLowerCase();
  if (p === "youtube") return "YouTube";
  if (p === "facebook") return "Facebook";
  return platform;
}

export function publicationLabel(status: string): {
  text: string;
  tone: "green" | "amber" | "red" | "slate" | "blue";
} {
  switch (status) {
    case "published":
      return { text: "Published", tone: "green" };
    case "scheduled":
      return { text: "Scheduled", tone: "blue" };
    case "queued":
      return { text: "Waiting", tone: "amber" };
    case "failed":
      return { text: "Failed", tone: "red" };
    case "skipped":
      return { text: "Skipped", tone: "slate" };
    default:
      return { text: status, tone: "slate" };
  }
}
