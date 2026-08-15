import { useEffect, useState } from "react";

import { storageGet, storageSet } from "@/lib/storage";

// 默认呈现亮色（对齐对冲基金平台的亮色默认）；用户可切暗色，选择存 localStorage。
// 机制：暗色时给 <html> 加 .dark（亮色为 :root 默认态，无需类名）。
// key 用 v2：旧版本默认暗色时会把 vr-theme=dark 写入，换 key 让老偏好失效，直接落到新的亮色默认。
export function useDarkMode() {
  const [dark, setDark] = useState(() => {
    const saved = storageGet("vr-theme-v2");
    if (saved) return saved === "dark";
    return false; // 默认亮色
  });

  useEffect(() => {
    document.documentElement.classList.toggle("light", !dark);
    document.documentElement.classList.toggle("dark", dark);
    storageSet("vr-theme-v2", dark ? "dark" : "light");
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}
