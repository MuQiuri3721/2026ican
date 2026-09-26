// 演示视频 · 口播稿与操作脚本（图文版）— docx 生成
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType,
} = require("docx");
const fs = require("fs");
const { imageSize } = require("image-size");

const ROOT = "E:/开发/2026ican";
const IMG = `${ROOT}/e2e/annot/annotated`;
const OUT = `${ROOT}/docs/演示视频_口播稿与操作脚本_图文版.docx`;

const F = { hei: { ascii: "Times New Roman", eastAsia: "SimHei" }, song: { ascii: "Times New Roman", eastAsia: "SimSun" } };
const CIRC = "①②③④⑤⑥⑦⑧⑨⑩";

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1, keepNext: true,
    spacing: { before: 320, after: 180, line: 380, lineRule: "atLeast" },
    children: [new TextRun({ text, bold: true, size: 32, color: "000000", font: F.hei })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2, keepNext: true,
    spacing: { before: 260, after: 120, line: 360, lineRule: "atLeast" },
    children: [new TextRun({ text, bold: true, size: 28, color: "1F3864", font: F.hei })],
  });
}
function body(text, opts = {}) {
  return new Paragraph({
    alignment: opts.center ? AlignmentType.CENTER : AlignmentType.JUSTIFIED,
    indent: opts.noIndent ? undefined : { firstLine: 420 },
    spacing: { line: 312, after: opts.after ?? 60 },
    children: [new TextRun({ text, bold: !!opts.bold, size: opts.size || 24, color: opts.color || "000000", font: F.song })],
  });
}
function step(text) {
  return new Paragraph({
    alignment: AlignmentType.LEFT, indent: { left: 360 },
    spacing: { line: 312, after: 40 },
    children: [new TextRun({ text, size: 24, color: "000000", font: F.song })],
  });
}
function figure(name, width = 600) {
  const p = `${IMG}/${name}.png`;
  if (!fs.existsSync(p)) return body(`（${name} 截图缺失）`, { center: true, noIndent: true });
  const buf = fs.readFileSync(p);
  const dim = imageSize(buf);
  const w = width, h = Math.round(w * dim.height / dim.width);
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 },
    children: [new ImageRun({ data: buf, transformation: { width: w, height: h }, type: "png" })],
  });
}
function legend(labels) {
  const t = labels.map((l, i) => `${CIRC[i]} ${l}`).join("　");
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED, spacing: { line: 300, after: 140 },
    children: [new TextRun({ text: `图上编号说明：${t}`, size: 21, color: "444444", font: F.song })],
  });
}
function voTable(rows) {
  const bd = { style: BorderStyle.SINGLE, size: 4, color: "9CAFCD" };
  const cell = (text, w, head) => new TableCell({
    width: { size: w, type: WidthType.PERCENTAGE },
    shading: head ? { type: ShadingType.CLEAR, fill: "1F3864" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({
      spacing: { line: 300 },
      children: [new TextRun({ text, bold: !!head, size: head ? 22 : 22, color: head ? "FFFFFF" : "000000", font: F.song })],
    })],
  });
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: { top: bd, bottom: bd, left: bd, right: bd, insideHorizontal: bd, insideVertical: bd },
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true, children: [cell("成片时间码", 18, true), cell("口播内容", 82, true)] }),
      ...rows.map(([t, c]) => new TableRow({ cantSplit: true, children: [cell(t, 18, false), cell(c, 82, false)] })),
    ],
  });
}
function voNote() {
  return new Paragraph({
    spacing: { before: 80, after: 200, line: 300 },
    children: [new TextRun({ text: "（口播数值以录制时屏幕实际显示为准；本句录废只重录该句。）", italics: true, size: 20, color: "666666", font: F.song })],
  });
}

