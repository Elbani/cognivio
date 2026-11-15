import { RefObject } from "react";

type EditorRef = RefObject<HTMLTextAreaElement | null>;

function getSelection(el: HTMLTextAreaElement) {
  return { start: el.selectionStart, end: el.selectionEnd };
}

function applyEdit(
  el: HTMLTextAreaElement,
  content: string,
  setContent: (v: string) => void,
  newValue: string,
  cursorStart: number,
  cursorEnd?: number
) {
  setContent(newValue);
  requestAnimationFrame(() => {
    el.focus();
    el.setSelectionRange(cursorStart, cursorEnd ?? cursorStart);
  });
}

function wrapSelection(
  ref: EditorRef,
  content: string,
  setContent: (v: string) => void,
  before: string,
  after: string
) {
  const el = ref.current;
  if (!el) return;
  const { start, end } = getSelection(el);
  const selected = content.substring(start, end);
  const wrapped = selected.startsWith(before) && selected.endsWith(after);

  if (wrapped && selected.length >= before.length + after.length) {
    const unwrapped = selected.slice(before.length, -after.length || undefined);
    const newValue = content.substring(0, start) + unwrapped + content.substring(end);
    applyEdit(el, content, setContent, newValue, start, start + unwrapped.length);
  } else {
    const newValue = content.substring(0, start) + before + selected + after + content.substring(end);
    applyEdit(el, content, setContent, newValue, start + before.length, start + before.length + selected.length);
  }
}

function prependLine(
  ref: EditorRef,
  content: string,
  setContent: (v: string) => void,
  prefix: string
) {
  const el = ref.current;
  if (!el) return;
  const { start, end } = getSelection(el);
  const lineStart = content.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = content.indexOf("\n", end);
  const blockEnd = lineEnd === -1 ? content.length : lineEnd;
  const block = content.substring(lineStart, blockEnd);

  const lines = block.split("\n");
  const allPrefixed = lines.every((l) => l.startsWith(prefix));
  const transformed = allPrefixed
    ? lines.map((l) => l.slice(prefix.length)).join("\n")
    : lines.map((l) => prefix + l).join("\n");

  const newValue = content.substring(0, lineStart) + transformed + content.substring(blockEnd);
  applyEdit(el, content, setContent, newValue, lineStart, lineStart + transformed.length);
}

export function toggleBold(ref: EditorRef, content: string, setContent: (v: string) => void) {
  wrapSelection(ref, content, setContent, "**", "**");
}

export function toggleItalic(ref: EditorRef, content: string, setContent: (v: string) => void) {
  wrapSelection(ref, content, setContent, "_", "_");
}

export function toggleStrikethrough(ref: EditorRef, content: string, setContent: (v: string) => void) {
  wrapSelection(ref, content, setContent, "~~", "~~");
}

export function toggleInlineCode(ref: EditorRef, content: string, setContent: (v: string) => void) {
  wrapSelection(ref, content, setContent, "`", "`");
}

export function insertCodeBlock(ref: EditorRef, content: string, setContent: (v: string) => void) {
  wrapSelection(ref, content, setContent, "```\n", "\n```");
}

