export type Why = { by: "meaning" | "all" | "near" | "any"; rank: number; sim?: number };
export type Result = {
  id: string; name: string; kind: string; status: string; folder: string;
  title: string; description: string; tags: string[]; textInImage: string; sensitive: boolean;
  url: string; folderUrl: string; thumb: string; score: number; why: Why[];
};
export type IndexInfo = {
  path: string; rootId: string; listedAt: string; files: number; described: number; vectors: number;
  lockedFolders: string[]; kinds: Record<string, number>;
};
export type ModelState = { state: "idle" | "loading" | "ready" | "error"; progress: number; error: string };

declare global {
  interface Window {
    lens: {
      info(): Promise<IndexInfo | null>;
      chooseIndex(): Promise<{ ok: boolean; info?: IndexInfo; error?: string; canceled?: boolean }>;
      modelStatus(): Promise<ModelState>;
      onModel(fn: (m: ModelState) => void): () => void;
      search(q: string, opts?: { k?: number; kind?: string }): Promise<{ ok: boolean; results?: Result[]; error?: string }>;
      open(url: string): Promise<void>;
    };
  }
}