// ── 各镜头图例（与 boxes.json 顺序一致）──
const L = {
  map: ["页面标题与推演轮次提示", "平面 / 三维地形切换", "六个图层开关", "指定火点 / 语音广播", "右侧信息栏（实时画面 / 任务执行 / 环境）", "底部方案条（当前方案 / 结论 / 下次评估）"],
  command_drawer: ["拖拽区：拖入 / 选择火场照片", "勾选「上传时调用 VLM 解释」", "模型状态行（YOLO / VLM / GLM）", "演示脚本（一键主场景）"],
  command_assess: ["影像主舞台（真实火场照片 + YOLO 检测框）", "原图 / 检测结果 切换", "火情识别结果（视觉观察陈述）", "YOLO / VLM / GLM 状态徽章", "火情量化（等级 / FLP，规则引擎计算）", "环境影响（坡度 / 植被 / 风速 / 温湿度）", "指挥操作条（吸底常驻）"],
  dispatch_top: ["调度地图（火点 / 水源 / 航线）", "火情告警卡（等级 / 面积 / 风向）", "调度结论三态", "五指标盒", "方案摘要（中文触发原因）", "方案审批表单"],
  dispatch_approval: ["批准主方案（点击后进入执行）", "驳回 / 终止任务", "操作原因输入框（驳回/终止必填）"],
  dispatch_ledger: ["2+6+4 编组表（12 架分工与状态）", "推演账本（每轮 FLP 账目）", "回放面板"],
  analysis_top: ["复盘 KPI（FLP 变化 / 压制效率）", "过火面积趋势 + FLP 曲线", "资源消耗 KPI", "前后轮次对比表", "多任务对比勾选"],
  analysis_bottom: ["复盘回放", "报告输出（在线 / 图文 / JSON / PDF）"],
  fleet_top: ["资源 KPI 一行", "机卡（SOC / 健康 / 载荷 / 任务）", "遥测展开按钮"],
  fleet_bottom: [],
  history: ["状态过滤器", "任务归档行（点行恢复任务）", "勾选 2-4 个任务横向对比", "详情按钮（任务全流程）"],
};

const children = [];

// ── 标题与用法 ──
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 200, after: 120, line: 400 },
  children: [new TextRun({ text: "火巡智策演示视频", bold: true, size: 44, color: "1F3864", font: F.hei })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 240, line: 360 },
  children: [new TextRun({ text: "口播稿 · 操作脚本 · 图文对照版（成片 6 分 30 秒）", bold: true, size: 26, color: "000000", font: F.hei })],
}));
children.push(body("用法：先按「录制前检查单」备场；再按「逐镜头图文详解」的顺序录制——每个镜头包含①操作步骤（照着点）、②带编号标注的界面截图（圈到哪里点哪里，图例在图下方）、③口播稿表（对着时间码念）。录完按「剪辑与后期」合成：屏幕视频 + 单独口播 + BGM，等待段加速。", { after: 200 }));

// ── 一、录制前检查单 ──
children.push(h1("一、录制前检查单"));
const checks = [
  "三个服务在线：① python yolo_server/server.py --port 9000　② cd backend 后启动后端（cmd 用 set FIRE_YOLO_ENDPOINT=http://127.0.0.1:9000/detect，bash 用 export ...）再 python -m uvicorn app.main:app --port 8000　③ cd frontend && npx vite --port 5173",
  "YOLO 预热：服务刚启动后先随意传一张图完成一次研判（或命令行调一次 /detect），避免首帧超时",
  "★ 清理在途任务（关键）：到任务管理页，把「执行中/待确认」的旧任务全部终止——否则资源锁被占，镜头 3 的批准会一直失败",
  "★ 库里有已推演的历史任务（镜头 1/5/7 需要数据）：没有就先把镜头 2-3 的流程完整跑一遍",
  "浏览器 1920×1080 全屏、隐藏书签栏、只留一个标签页、系统缩放 100%、开启系统勿扰",
  "主素材图：e2e/real/AoF07718.jpg（5 个检测框，镜头 2 用）；备用剧情图：AoF07719.jpg（III 级大火·请求增援）",
  "录屏 30 帧 + 麦克风，先试录 10 秒检查底噪",
  "开录前 30 分钟内若没调过 VLM，一次即可成；若界面出现「规则映射」回落标注，等 2 分钟重录",
];
checks.forEach((c, i) => children.push(step(`☐ ${i + 1}. ${c}`)));

