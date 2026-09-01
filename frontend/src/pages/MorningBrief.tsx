import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import "./morning-brief.css";

/* ============================================================
   统一交易晨报 —— 高保真复刻《统一交易晨报_2026-08-14.html》
   数据：冻结 payload（/api/morning-brief?date=）→ Dashboard 渲染
   支持：全部 / 概览 / 研究 阅读模式；HTML / PDF 下载；日期参数
   ============================================================ */

interface Payload {
  report_meta: {
    report_name: string; report_date: string; report_cutoff: string; timezone: string;
    china_market_date: string; global_market_date: string; a_share_analysis_status: string; headline: string;
  };
  summary: {
    kicker: string; overnight_title: string;
    overnight_changes: { title: string; text: string }[];
    china_title: string; china_changes: { title: string; text: string }[];
    priority_card: { label: string; title: string; note: string };
    priorities: { head: string; text: string }[];
  };
  asset_overview: { kicker: string; rows: { market: string; asset: string; value: string; change: string; cls: string; time: string; meaning: string }[] };
  overnight_drivers: { kicker: string; items: { label: string; title: string; note: string }[] };
  china_market: {
    title: string; kicker: string; analysis_status: string; priority: string; warning: string;
    switch: { label: string; metric: string; cls: string; note: string }[];
    breadth: { title: string; up: string; down: string; up_pct: number; down_pct: number; note: string };
    industry: { title: string; up: string; down: string; up_pct: number; down_pct: number; note: string };
  };
  mainlines: { kicker: string; items: { tags: string[]; title: string; paras: string[]; evidence: string; validation: string }[] };
  today_validation: { kicker: string; rows: { subject: string; question: string; look: string; meaning: string }[] };
  previous_review: { kicker: string; rows: { judgment: string; facts: string; state: string; state_cls: string; adjust: string }[] };
  funding_industry: { kicker: string; items: { label: string; metric: string; cls: string; note: string }[] };
  tracking: { kicker: string; rows: { topic: string; judgment: string; support: string; counter: string; next: string; falsify: string; period: string }[] };
  events: { kicker: string; rows: { time: string; event: string; markets: string; var: string }[] };
  sources: { kicker: string; rows: { url: string; label: string; use: string }[]; note: string };
}

