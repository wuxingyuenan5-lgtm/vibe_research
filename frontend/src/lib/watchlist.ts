// 注意：自选股（近期关注 focus）的唯一真源已收敛到后端 `data/stock-pool/focus.json`
// （经 /api/stock-pool/focus 读写 + 同步 GitHub），不再使用 localStorage 兜底。
// 本文件仅保留「代码解析」纯函数，供批量添加输入框使用。

// 从任意文本里抽取 6 位 A 股代码（逗号 / 空格 / 换行 / 顿号分隔都行，方便一次粘贴一串）。
export function parseCodes(raw: string): string[] {
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return Array.from(new Set(tokens.filter((t) => /^\d{6}$/.test(t))));
}

// 把用户输入的一串代码并入已有自选，返回去重后的新列表 + 实际新增数量。
export function addCodes(existing: string[], raw: string): { next: string[]; added: number } {
  const incoming = parseCodes(raw).filter((c) => !existing.includes(c));
  return { next: [...existing, ...incoming], added: incoming.length };
}