// ── 二、成片分镜总表 ──
children.push(h1("二、成片分镜总表"));
const srows = [
  ["镜头 1", "0:00–0:35", "态势总览", "开场 · 平台定位与全局态势"],
  ["镜头 2", "0:35–1:50", "火情监测", "真实照片上传 → YOLO 真实检测 → VLM 解释 → 量化（核心）"],
  ["镜头 3", "1:50–2:55", "机群调度", "方案生成 · 调度结论 · 审批"],
  ["镜头 4", "2:55–3:50", "态势 + 调度", "轮次推演 · 多页联动 · 重规划兜底"],
  ["镜头 5", "3:50–4:45", "数据分析", "复盘 KPI · 双曲线 · 轮次表 · 对比"],
  ["镜头 6", "4:45–5:25", "资源管理", "12 架机卡 · 遥测 · 库存与水源"],
  ["镜头 7", "5:25–6:05", "任务管理", "归档 · 详情 · 对比 · 报告导出"],
  ["镜头 8", "6:05–6:40", "态势总览", "收尾 · 闭环总结"],
];
const sbd = { style: BorderStyle.SINGLE, size: 4, color: "9CAFCD" };
const scell = (text, w, head) => new TableCell({
  width: { size: w, type: WidthType.PERCENTAGE },
  shading: head ? { type: ShadingType.CLEAR, fill: "1F3864" } : undefined,
  margins: { top: 60, bottom: 60, left: 100, right: 100 },
  children: [new Paragraph({ spacing: { line: 300 }, children: [new TextRun({ text, bold: !!head, size: 21, color: head ? "FFFFFF" : "000000", font: F.song })] })],
});
children.push(new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  borders: { top: sbd, bottom: sbd, left: sbd, right: sbd, insideHorizontal: sbd, insideVertical: sbd },
  rows: [
    new TableRow({ tableHeader: true, cantSplit: true, children: [scell("镜头", 10, true), scell("成片时间", 16, true), scell("页面", 14, true), scell("核心内容", 60, true)] }),
    ...srows.map(r => new TableRow({ cantSplit: true, children: [scell(r[0], 10), scell(r[1], 16), scell(r[2], 14), scell(r[3], 60)] })),
  ],
}));
children.push(new Paragraph({ spacing: { after: 120 }, children: [] }));

// ── 三、逐镜头图文详解 ──
children.push(h1("三、逐镜头图文详解"));

// 镜头 1
children.push(h2("镜头 1 ｜ 0:00–0:35 ｜ 开场 · 态势总览"));
children.push(body("操作：恢复一个已推演过的任务（任务管理→点任务行），切到态势总览；鼠标缓慢划过①→②→③→④→⑤→⑥，最后停在底部方案条。", { noIndent: true }));
children.push(figure("map"));
children.push(legend(L.map));
children.push(voTable([
  ["0:03", "这里的紫金山，一场森林火灾正在发生。"],
  ["0:09", "火巡智策，是一套面向森林火灾的智能应急指挥平台。"],
  ["0:16", "高分卫星底图上，火点位置、过火范围、取水路线、机群位置一屏尽览。"],
  ["0:24", "左上是当前火情等级与处置结论，右侧是无人机回传的实时画面和任务执行进度。"],
]));
children.push(voNote());

