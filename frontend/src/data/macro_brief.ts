/**
 * 中美宏观速览 + 未来关注事件（AI 当日复盘数据源之一）
 *
 * ⚠️ 数据为 2026-08-18 快照。**每条必须带数据期（period）和发布日期（release）**——
 * AI 复盘会原样喂给 LLM，prompt 强约束每条都带日期；缺日期的字段会被 LLM 当作"无日期"忽略。
 * 每周需人工/采集更新一次；更新时保持结构不变。
 */
export interface MacroItem {
  indicator: string; // "CPI 同比" / "7月非农新增" / "央行 Q2 货币政策报告"
  value: string;     // "同比+3.4%（环比+0.1%），核心+2.5%，创四年多新低"
  period: string;    // "7月" / "2026 Q2" / "7/30"（数据统计期）
  release: string;   // "8/12发布" / "7/31公布" / "8/14发布"（官方发布日期）
}
export const macroBrief = {
  china: [
    { indicator: "CPI 同比",    value: "同比+0.5%（环比-0.1%），核心CPI同比+0.9%；1-7月累计+0.9%", period: "7月",      release: "8/9发布" },
    { indicator: "PPI 同比",    value: "同比+3.5%（环比-0.7%，涨幅回落0.6pct），连续5个月正增长",                period: "7月",      release: "8/9发布" },
    { indicator: "社融累计增量", value: "1-7月累计增量22.25万亿元（同比少1.74万亿）；7月末存量463.27万亿，同比+7.4%", period: "1-7月",    release: "8月中旬发布" },
    { indicator: "M2 / M1",     value: "7月末M2同比+7.7%、M1同比+4%",                                          period: "7月末",    release: "8/13发布" },
    { indicator: "制造业 PMI",   value: "49.2%（回落1.1pct，低于荣枯线50）",                                      period: "7月",      release: "7/31发布" },
    { indicator: "出口",        value: "7月同比+25%（增速回落5.6pct），贸易顺差1125亿美元",                       period: "7月",      release: "8/7发布" },
    { indicator: "政策定调",    value: "7月底政治局会议「更加积极财政+适度宽松货币」",                            period: "7月底",    release: "7月底会议" },
    { indicator: "央行 Q2 货政报告", value: "强调物价合理回升；Q2货币政策报告",                                     period: "2026 Q2", release: "8/12发布" },
  ],
  us: [
    { indicator: "CPI 同比",    value: "同比+3.4%（环比+0.1%），核心CPI同比+2.5%，创四年多新低",                   period: "7月",      release: "8/12发布" },
    { indicator: "PPI 同比",    value: "同比+4.7%（3月以来新低）",                                                 period: "7月",      release: "8/14发布" },
    { indicator: "非农新增",    value: "7月新增-2.3万人（预期+8万），5-6月合计下修10.3万；失业率4.1%，时薪同比+3.15%", period: "7月",      release: "8/1发布" },
    { indicator: "FOMC 利率决议", value: "维持利率3.50%-3.75%（连续第5次）；投票9-3（3票主张加息25bp，2016年来首次）；主席沃什中性偏鹰", period: "7/30", release: "7/30会议" },
    { indicator: "FedWatch",    value: "9月维持利率概率约65.9%，加息25bp约34.1%（实时变化，引用时取最新）",          period: "实时",      release: "实时" },
  ],
  upcoming: [
    { time: "8/20",          event: "中国LPR报价（预期维持不变）",        markets: "中国利率", var: "1Y/5Y LPR" },
    { time: "8月末-9月初",    event: "中国8月官方PMI",                    markets: "中国景气",  var: "制造业 PMI 50荣枯线" },
    { time: "8月中下旬",      event: "美国8月CPI与就业报告",              markets: "美国宏观",  var: "CPI / 非农 / 失业率" },
    { time: "9/16-17",        event: "美联储FOMC会议",                    markets: "全球利率",  var: "点阵图 / 利率决议" },
    { time: "8-9月",          event: "中国社融与政府债供给提速",          markets: "中国流动性", var: "社融存量增速 / 财政支出" },
    { time: "持续",           event: "地缘：霍尔木兹海峡与油价",          markets: "原油/避险",  var: "Brent/WTI 油价" },
  ],
} as const;