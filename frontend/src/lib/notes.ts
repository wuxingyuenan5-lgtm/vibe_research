import { storageSet, storageRemove } from "@/lib/storage";

export interface Note {
  id: string;
  kind: string;   // 复盘 / 今日要点 / 问AI
  title: string;  // 如「每日复盘 2026-07-04」「AI 算力 今日要点」「问 AI · 600519」
  content: string; // markdown 正文
  ts: number;      // 保存时间戳(ms)
}

const KEY = "vr-notes";
const MAX = 200;

export function loadNotes(): Note[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function persist(notes: Note[]) {
  storageSet(KEY, JSON.stringify(notes.slice(0, MAX)));
}

// 新记录置顶。返回更新后的完整列表。
export function addNote(kind: string, title: string, content: string): Note[] {
  const note: Note = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    kind,
    title,
    content,
    ts: Date.now(),
  };
  const next = [note, ...loadNotes()];
  persist(next);
  return next;
}

export function deleteNote(id: string): Note[] {
  const next = loadNotes().filter((n) => n.id !== id);
  persist(next);
  return next;
}

export function clearNotes() {
  storageRemove(KEY);
}
