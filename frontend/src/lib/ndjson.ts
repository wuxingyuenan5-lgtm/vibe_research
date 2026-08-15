import { ApiError, authHeaders } from "@/lib/api";

export type NdjsonEvent = Record<string, any>;

export async function streamNdjson(
  url: string,
  body: unknown,
  onEvent: (ev: NdjsonEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }

  if (!resp.ok) {
    let detail: any = null;
    try { detail = await resp.json(); } catch { /* 无 JSON body 就用状态码兜底 */ }
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(detail?.detail || `HTTP ${resp.status}`, resp.status);
  }
  if (!resp.body) throw new ApiError("后端无响应流", 502);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";   // 末尾可能是半行，留到下一块
    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      try { onEvent(JSON.parse(t)); } catch { /* 半截行或脏行，跳过 */ }
    }
  }
}
