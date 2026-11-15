import type { MemoryType } from "../lib/api";

export const TYPE_COLOR: Record<MemoryType, string> = {
  map: "#8b5cf6",
  architecture: "#0ea5e9",
  playbook: "#10b981",
  incident: "#ef4444",
  decision: "#f59e0b",
  lesson: "#ec4899",
  note: "#9ca3af"
};

export const TYPE_GLYPH: Record<MemoryType, string> = {
  map: "◆",
  architecture: "▤",
  playbook: "▶",
  incident: "▲",
  decision: "◇",
  lesson: "✦",
  note: "•"
};

const DAY = 86400000;
export const STALE_DAYS = 90;

// API timestamps are UTC but are often serialized without a timezone marker.
// A marker-less ISO string is parsed as LOCAL time by browsers, which skews every
// "X ago" by the viewer's UTC offset, so treat a marker-less string as UTC.
function parseTs(iso: string): number {
  const hasTz = /([zZ]|[+-]\d\d:?\d\d)$/.test(iso);
  return new Date(hasTz ? iso : iso + "Z").getTime();
}

export function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - parseTs(iso)) / DAY);
}

export function freshness(iso: string | null | undefined): {
  label: string;
  stale: boolean;
  days: number | null;
} {
  const days = daysSince(iso);
  if (days === null) return { label: "never verified", stale: true, days: null };
  if (days <= 0) return { label: "verified today", stale: false, days };
  if (days === 1) return { label: "verified yesterday", stale: false, days };
  if (days < 30) return { label: `verified ${days}d ago`, stale: days > STALE_DAYS, days };
  if (days < 365) return { label: `verified ${Math.floor(days / 30)}mo ago`, stale: days > STALE_DAYS, days };
  return { label: `verified ${Math.floor(days / 365)}y ago`, stale: true, days };
}

export function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - parseTs(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const ACTION_LABEL: Record<string, string> = {
  "context.pack": "primed context",
  "map.read": "read the map",
  "memory.search": "searched memories",
  "memory.read": "read a memory",
  "memory.create": "wrote a memory",
  "memory.update": "updated a memory",
  "memory.delete": "deleted a memory",
  "memory.feedback": "rated a memory"
};
