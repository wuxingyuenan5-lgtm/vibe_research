/**
 * AI 当日复盘 —— 晨报同款版式渲染（复用 morning-brief.css 类）
 * 数据：AI 输出的结构化 payload（report_schema 盘后化子集，不含海内外大类资产总览）
 * 区块：Hero / 90秒摘要 / 今日中国市场 / 晨报主线兑现对照 / 明日验证清单 /
 *       前期观点复盘 / 资金仓位产业 / 后续跟踪框架 / 未来7天事件
 * 任何区块缺失自动跳过（AI 输出不完整不崩）。
 */
export interface ReviewPayload {
  report_meta?: {
    report_name?: string; report_date?: string; report_cutoff?: string;
    china_market_date?: string; headline?: string;
  };
  summary?: {
    kicker?: string; overnight_title?: string;
    overnight_changes?: { title: string; text: string }[];
    china_title?: string; china_changes?: { title: string; text: string }[];
    priority_card?: { label?: string; title?: string; note?: string };
    priorities?: { head: string; text: string }[];
  };
  china_market?: {
    title?: string; kicker?: string; priority?: string; warning?: string;
    switch?: { label?: string; metric?: string; cls?: string; note?: string }[];
    breadth?: { title?: string; up?: string; down?: string; up_pct?: number; down_pct?: number; note?: string };
    industry?: { title?: string; up?: string; down?: string; up_pct?: number; down_pct?: number; note?: string };
  };
  mainlines?: { kicker?: string; items?: { tags?: string[]; title?: string; paras?: string[]; evidence?: string; validation?: string }[] };
  today_validation?: { kicker?: string; rows?: { subject?: string; question?: string; look?: string; meaning?: string }[] };
  previous_review?: { kicker?: string; rows?: { judgment?: string; facts?: string; state?: string; state_cls?: string; adjust?: string }[] };
  funding_industry?: { kicker?: string; items?: { label?: string; metric?: string; cls?: string; note?: string }[] };
  tracking?: { kicker?: string; rows?: { topic?: string; judgment?: string; support?: string; counter?: string; next?: string; falsify?: string; period?: string }[] };
  events?: { kicker?: string; rows?: { time?: string; event?: string; markets?: string; var?: string }[] };
}

const upDown = (cls?: string) =>
  cls === "up" ? "up" : cls === "down" ? "down" : "flat";

