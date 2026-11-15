import {
  ChangeEvent,
  KeyboardEvent,
  RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from "react";
import type { Memory } from "./lib/api";

type SuggestState = {
  open: boolean;
  query: string;
  startIndex: number;
};

const CLOSED: SuggestState = { open: false, query: "", startIndex: 0 };

function getCaretCoords(textarea: HTMLTextAreaElement): { top: number; left: number } {
  const mirror = document.createElement("div");
  const style = window.getComputedStyle(textarea);
  const props = [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "letterSpacing",
    "lineHeight",
    "padding",
    "border",
    "whiteSpace",
    "wordWrap",
    "overflowWrap",
    "tabSize",
    "textIndent"
  ] as const;
  for (const prop of props) {
    (mirror.style as unknown as Record<string, string>)[prop] = style[prop];
  }
  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.wordWrap = "break-word";
  mirror.style.overflow = "hidden";
  mirror.style.width = `${textarea.clientWidth}px`;
  mirror.style.height = "auto";

  const text = textarea.value.substring(0, textarea.selectionEnd);
  const textNode = document.createTextNode(text);
  const marker = document.createElement("span");
  marker.textContent = "\u200b";
  mirror.appendChild(textNode);
  mirror.appendChild(marker);
  document.body.appendChild(mirror);

  const rect = textarea.getBoundingClientRect();
  const markerRect = marker.getBoundingClientRect();
  const mirrorRect = mirror.getBoundingClientRect();

  const top = rect.top + (markerRect.top - mirrorRect.top) - textarea.scrollTop;
  const left = rect.left + (markerRect.left - mirrorRect.left) - textarea.scrollLeft;

  document.body.removeChild(mirror);
  return { top, left };
}

export function useWikiLinkSuggest(
  notes: Memory[],
  content: string,
  setContent: (value: string) => void,
  textareaRef: RefObject<HTMLTextAreaElement | null>,
  disabled?: boolean
) {
  const [suggest, setSuggest] = useState<SuggestState>(CLOSED);
  const [activeIndex, setActiveIndex] = useState(0);
  const [position, setPosition] = useState<{ top: number; left: number }>({ top: 0, left: 0 });

  const filtered = useMemo(() => {
    if (!suggest.open) return [];
    const q = suggest.query.toLowerCase();
    return notes
      .filter((n) => !n.deletedAt && n.title.toLowerCase().includes(q))
      .slice(0, 12);
  }, [suggest, notes]);

  useEffect(() => {
    setActiveIndex(0);
  }, [filtered]);

  const updatePosition = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta || !suggest.open) return;
    setPosition(getCaretCoords(ta));
  }, [suggest.open, textareaRef]);

  useLayoutEffect(updatePosition, [updatePosition, content]);

  function detect(event: ChangeEvent<HTMLTextAreaElement>) {
    if (disabled) return;
    const el = event.target;
    const value = el.value;
    const cursor = el.selectionEnd;

    const before = value.substring(0, cursor);
    const openBracket = before.lastIndexOf("[[");
    if (openBracket === -1) {
      if (suggest.open) setSuggest(CLOSED);
      return;
    }
    const afterBracket = before.substring(openBracket + 2);
    if (afterBracket.includes("]]") || afterBracket.includes("\n")) {
      if (suggest.open) setSuggest(CLOSED);
      return;
    }
    setSuggest({ open: true, query: afterBracket, startIndex: openBracket });
  }

  function pick(note: Memory) {
    const ta = textareaRef.current;
    if (!ta) return;
    const cursor = ta.selectionEnd;
    const before = content.substring(0, suggest.startIndex);
    const after = content.substring(cursor);
    const inserted = `[[${note.title}]]`;
    const newContent = before + inserted + after;
    setContent(newContent);
    setSuggest(CLOSED);

    requestAnimationFrame(() => {
      const pos = before.length + inserted.length;
      ta.focus();
      ta.setSelectionRange(pos, pos);
    });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!suggest.open || filtered.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => (i + 1) % filtered.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => (i - 1 + filtered.length) % filtered.length);
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      pick(filtered[activeIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setSuggest(CLOSED);
    }
  }

  function close() {
    setSuggest(CLOSED);
  }

  return { suggest, filtered, activeIndex, position, detect, handleKeyDown, pick, close };
}

export function WikiLinkDropdown({
  filtered,
  activeIndex,
  position,
  onPick,
  onClose
}: {
  filtered: Memory[];
  activeIndex: number;
  position: { top: number; left: number };
  onPick: (note: Memory) => void;
  onClose: () => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>("[data-active]");
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  useEffect(() => {
    function handleClick(event: globalThis.MouseEvent) {
      if (listRef.current && !listRef.current.contains(event.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  if (filtered.length === 0) return null;

  return (
    <div
      ref={listRef}
      className="wikilink-dropdown"
      style={{ top: position.top + 24, left: position.left }}
      role="listbox"
    >
      {filtered.map((note, i) => (
        <button
          key={note.id}
          type="button"
          className={`wikilink-option${i === activeIndex ? " active" : ""}`}
          role="option"
          aria-selected={i === activeIndex}
          data-active={i === activeIndex ? "" : undefined}
          onMouseDown={(e) => {
            e.preventDefault();
            onPick(note);
          }}
          onMouseEnter={() => {}}
        >
          <span className="wikilink-option-title">{note.title}</span>
          {note.tags.length > 0 && (
            <span className="wikilink-option-tags">
              {note.tags.map((t) => `#${t}`).join(" ")}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