// 镜头 2
children.push(h2("镜头 2 ｜ 0:35–1:50 ｜ 核心 · 真实影像接入与智能识别（火情监测）"));
children.push(body("操作：切到火情监测 → 工具抽屉默认展开。", { noIndent: true }));
children.push(figure("command_drawer", 560));
children.push(legend(L.command_drawer));
children.push(step("步骤 1：勾选「上传时调用 VLM 解释」（③）。"));
children.push(step("步骤 2：点拖拽区（①）选择 e2e/real/AoF07718.jpg，出现「影像已接入」（注意：上传成功后工具抽屉会自动收起，属正常设计）。"));
children.push(step("步骤 3：点吸底操作条上的「开始研判」，进度条走完约 40 秒（素材 4 倍速）。"));
children.push(figure("command_assess"));
children.push(legend(L.command_assess));
children.push(step("步骤 4：切「检测结果」视图（③），鼠标依次划过 5 个检测框。"));
children.push(step("步骤 5：右侧从上往下缓划：识别结果（④）→ 徽章（⑤）→ 量化（⑥）→ 环境（⑦）。"));
children.push(voTable([
  ["0:38", "发现火情，靠的是真材实料——我们上传一张无人机实拍的火场照片。"],
  ["0:47", "平台用自训的 YOLO 模型做视觉检测：画面上自动框出了四处火焰和一片烟雾，置信度最高 84%。"],
  ["1:02", "同时接入视觉大模型 GLM-4.6V，对火场做语义解读：火焰面积、烟雾规模、火势趋势，一眼可读。"],
  ["1:15", "请注意，安全关键数值不由大模型拍脑袋——FLP 火情负荷、过火面积，全部由确定性规则引擎计算，每个数都可复算、可追溯。"],
  ["1:31", "火情量化结论直接给出等级与建议（按屏幕念，两版皆有可能）：白天风小时多为「II 级中等火情，可控，立即出动」；夜间风大时可能为「III 级高风险，失控可能，请求增援」。"],
]));
children.push(voNote());

// 镜头 3
children.push(h2("镜头 3 ｜ 1:50–2:55 ｜ 智能调度 · 方案生成与审批（机群调度）"));
children.push(body("操作：点「生成调度方案」自动切到机群调度 → 右侧从上往下划过。", { noIndent: true }));
children.push(figure("dispatch_top"));
children.push(legend(L.dispatch_top));
children.push(voTable([
  ["1:53", "一键生成调度方案。"],
  ["1:57", "平台按 2 加 6 加 4 的编组规则，从十二架无人机里挑出最优组合：侦察机持续观测，灭火机主力压制，支援机通信保障。"],
  ["2:12", "调度结论直接给答案：可控、建议立即出动，预计控制时间屏幕实时给出。"],
  ["2:24", "出动架次、方案版本、SOC 药剂约束、资源缺口，全部量化可见。"],
]));
children.push(voNote());
children.push(body("操作：向下滚动，展示审批表单与编组表。", { noIndent: true }));
children.push(figure("dispatch_approval", 560));
children.push(legend(L.dispatch_approval));
children.push(step("步骤：先向下滚动让「批准主方案」按钮露出（它在首屏折叠线下），再点击 → 任务徽章变「执行中」（此瞬间保留原速）。"));
children.push(voTable([["2:36", "指挥员一键批准，方案立即进入执行。"]]));
children.push(voNote());

// 镜头 4
children.push(h2("镜头 4 ｜ 2:55–3:50 ｜ 推演执行 · 多页联动"));
children.push(body("操作：切态势总览看机群动态（素材 3 倍速）→ 切回机群调度滚动到账本 → 点一次「执行下一轮监测」。", { noIndent: true }));
children.push(figure("dispatch_ledger"));
children.push(legend(L.dispatch_ledger));
children.push(voTable([
  ["2:58", "方案批准只是开始，平台进入离散轮次推演：每五分钟一个决策轮。"],
  ["3:08", "态势图上，机群沿航线包围火场，实时画面持续回传。"],
  ["3:18", "每一轮，规则引擎都在重新计算火情负荷：压制了多少、自然增长了多少、净变化多少，全部记入推演账本。"],
  ["3:32", "一旦火情负荷增长超 20%、风档变化或单机失能，平台会自动触发重规划，二次审批兜底安全。"],
]));
children.push(voNote());

// 镜头 5
children.push(h2("镜头 5 ｜ 3:50–4:45 ｜ 数据分析 · 复盘"));
children.push(figure("analysis_top"));
children.push(legend(L.analysis_top));
children.push(voTable([
  ["3:53", "火扑灭了，仗打得怎么样？数据分析页给出复盘答案。"],
  ["4:00", "FLP 净变化与压制效率直接给结论——五个轮次，从发现到扑灭。"],
  ["4:12", "过火面积与火情负荷双曲线一目了然，每轮的侦察、压制、补给动作全部留痕。"],
]));
children.push(voNote());
children.push(figure("analysis_bottom", 560));
children.push(legend(L.analysis_bottom));
children.push(voTable([["4:24", "药剂消耗、出动架次、补水换电次数自动汇总，还支持 2 到 4 个任务横向对比。"]]));
children.push(voNote());