function useBrief(date: string) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`/api/morning-brief?date=${encodeURIComponent(date)}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((b) => setData(b.data))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [date]);
  return { data, error, loading };
}

type Mode = "all" | "overview" | "research";

export function MorningBrief() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") || "2026-08-14";
  const { data, error, loading } = useBrief(date);
  const [mode, setMode] = useState<Mode>("all");

  const dl = (kind: "html" | "pdf") =>
    `/api/morning-brief/download?date=${encodeURIComponent(date)}&kind=${kind}`;

  if (loading) return <div className="mb-root"><div className="page"><div style={{ padding: 60, textAlign: "center", color: "#6a7585" }}>正在加载晨报…</div></div></div>;
  if (error || !data) return <div className="mb-root"><div className="page"><div style={{ padding: 60, textAlign: "center", color: "#c23b3b" }}>加载失败：{error ?? "无数据"}</div></div></div>;

  const m = data.report_meta;
  const hidden = (view: string) => (mode !== "all" && mode !== view ? { "data-mode-hide": "1" as const } : {});

  return (
    <div className="mb-root">
      <div className="page">
        {/* Hero */}
        <header className="hero">
          <div className="eyebrow">UNIFIED MORNING BRIEF · 实验版</div>
          <h1>统一交易晨报｜{m.report_date}</h1>
          <div className="hero-meta">
            <span>数据冻结：{m.report_cutoff.slice(11, 16)}</span>
            <span>中国市场：{m.china_market_date}</span>
            <span>美国市场：{m.global_market_date}</span>
          </div>
          <div className="hero-call">{m.headline}</div>
        </header>

        {/* Controls */}
        <div className="controls">
          {([["all", "全部"], ["overview", "概览"], ["research", "研究"]] as [Mode, string][]).map(([v, label]) => (
            <button key={v} className={mode === v ? "active" : ""} data-mode={v} onClick={() => setMode(v)}>{label}</button>
          ))}
          <div className="dl">
            <button onClick={() => window.open(dl("html"), "_blank")}>下载 HTML</button>
            <button onClick={() => window.open(dl("pdf"), "_blank")}>下载 PDF</button>
            <input type="date" value={date} onChange={(e) => e.target.value && setParams({ date: e.target.value })} style={{ border: "1px solid var(--line)", borderRadius: 7, padding: "7px 10px", fontSize: 12, background: "var(--control-bg)", color: "var(--ink)", colorScheme: "dark" }} />
          </div>
        </div>

        {/* 90秒摘要 */}
        <section data-view="overview" {...hidden("overview")}>
          <div className="section-head"><h2>90秒摘要</h2><span className="kicker">{data.summary.kicker}</span></div>
          <div className="summary-grid">
            <div>
              <h3>{data.summary.overnight_title}</h3>
              <ol className="summary-list">
                {data.summary.overnight_changes.map((c, i) => (
                  <li key={i}><b>{c.title}</b>{c.text}</li>
                ))}
              </ol>
              <h3 style={{ marginTop: 16 }}>{data.summary.china_title}</h3>
              <ol className="summary-list">
                {data.summary.china_changes.map((c, i) => (
                  <li key={i}><b>{c.title}</b>{c.text}</li>
                ))}
              </ol>
            </div>
            <div>
              <div className="card soft">
                <div className="label">{data.summary.priority_card.label}</div>
                <div style={{ fontWeight: 760 }}>{data.summary.priority_card.title}</div>
                <div className="note">{data.summary.priority_card.note}</div>
              </div>
              {data.summary.priorities.map((p, i) => (
                <div className="priority" key={i}><b>{p.head}</b>{p.text}</div>
              ))}
            </div>
          </div>
        </section>

        {/* 海内外大类资产总览 */}
        <section data-view="overview" {...hidden("overview")}>
          <div className="section-head"><h2>海内外大类资产总览</h2><span className="kicker">{data.asset_overview.kicker}</span></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>市场</th><th>资产</th><th>最新值</th><th>变化</th><th>真实时点</th><th>市场含义</th></tr></thead>
              <tbody>
                {data.asset_overview.rows.map((r, i) => (
                  <tr key={i}>
                    <td><span className="group-tag">{r.market}</span></td>
                    <td><strong>{r.asset}</strong></td>
                    <td>{r.value}</td>
                    <td className={r.cls}>{r.change}</td>
                    <td className="time">{r.time}</td>
                    <td>{r.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 隔夜关键驱动 */}
        <section data-view="overview" {...hidden("overview")}>
          <div className="section-head"><h2>隔夜关键驱动</h2><span className="kicker">{data.overnight_drivers.kicker}</span></div>
          <div className="grid-3">
            {data.overnight_drivers.items.map((d, i) => (
              <div className="card" key={i}>
                <div className="label">{d.label}</div>
                <h3>{d.title}</h3>
                <p className="note">{d.note}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 昨日中国市场 */}
        <section data-view="overview" {...hidden("overview")}>
          <div className="section-head"><h2>{data.china_market.title}</h2><span className="kicker">{data.china_market.kicker}</span></div>
          <div className="priority"><b>昨天真正重要的不是上证跌0.50%，而是日内结构。</b> {data.china_market.priority}</div>
          <div className="warning">{data.china_market.warning}</div>
          <div className="switch-grid">
            {data.china_market.switch.map((s, i) => (
              <div key={i} style={{ display: "contents" }}>
                <div className="card">
                  <div className="label">{s.label}</div>
                  <div className={`metric ${s.cls}`}>{s.metric}</div>
                  <p className="note">{s.note}</p>
                </div>
                {i === 0 && <div className="switch-arrow">→</div>}
              </div>
            ))}
          </div>
          <div className="grid-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h3>{data.china_market.breadth.title}</h3>
              <div className="breadth">
                <span className="u" style={{ width: `${data.china_market.breadth.up_pct}%` }} />
                <span className="d" style={{ width: `${data.china_market.breadth.down_pct}%` }} />
              </div>
              <div className="grid-2">
                <div><div className="label">上涨</div><div className="metric up">{data.china_market.breadth.up}</div></div>
                <div><div className="label">下跌</div><div className="metric down">{data.china_market.breadth.down}</div></div>
              </div>
              <p className="note">{data.china_market.breadth.note}</p>
            </div>
            <div className="card">
              <h3>{data.china_market.industry.title}</h3>
              <div className="industrybar">
                <span className="u" style={{ width: `${data.china_market.industry.up_pct}%` }} />
                <span className="d" style={{ width: `${data.china_market.industry.down_pct}%` }} />
              </div>
              <div className="grid-2">
                <div><div className="label">上涨行业</div><div className="metric up">{data.china_market.industry.up}</div></div>
                <div><div className="label">下跌行业</div><div className="metric down">{data.china_market.industry.down}</div></div>
              </div>
              <p className="note">{data.china_market.industry.note}</p>
            </div>
          </div>
        </section>

        {/* 三条统一市场主线 */}
        <section data-view="research" {...hidden("research")}>
          <div className="section-head"><h2>三条统一市场主线</h2><span className="kicker">{data.mainlines.kicker}</span></div>
          {data.mainlines.items.map((ml, i) => (
            <article className="mainline" key={i}>
              <div className="mainline-head">
                <div>
                  {ml.tags.map((t) => <span className="tag" key={t}>{t}</span>)}
                  <h3 style={{ clear: "both" }}>{ml.title}</h3>
                  {ml.paras.map((p, j) => <p key={j}>{p}</p>)}
                </div>
                <div className="evidence">
                  <b>分歧与反方证据</b>{ml.evidence}
                  <br /><br />
                  <b>今日验证</b>{ml.validation}
                </div>
              </div>
            </article>
          ))}
        </section>

        {/* 今日验证清单 */}
        <section data-view="research" {...hidden("research")}>
          <div className="section-head"><h2>今日验证清单</h2><span className="kicker">{data.today_validation.kicker}</span></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>观察对象</th><th>昨日留下的问题</th><th>今天看什么</th><th>判断含义</th></tr></thead>
              <tbody>
                {data.today_validation.rows.map((r, i) => (
                  <tr key={i}><td><strong>{r.subject}</strong></td><td>{r.question}</td><td>{r.look}</td><td>{r.meaning}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 前期观点复盘 */}
        <section data-view="research" {...hidden("research")}>
          <div className="section-head"><h2>前期观点复盘</h2><span className="kicker">{data.previous_review.kicker}</span></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>前一判断</th><th>8月13日新增事实</th><th>状态</th><th>调整</th></tr></thead>
              <tbody>
                {data.previous_review.rows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.judgment}</td><td>{r.facts}</td>
                    <td><span className={`state ${r.state_cls}`}>{r.state}</span></td><td>{r.adjust}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 资金、仓位与产业数据 */}
        <section data-view="research" {...hidden("research")}>
          <div className="section-head"><h2>资金、仓位与产业数据</h2><span className="kicker">{data.funding_industry.kicker}</span></div>
          <div className="grid-3">
            {data.funding_industry.items.map((f, i) => (
              <div className="card" key={i}>
                <div className="label">{f.label}</div>
                <div className={`metric ${f.cls}`}>{f.metric}</div>
                <div className="note">{f.note}</div>
              </div>
            ))}
          </div>
        </section>

        {/* 后续跟踪框架 */}
        <section data-view="research" {...hidden("research")}>
          <div className="section-head"><h2>后续跟踪框架</h2><span className="kicker">{data.tracking.kicker}</span></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>主题</th><th>当前判断</th><th>支持证据</th><th>反方证据</th><th>下一验证</th><th>证伪条件</th><th>周期</th></tr></thead>
              <tbody>
                {data.tracking.rows.map((r, i) => (
                  <tr key={i}>
                    <td><strong>{r.topic}</strong></td><td>{r.judgment}</td><td>{r.support}</td>
                    <td>{r.counter}</td><td>{r.next}</td><td>{r.falsify}</td><td>{r.period}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 今日关注与未来7天事件 */}
        <section data-view="overview" {...hidden("overview")}>
          <div className="section-head"><h2>今日关注与未来7天事件</h2><span className="kicker">{data.events.kicker}</span></div>
          <div className="table-wrap">
            <table className="events">
              <thead><tr><th>北京时间</th><th>事件</th><th>影响市场</th><th>核心验证变量</th></tr></thead>
              <tbody>
                {data.events.rows.map((r, i) => (
                  <tr key={i}><td>{r.time}</td><td>{r.event}</td><td>{r.markets}</td><td>{r.var}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 来源与口径 */}
        <section data-view="research" {...hidden("research")}>
          <div className="section-head"><h2>来源与口径</h2><span className="kicker">{data.sources.kicker}</span></div>
          <div className="table-wrap">
            <table className="sources">
              <thead><tr><th>来源</th><th>用途</th></tr></thead>
              <tbody>
                {data.sources.rows.map((s, i) => (
                  <tr key={i}><td><a href={s.url} target="_blank" rel="noreferrer">{s.label}</a></td><td>{s.use}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note" style={{ marginTop: 11 }}>{data.sources.note}</p>
        </section>

        <div className="footer">统一交易晨报｜{m.report_date}｜数据冻结：北京时间{m.report_cutoff.slice(11, 16)}</div>
      </div>
    </div>
  );
}
