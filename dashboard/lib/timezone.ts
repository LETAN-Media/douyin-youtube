// Timezone helpers for schedule forms.
//
// The dashboard must never display a UTC instant as if it were local time, and
// must never send a bare local string that the server could misread. All
// conversions go through Intl with an explicit IANA timezone (zoneinfo-based
// in the backend), so Asia/Ho_Chi_Minh always means GMT+7 regardless of the
// viewer's device settings.

const formatterCache = new Map<string, Intl.DateTimeFormat>();

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function isValidTimeZone(timeZone: string): boolean {
  if (!timeZone) return false;
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone });
    return true;
  } catch {
    return false;
  }
}

function safeZone(timeZone: string): string {
  return isValidTimeZone(timeZone) ? timeZone : "UTC";
}

function partsFormatter(timeZone: string): Intl.DateTimeFormat {
  const zone = safeZone(timeZone);
  let formatter = formatterCache.get(zone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatterCache.set(zone, formatter);
  }
  return formatter;
}

export interface ZonedParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

export function zonedParts(date: Date, timeZone: string): ZonedParts {
  const parts = partsFormatter(timeZone).formatToParts(date);
  const read = (type: string) =>
    Number(parts.find((part) => part.type === type)?.value ?? "0");
  return {
    year: read("year"),
    month: read("month"),
    day: read("day"),
    // Some engines emit 24 for midnight with hourCycle h23.
    hour: read("hour") % 24,
    minute: read("minute"),
    second: read("second"),
  };
}

/** Offset of the given timezone at that instant, in minutes east of UTC. */
export function offsetMinutesAt(date: Date, timeZone: string): number {
  const p = zonedParts(date, timeZone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
}

/** "GMT+7" / "GMT-3:30" for the given instant and zone. */
export function gmtOffsetLabel(date: Date, timeZone: string): string {
  const minutes = offsetMinutesAt(date, timeZone);
  const sign = minutes >= 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  const hours = Math.floor(abs / 60);
  const rest = abs % 60;
  return `GMT${sign}${hours}${rest ? `:${pad(rest)}` : ""}`;
}

/** "Asia/Ho_Chi_Minh (GMT+7)" */
export function timezoneLabel(timeZone: string, at: Date = new Date()): string {
  const zone = safeZone(timeZone);
  return `${zone} (${gmtOffsetLabel(at, zone)})`;
}

/**
 * Local date + time in an explicit timezone -> UTC ISO 8601 instant.
 * Two passes handle DST boundaries without manual arithmetic.
 */
export function localDateTimeToUtcIso(
  date: string,
  time: string,
  timeZone: string,
): string {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  if (
    !year ||
    !month ||
    !day ||
    !Number.isFinite(hour) ||
    !Number.isFinite(minute)
  ) {
    throw new Error("Ngày hoặc giờ không hợp lệ.");
  }
  if (hour > 23 || minute > 59) throw new Error("Giờ không hợp lệ.");
  const zone = safeZone(timeZone);
  const naiveUtc = Date.UTC(year, month - 1, day, hour, minute, 0);
  let instant = naiveUtc - offsetMinutesAt(new Date(naiveUtc), zone) * 60000;
  instant = naiveUtc - offsetMinutesAt(new Date(instant), zone) * 60000;
  const result = new Date(instant);
  if (Number.isNaN(result.getTime())) throw new Error("Ngày giờ không hợp lệ.");
  return result.toISOString();
}

/** UTC ISO -> value for <input type="date"> / <input type="time"> in a zone. */
export function utcIsoToLocalInput(
  iso: string,
  timeZone: string,
): { date: string; time: string } {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return { date: "", time: "" };
  const p = zonedParts(parsed, timeZone);
  return {
    date: `${p.year}-${pad(p.month)}-${pad(p.day)}`,
    time: `${pad(p.hour)}:${pad(p.minute)}`,
  };
}

/** "20:30 — 02/11/2026 (GMT+7)" */
export function formatScheduleLabel(iso: string, timeZone: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  const p = zonedParts(parsed, timeZone);
  return `${pad(p.hour)}:${pad(p.minute)} — ${pad(p.day)}/${pad(p.month)}/${p.year} (${gmtOffsetLabel(
    parsed,
    timeZone,
  )})`;
}

/** Today's calendar date in the destination timezone (input min). */
export function todayInZone(timeZone: string): string {
  const p = zonedParts(new Date(), timeZone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}
