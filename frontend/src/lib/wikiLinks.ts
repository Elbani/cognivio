import type { Memory } from "./api";

export function normalizeTitle(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

export function replaceWikiLinks(markdown: string, memories: Memory[]): string {
  const byTitle = new Map(memories.map((m) => [normalizeTitle(m.title), m.id]));

  return markdown.replace(/\[\[([^[\]]+)\]\]/g, (_match, title: string) => {
    const cleanedTitle = title.trim().replace(/\s+/g, " ");
    const memoryId = byTitle.get(normalizeTitle(cleanedTitle));
    if (!memoryId) {
      return `**${cleanedTitle}**`;
    }
    return `[${cleanedTitle}](/app?memory=${encodeURIComponent(memoryId)})`;
  });
}