export function DailyReviewReport({ p }: { p: ReviewPayload }) {
  const m = p.report_meta;
  const s = p.summary;
  const cm = p.china_market;
  const ml = p.mainlines;
  const tv = p.today_validation;
  const pr = p.previous_review;
  const fi = p.funding_industry;
  const tr = p.tracking;
  const ev = p.events;

  return (
    <div className="mb-root">
      <div className="page">
        {m && (
          <header className="hero">
            <div className="eyebrow">AI DAILY REVIEW · 盘后复盘</div>
            <h1>AI 当日复盘｜{m.report_date || "—"}</h1>
            <div className="hero-meta">
              <span>数据冻结：{m.report_cutoff ? m.report_cutoff.slice(11, 16) : "—"}</span>
              <span>中国市场：{m.china_market_date || "—"}</span>
            </div>
            {m.headline && <div className="hero-call">{m.headline}</div>}
          </header>
        )}

        {s && (
          <section>
            <div className="section-head"><h2>90秒摘要</h2>{s.kicker && <span className="kicker">{s.kicker}</span>}</div>
            <div className="summary-grid">
              <div>
                {s.overnight_changes && s.overnight_changes.length > 0 && (
                  <>
                    <h3>{s.overnight_title || "今日重要变化"}</h3>
                    <ol className="summary-list">
                      {s.overnight_changes.map((c, i) => (
                        <li key={i}><b>{c.title}</b>{c.text}</li>
                      ))}
                    </ol>
                  </>
                )}
                {s.china_changes && s.china_changes.length > 0 && (
                  <>
                    <h3 style={{ marginTop: 16 }}>{s.china_title || "今日中国结构变化"}</h3>
                    <ol className="summary-list">
                      {s.china_changes.map((c, i) => (
                        <li key={i}><b>{c.title}</b>{c.text}</li>
                      ))}
                    </ol>
                  </>
                )}
              </div>
              <div>
                {s.priority_card && (
                  <div className="card soft">
                    <div className="label">{s.priority_card.label || "明天最高优先级"}</div>
                    <div style={{ fontWeight: 760 }}>{s.priority_card.title}</div>
                    {s.priority_card.note && <div className="note">{s.priority_card.note}</div>}
                  </div>
                )}
                {(s.priorities || []).map((p2, i) => (
                  <div className="priority" key={i}><b>{p2.head}</b>{p2.text}</div>
                ))}
              </div>
            </div>
          </section>
        )}

        {cm && (
          <section>
            <div className="section-head"><h2>{cm.title || "今日中国市场"}</h2>{cm.kicker && <span className="kicker">{cm.kicker}</span>}</div>
            {cm.priority && <div className="priority"><b>今天真正重要的：</b> {cm.priority}</div>}
            {cm.warning && <div className="warning">{cm.warning}</div>}
            {cm.switch && cm.switch.length > 0 && (
              <div className="switch-grid">
                {cm.switch.slice(0, 2).map((sw, i) => (
                  <div key={i} style={{ display: "contents" }}>
                    <div className="card">
                      <div className="label">{sw.label}</div>
                      <div className={`metric ${upDown(sw.cls)}`}>{sw.metric}</div>
                      {sw.note && <p className="note">{sw.note}</p>}
                    </div>
                    {i === 0 && <div className="switch-arrow">→</div>}
                  </div>
                ))}
              </div>
            )}
            {(cm.breadth || cm.industry) && (
              <div className="grid-2" style={{ marginTop: 14 }}>
                {cm.breadth && (
                  <div className="card">
                    <h3>{cm.breadth.title || "市场宽度"}</h3>
                    <div className="breadth">
                      <span className="u" style={{ width: `${cm.breadth.up_pct ?? 50}%` }} />
                      <span className="d" style={{ width: `${cm.breadth.down_pct ?? 50}%` }} />
                    </div>
                    <div className="grid-2">
                      <div><div className="label">上涨</div><div className="metric up">{cm.breadth.up}</div></div>
                      <div><div className="label">下跌</div><div className="metric down">{cm.breadth.down}</div></div>
                    </div>
                    {cm.breadth.note && <p className="note">{cm.breadth.note}</p>}
                  </div>
                )}
                {cm.industry && (
                  <div className="card">
                    <h3>{cm.industry.title || "申万一级行业宽度"}</h3>
                    <div className="industrybar">
                      <span className="u" style={{ width: `${cm.industry.up_pct ?? 50}%` }} />
                      <span className="d" style={{ width: `${cm.industry.down_pct ?? 50}%` }} />
                    </div>
                    <div className="grid-2">
                      <div><div className="label">上涨行业</div><div className="metric up">{cm.industry.up}</div></div>
                      <div><div className="label">下跌行业</div><div className="metric down">{cm.industry.down}</div></div>
                    </div>
                    {cm.industry.note && <p className="note">{cm.industry.note}</p>}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {ml && ml.items && ml.items.length > 0 && (
          <section>
            <div className="section-head"><h2>三条统一市场主线</h2>{ml.kicker && <span className="kicker">{ml.kicker}</span>}</div>
            {ml.items.map((item, i) => (
              <article className="mainline" key={i}>
                <div className="mainline-head">
                  <div>
                    {(item.tags || []).map((t) => <span className="tag" key={t}>{t}</span>)}
                    <h3 style={{ clear: "both" }}>{item.title}</h3>
                    {(item.paras || []).map((pp, j) => <p key={j}>{pp}</p>)}
                  </div>
                  <div className="evidence">
                    {item.evidence && (<><b>分歧与反方证据</b>{item.evidence}<br /><br /></>)}
                    {item.validation && (<><b>明日继续验证</b>{item.validation}</>)}
                  </div>
                </div>
              </article>
            ))}
          </section>
        )}

        {tv && tv.rows && tv.rows.length > 0 && (
          <section>
            <div className="section-head"><h2>明日验证清单</h2>{tv.kicker && <span className="kicker">{tv.kicker}</span>}</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>观察对象</th><th>今天留下的问题</th><th>明天看什么</th><th>判断含义</th></tr></thead>
                <tbody>
                  {tv.rows.map((r, i) => (
                    <tr key={i}>
                      <td><strong>{r.subject}</strong></td>
                      <td>{r.question}</td><td>{r.look}</td><td>{r.meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {pr && pr.rows && pr.rows.length > 0 && (
          <section>
            <div className="section-head"><h2>前期观点复盘</h2>{pr.kicker && <span className="kicker">{pr.kicker}</span>}</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>前一判断</th><th>新增事实</th><th>状态</th><th>调整</th></tr></thead>
                <tbody>
                  {pr.rows.map((r, i) => (
                    <tr key={i}>
                      <td>{r.judgment}</td><td>{r.facts}</td>
                      <td><span className={`state ${r.state_cls || "neutral"}`}>{r.state}</span></td><td>{r.adjust}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {fi && fi.items && fi.items.length > 0 && (
          <section>
            <div className="section-head"><h2>资金、仓位与产业数据点评</h2>{fi.kicker && <span className="kicker">{fi.kicker}</span>}</div>
            <div className="space-y-4">
              {fi.items.map((f, i) => (
                <div key={i} className="border-l-2 border-primary/40 pl-4 py-1">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <h3 className="!mb-0">{f.label}</h3>
                    <span className={`metric !text-[20px] ${upDown(f.cls)}`}>{f.metric}</span>
                  </div>
                  {f.note && (
                    <div className="mt-1.5 text-sm leading-relaxed text-foreground/90 whitespace-pre-line">{f.note}</div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {tr && tr.rows && tr.rows.length > 0 && (
          <section>
            <div className="section-head"><h2>后续跟踪框架</h2>{tr.kicker && <span className="kicker">{tr.kicker}</span>}</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>主题</th><th>当前判断</th><th>支持证据</th><th>反方证据</th><th>下一验证</th><th>证伪条件</th><th>周期</th></tr></thead>
                <tbody>
                  {tr.rows.map((r, i) => (
                    <tr key={i}>
                      <td><strong>{r.topic}</strong></td><td>{r.judgment}</td><td>{r.support}</td>
                      <td>{r.counter}</td><td>{r.next}</td><td>{r.falsify}</td><td>{r.period}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {ev && ev.rows && ev.rows.length > 0 && (
          <section>
            <div className="section-head"><h2>今日关注与未来7天事件</h2>{ev.kicker && <span className="kicker">{ev.kicker}</span>}</div>
            <div className="table-wrap">
              <table className="events">
                <thead><tr><th>北京时间</th><th>事件</th><th>影响市场</th><th>核心验证变量</th></tr></thead>
                <tbody>
                  {ev.rows.map((r, i) => (
                    <tr key={i}><td>{r.time}</td><td>{r.event}</td><td>{r.markets}</td><td>{r.var}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
