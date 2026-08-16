import { type ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="flex items-start gap-3">
        {/* 标题左侧渐变刻度条 */}
        <span className="mt-1.5 h-7 w-1 shrink-0 rounded-full bg-gradient-to-b from-primary to-accent" />
        <div>
          <h1 className="font-serif text-[24px] font-bold leading-tight tracking-wide">{title}</h1>
          {subtitle && <p className="mt-1 text-[13px] text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
