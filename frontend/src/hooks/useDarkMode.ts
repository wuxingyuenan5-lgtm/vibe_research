import { useEffect, useState } from "react";

import { storageGet, storageSet } from "@/lib/storage";

// 默认呈现深夜蓝金主题（对齐 Platform_Experiment 落地页的夜空质感）；用户可切暖纸亮色，选择存 localStorage。
// 机制：暗色时给 <html> 加 .dark（:root 令牌即深夜蓝，.dark 无覆盖、保持一致）；亮色加 .light（暖纸变体）。
// key 用 v3：v2 及之前默认亮色会写入 vr-theme-v2=light，换 key 让老偏好失效，直接落到新的深夜蓝默认。
export function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const saved = storageGet("vr-theme-v3");
    if (saved) return saved === "dark";
    return true; // 默认深夜蓝
  });

  useEffect(() => {
    document.documentElement.classList.toggle("light", !dark);
    document.documentElement.classList.toggle("dark", dark);
    storageSet("vr-theme-v3", dark ? "dark" : "light");
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}