export function toggleHeading(ref: EditorRef, content: string, setContent: (v: string) => void) {
  const el = ref.current;
  if (!el) return;
  const { start } = getSelection(el);
  const lineStart = content.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = content.indexOf("\n", start);
  const end = lineEnd === -1 ? content.length : lineEnd;
  const line = content.substring(lineStart, end);

  const match = line.match(/^(#{1,6})\s/);
  let newLine: string;
  if (!match) {
    newLine = "## " + line;
  } else if (match[1].length >= 4) {
    newLine = line.slice(match[0].length);
  } else {
    newLine = "#" + line;
  }
  const newValue = content.substring(0, lineStart) + newLine + content.substring(end);
  applyEdit(el, content, setContent, newValue, lineStart + newLine.length);
}

export function toggleBulletList(ref: EditorRef, content: string, setContent: (v: string) => void) {
  prependLine(ref, content, setContent, "- ");
}

export function toggleOrderedList(ref: EditorRef, content: string, setContent: (v: string) => void) {
  prependLine(ref, content, setContent, "1. ");
}

export function toggleBlockquote(ref: EditorRef, content: string, setContent: (v: string) => void) {
  prependLine(ref, content, setContent, "> ");
}

export function insertLink(ref: EditorRef, content: string, setContent: (v: string) => void) {
  const el = ref.current;
  if (!el) return;
  const { start, end } = getSelection(el);
  const selected = content.substring(start, end);
  const isUrl = /^https?:\/\//.test(selected);

  if (isUrl) {
    const newValue = content.substring(0, start) + `[](${selected})` + content.substring(end);
    applyEdit(el, content, setContent, newValue, start + 1);
  } else {
    const text = selected || "link text";
    const newValue = content.substring(0, start) + `[${text}](url)` + content.substring(end);
    applyEdit(el, content, setContent, newValue, start + text.length + 3, start + text.length + 6);
  }
}

export function insertHr(ref: EditorRef, content: string, setContent: (v: string) => void) {
  const el = ref.current;
  if (!el) return;
  const { end } = getSelection(el);
  const before = content.substring(0, end);
  const after = content.substring(end);
  const needsNewline = before.length > 0 && !before.endsWith("\n");
  const insert = (needsNewline ? "\n" : "") + "\n---\n\n";
  const newValue = before + insert + after;
  applyEdit(el, content, setContent, newValue, before.length + insert.length);
}

export function handleEditorKeyDown(
  event: React.KeyboardEvent<HTMLTextAreaElement>,
  content: string,
  setContent: (v: string) => void,
  ref: EditorRef
) {
  const el = event.currentTarget;
  const mod = event.metaKey || event.ctrlKey;

  if (mod && event.key === "b") {
    event.preventDefault();
    toggleBold(ref, content, setContent);
    return true;
  }
  if (mod && event.key === "i") {
    event.preventDefault();
    toggleItalic(ref, content, setContent);
    return true;
  }
  if (mod && event.key === "e") {
    event.preventDefault();
    toggleInlineCode(ref, content, setContent);
    return true;
  }
  if (mod && event.shiftKey && event.key === "x") {
    event.preventDefault();
    toggleStrikethrough(ref, content, setContent);
    return true;
  }
  if (mod && event.key === "k") {
    event.preventDefault();
    insertLink(ref, content, setContent);
    return true;
  }

  if (event.key === "Tab") {
    event.preventDefault();
    const { start, end } = getSelection(el);
    if (event.shiftKey) {
      const lineStart = content.lastIndexOf("\n", start - 1) + 1;
      if (content.substring(lineStart, lineStart + 2) === "  ") {
        const newValue = content.substring(0, lineStart) + content.substring(lineStart + 2);
        setContent(newValue);
        requestAnimationFrame(() => {
          el.focus();
          el.setSelectionRange(Math.max(start - 2, lineStart), Math.max(end - 2, lineStart));
        });
      }
    } else {
      const newValue = content.substring(0, start) + "  " + content.substring(end);
      setContent(newValue);
      requestAnimationFrame(() => {
        el.focus();
        el.setSelectionRange(start + 2, start + 2);
      });
    }
    return true;
  }

  if (event.key === "Enter" && !mod && !event.shiftKey) {
    const { start } = getSelection(el);
    const lineStart = content.lastIndexOf("\n", start - 1) + 1;
    const line = content.substring(lineStart, start);

    const bullet = line.match(/^(\s*[-*+]\s)/);
    if (bullet) {
      if (line.trim() === "-" || line.trim() === "*" || line.trim() === "+") {
        event.preventDefault();
        const newValue = content.substring(0, lineStart) + "\n" + content.substring(start);
        setContent(newValue);
        requestAnimationFrame(() => {
          el.focus();
          el.setSelectionRange(lineStart + 1, lineStart + 1);
        });
        return true;
      }
      event.preventDefault();
      const insert = "\n" + bullet[1];
      const newValue = content.substring(0, start) + insert + content.substring(start);
      setContent(newValue);
      const pos = start + insert.length;
      requestAnimationFrame(() => {
        el.focus();
        el.setSelectionRange(pos, pos);
      });
      return true;
    }

    const ordered = line.match(/^(\s*)(\d+)\.\s/);
    if (ordered) {
      if (line.trim().match(/^\d+\.\s*$/)) {
        event.preventDefault();
        const newValue = content.substring(0, lineStart) + "\n" + content.substring(start);
        setContent(newValue);
        requestAnimationFrame(() => {
          el.focus();
          el.setSelectionRange(lineStart + 1, lineStart + 1);
        });
        return true;
      }
      event.preventDefault();
      const next = parseInt(ordered[2], 10) + 1;
      const insert = `\n${ordered[1]}${next}. `;
      const newValue = content.substring(0, start) + insert + content.substring(start);
      setContent(newValue);
      const pos = start + insert.length;
      requestAnimationFrame(() => {
        el.focus();
        el.setSelectionRange(pos, pos);
      });
      return true;
    }

    const quote = line.match(/^(\s*>\s)/);
    if (quote) {
      if (line.trim() === ">") {
        event.preventDefault();
        const newValue = content.substring(0, lineStart) + "\n" + content.substring(start);
        setContent(newValue);
        requestAnimationFrame(() => {
          el.focus();
          el.setSelectionRange(lineStart + 1, lineStart + 1);
        });
        return true;
      }
      event.preventDefault();
      const insert = "\n" + quote[1];
      const newValue = content.substring(0, start) + insert + content.substring(start);
      setContent(newValue);
      const pos = start + insert.length;
      requestAnimationFrame(() => {
        el.focus();
        el.setSelectionRange(pos, pos);
      });
      return true;
    }
  }

  return false;
}

export function getWordCount(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean);
  return words.length;
}

export function getCharCount(text: string): number {
  return text.length;
}
