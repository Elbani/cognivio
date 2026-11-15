import type { Memory, MemoryListItem, MemoryType } from "../lib/api";
import { MEMORY_TYPES, MEMORY_TYPE_LABELS } from "../lib/api";
import { NoteGraph } from "../NoteGraph";
import { TYPE_COLOR } from "./shared";

export function GraphView({
  memories,
  selectedId,
  onSelect
}: {
  memories: MemoryListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (memories.length === 0) {
    return <div className="ws-empty"><h2>Nothing to graph yet</h2><p>Create a few docs and link them with [[wiki links]].</p></div>;
  }
  return (
    <div className="ws-graphwrap">
      <div className="ws-legend">
        {MEMORY_TYPES.map((t) => (
          <span className="li" key={t}><span className="ty-dot" style={{ background: TYPE_COLOR[t as MemoryType] }} />{MEMORY_TYPE_LABELS[t]}</span>
        ))}
      </div>
      <NoteGraph notes={memories as unknown as Memory[]} selectedNoteId={selectedId} onSelectNote={onSelect} />
    </div>
  );
}
