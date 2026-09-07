import { apiRequest } from "@/lib/api";

export interface Note {
  id: string;
  kind: string;
  title: string;
  content: string;
  ts: number;
}

const LEGACY_KEY = "vr-notes";

export async function loadNotes(): Promise<Note[]> {
  const remote = await apiRequest<Note[]>("/notes");
  let legacy: Note[] = [];
  try {
    const parsed = JSON.parse(localStorage.getItem(LEGACY_KEY) || "[]");
    legacy = Array.isArray(parsed) ? parsed : [];
  } catch {
    legacy = [];
  }
  if (!legacy.length) return remote;
  for (const note of legacy) {
    await apiRequest<Note>("/notes", "POST", note);
  }
  localStorage.removeItem(LEGACY_KEY);
  return apiRequest<Note[]>("/notes");
}

export function addNote(kind: string, title: string, content: string): Promise<Note> {
  return apiRequest<Note>("/notes", "POST", { kind, title, content });
}

export async function deleteNote(id: string): Promise<void> {
  await apiRequest(`/notes/${encodeURIComponent(id)}`, "DELETE");
}

export async function clearNotes(): Promise<void> {
  await apiRequest("/notes", "DELETE");
}