// 镜头 6
children.push(h2("镜头 6 ｜ 4:45–5:25 ｜ 资源管理"));
children.push(figure("fleet_top"));
children.push(legend(L.fleet_top));
children.push(step("操作：点任一机卡的遥测按钮展开再收起；滚动展示底部库存与水源表。"));
children.push(voTable([
  ["4:48", "后勤保障看资源管理。"],
  ["4:52", "十二架无人机的电量、健康、信号、载荷、药剂余量、当前任务，一屏全览；每架都能展开遥测细看。"],
  ["5:06", "W20 水剂、C6 气剂、备用电池库存和水源候选实时在册，补给决策有据可依。"],
]));
children.push(voNote());

// 镜头 7
children.push(h2("镜头 7 ｜ 5:25–6:05 ｜ 任务管理 · 归档与报告"));
children.push(body("操作：点状态过滤器切换 → 点任务行恢复任务 → 勾两行开对比 → 点「详情」看全流程并找到「导出图文报告」。", { noIndent: true }));
children.push(figure("history"));
children.push(legend(L.history));
children.push(voTable([
  ["5:28", "每一次任务自动归档：编号、等级、面积、处置结论、耗时，随时检索恢复。"],
  ["5:40", "任务全流程、方案版本、轮次执行结果可完整回放，还能勾选多个任务横向对比。"],
  ["5:52", "一键导出图文报告，扑救过程变成可交付的书面材料。"],
]));
children.push(voNote());

// 镜头 8
children.push(h2("镜头 8 ｜ 6:05–6:40 ｜ 收尾 · 回到态势总览"));
children.push(body("操作：切回态势总览，地图缓慢拉远，定格全屏 3 秒（画面参考镜头 1）。", { noIndent: true }));
children.push(voTable([
  ["6:08", "从影像接入、智能识别，到方案生成、推演执行，再到复盘归档——"],
  ["6:18", "火巡智策用真实检测、大模型解释和确定性规则引擎，把森林火灾的指挥决策，变成一条可追溯的闭环。"],
]));
children.push(voNote());

// ── 四、口播稿连读版 ──
children.push(h1("四、口播稿连读版（单独录音频用）"));
children.push(body("按「／」断句，每句可独立重录；录废只重说该句，剪辑时切掉废句。", { noIndent: true }));
const lian = "这里的紫金山，一场森林火灾正在发生。／火巡智策，是一套面向森林火灾的智能应急指挥平台。／高分卫星底图上，火点位置、过火范围、取水路线、机群位置一屏尽览。／左上是当前火情等级与处置结论，右侧是无人机回传的实时画面和任务执行进度。／发现火情，靠的是真材实料——我们上传一张无人机实拍的火场照片。／平台用自训的 YOLO 模型做视觉检测：画面上自动框出了四处火焰和一片烟雾，置信度最高 84%。／同时接入视觉大模型 GLM-4.6V，对火场做语义解读：火焰面积、烟雾规模、火势趋势，一眼可读。／请注意，安全关键数值不由大模型拍脑袋——FLP 火情负荷、过火面积，全部由确定性规则引擎计算，每个数都可复算、可追溯。／火情量化结论：II 级中等火情，当前可控，可以立即出动。／一键生成调度方案。／平台按 2 加 6 加 4 的编组规则，从十二架无人机里挑出最优组合：侦察机持续观测，灭火机主力压制，支援机通信保障。／调度结论直接给答案：可控、建议立即出动。／出动架次、方案版本、SOC 药剂约束、资源缺口，全部量化可见。／指挥员一键批准，方案立即进入执行。／方案批准只是开始，平台进入离散轮次推演：每五分钟一个决策轮。／态势图上，机群沿航线包围火场，实时画面持续回传。／每一轮，规则引擎都在重新计算火情负荷：压制了多少、自然增长了多少、净变化多少，全部记入推演账本。／一旦火情负荷增长超 20%、风档变化或单机失能，平台会自动触发重规划，二次审批兜底安全。／火扑灭了，仗打得怎么样？数据分析页给出复盘答案。／FLP 净变化与压制效率直接给结论——五个轮次，从发现到扑灭。／过火面积与火情负荷双曲线一目了然，每轮的侦察、压制、补给动作全部留痕。／药剂消耗、出动架次、补水换电次数自动汇总，还支持 2 到 4 个任务横向对比。／后勤保障看资源管理。／十二架无人机的电量、健康、信号、载荷、药剂余量、当前任务，一屏全览；每架都能展开遥测细看。／W20 水剂、C6 气剂、备用电池库存和水源候选实时在册，补给决策有据可依。／每一次任务自动归档：编号、等级、面积、处置结论、耗时，随时检索恢复。／任务全流程、方案版本、轮次执行结果可完整回放，还能勾选多个任务横向对比。／一键导出图文报告，扑救过程变成可交付的书面材料。／从影像接入、智能识别，到方案生成、推演执行，再到复盘归档——／火巡智策用真实检测、大模型解释和确定性规则引擎，把森林火灾的指挥决策，变成一条可追溯的闭环。";
children.push(body(lian, { noIndent: true }));

