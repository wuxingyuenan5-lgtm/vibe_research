import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Quote } from "@/lib/api";

export const LIVE_INTERVAL_MS = 3000;   // A 股 level-1 快照粒度
const MAX_BACKOFF_MS = 30_000;

function beijingNow(): Date {
  const d = new Date();
  return new Date(d.getTime() + d.getTimezoneOffset() * 60_000 + 8 * 3600_000);
}

export function isTradingHours(): boolean {
  const bj = beijingNow();
  const day = bj.getDay();
  if (day === 0 || day === 6) return false;
  const mins = bj.getHours() * 60 + bj.getMinutes();
  return (mins >= 9 * 60 + 15 && mins <= 11 * 60 + 30) || (mins >= 13 * 60 && mins <= 15 * 60);
}

export interface LiveQuotesState {
  quotes: Record<string, Quote>;
  loading: boolean;
  /** 上次成功取到数据的时间戳（ms），从未成功则为 null */
  updatedAt: number | null;
  /** 轮询是否真的在跑（开关开着 ≠ 在跑：非交易时段 / 页面切走都会暂停） */
  polling: boolean;
  error: string | null;
  /** 手动刷新（任何时候都可用，不受交易时段限制） */
  refresh: () => void;
}

export function useLiveQuotes(codes: string[], enabled: boolean): LiveQuotesState {
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 用 ref 存最新的 codes，让轮询循环不必因为 codes 变化而重建
  const codesRef = useRef(codes);
  codesRef.current = codes;

  const failuresRef = useRef(0);
  const inFlightRef = useRef(false);
  const staleRef = useRef(false);          // 请求飞行途中自选变过 / 有请求被跳过
  const fetchRef = useRef<(() => Promise<boolean>) | null>(null);

  const fetchOnce = useCallback(async (): Promise<boolean> => {
    const cs = codesRef.current;
    if (!cs.length) {
      setQuotes({});
      return true;
    }
    if (inFlightRef.current) {
      // 上一次还没回来，跳过这一拍；但要记下来，等它回来后补拉一次。
      // 否则「首次请求在飞 → 用户此时粘贴新代码」会让新代码的行情永远缺失
      // （默认不开轮询时没有下一拍来兜底，只能手动刷新）。
      staleRef.current = true;
      return true;
    }
    inFlightRef.current = true;
    const requested = cs.join(",");
    setLoading(true);
    try {
      const data = await api.quote(requested);
      setQuotes(data);
      setUpdatedAt(Date.now());
      setError(null);
      failuresRef.current = 0;
      return true;
    } catch {
      failuresRef.current += 1;
      // 第一次失败先不打扰用户（可能只是一次网络抖动），连续失败才提示
      if (failuresRef.current >= 2) setError("行情获取失败，正在重试…");
      return false;
    } finally {
      inFlightRef.current = false;
      setLoading(false);
      // 这一趟拉的是不是已经过期的名单？过期就立刻补一次（只补一次，不会滚雪球：
      // 补拉时 staleRef 已复位，只有再次发生变动才会再补）。
      const changed = codesRef.current.join(",") !== requested;
      if (staleRef.current || changed) {
        staleRef.current = false;
        void fetchRef.current?.();
      }
    }
  }, []);
  fetchRef.current = fetchOnce;

  const refresh = useCallback(() => {
    void fetchOnce();
  }, [fetchOnce]);

  // 首次进入 / 自选变化：立即拉一次（与开关无关，页面总要有数据）
  useEffect(() => {
    void fetchOnce();
  }, [codes, fetchOnce]);

  // 轮询循环
  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const clear = () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };

    const shouldRun = () => enabled && !document.hidden && isTradingHours() && codesRef.current.length > 0;

    const loop = async () => {
      if (cancelled) return;
      if (!shouldRun()) {
        setPolling(false);
        // 没在跑也要保持一个心跳，好在开盘 / 页面切回来时自动恢复
        timer = window.setTimeout(loop, 10_000);
        return;
      }
      setPolling(true);
      const ok = await fetchOnce();
      if (cancelled) return;          // 请求期间被卸载/切换：到此为止，别再排下一拍
      const wait = ok
        ? LIVE_INTERVAL_MS
        : Math.min(LIVE_INTERVAL_MS * 2 ** failuresRef.current, MAX_BACKOFF_MS);
      timer = window.setTimeout(loop, wait);
    };

    if (enabled) {
      void loop();
    } else {
      setPolling(false);
    }

    // 页面切回来时立刻重新评估，不用等下一拍
    const onVisible = () => {
      if (!document.hidden && enabled && !cancelled) {
        clear();
        void loop();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      clear();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, fetchOnce]);

  return { quotes, loading, updatedAt, polling, error, refresh };
}