// ── 五、剪辑与后期 ──
children.push(h1("五、剪辑与后期"));
[
  "对齐：以每段口播第一句的起始时间为锚，把对应屏幕素材段铺到该时间码下。",
  "变速：研判进度条（镜头 2，40 秒）4 倍速；推演等待（镜头 4，30 秒）3 倍速；其余原速。",
  "剪切：口播废句整句剪掉，重录句拼在原位；句间留 0.3 秒气口；屏幕废操作整段剪掉。",
  "BGM：低沉科技感氛围乐，音量 -18dB（口播 -6dB），镜头 8 结尾渐弱。",
  "字幕：自动识别口播生成，术语校正：FLP、YOLO、GLM-4.6V、SOC、VLM。",
  "角标：镜头 2 右下角「真实火场照片 · PWM-YOLO 真实检测」；镜头 4「5 分钟/轮 · 离散推演」。",
].forEach(t => children.push(step("• " + t)));

// ── 六、应急预案与录制纪律 ──
children.push(h1("六、应急预案与录制纪律"));
const emerg = [
  ["研判失败一次", "YOLO 冷启动超时——立刻重传同一张图再研判（第二次必成），失败段剪掉"],
  ["徽章显示「回退·规则映射」", "VLM 被限流——等 2 分钟重录本镜头，或先录其他镜头"],
  ["提示资源被其他任务锁定", "任务管理里把「执行中/待确认」的旧任务终止即可"],
  ["数据被清空", "镜头 2-4 现场重跑一遍即重新生成全部数据"],
  ["服务被关", "按检查单三条命令重启 + YOLO 预热"],
  ["纪律一", "口播里的数值以屏幕实际显示为准——开录每个镜头前先瞄一眼屏幕再念数"],
  ["纪律二", "备用剧情：用 e2e/real/AoF07719.jpg 可录「III 级·请求增援·火力扩大」，插在镜头 3/4 之间"],
];
children.push(new Table({
  width: { size: 100, type: WidthType.PERCENTAGE },
  borders: { top: sbd, bottom: sbd, left: sbd, right: sbd, insideHorizontal: sbd, insideVertical: sbd },
  rows: [
    new TableRow({ tableHeader: true, cantSplit: true, children: [scell("状况", 32, true), scell("处理", 68, true)] }),
    ...emerg.map(r => new TableRow({ cantSplit: true, children: [scell(r[0], 32), scell(r[1], 68)] })),
  ],
}));

const doc = new Document({
  styles: { default: { document: { run: { font: F.song, size: 24 } } } },
  sections: [{
    properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("written:", OUT, buf.length, "bytes");
});
