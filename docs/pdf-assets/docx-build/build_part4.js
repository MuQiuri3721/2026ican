// 第四部分 系统实现与交互 — docx 初稿生成（Profile A 正式排版）
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, Header, Footer, PageNumber, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType,
} = require("docx");
const fs = require("fs");
const { imageSize } = require("image-size");

const ROOT = "E:/开发/2026ican";
const OUT = `${ROOT}/docs/pdf-assets/火巡智策_第四部分_系统实现与交互_初稿.docx`;

const F = { hei: { ascii: "Times New Roman", eastAsia: "SimHei" }, song: { ascii: "Times New Roman", eastAsia: "SimSun" } };

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1, alignment: AlignmentType.CENTER, keepNext: true,
    spacing: { before: 240, after: 200, line: 380, lineRule: "atLeast" },
    children: [new TextRun({ text, bold: true, size: 32, color: "000000", font: F.hei })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2, keepNext: true,
    spacing: { before: 280, after: 140, line: 360, lineRule: "atLeast" },
    children: [new TextRun({ text, bold: true, size: 30, color: "000000", font: F.hei })],
  });
}
function body(segs, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: opts.noIndent ? undefined : { firstLine: 480 },
    spacing: { line: 312, after: opts.after ?? 60 },
    children: segs.map(([t, b]) => new TextRun({ text: t, bold: !!b, size: 24, color: "000000", font: F.song })),
  });
}
function caption(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 80, after: 240, line: 280 },
    children: [new TextRun({ text, bold: true, size: 21, color: "000000", font: F.song })],
  });
}
function figure(path, displayWidth) {
  const buf = fs.readFileSync(path);
  const dim = imageSize(buf);
  const w = displayWidth, h = Math.round(w * dim.height / dim.width);
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 160, after: 40 },
    children: [new ImageRun({ data: buf, transformation: { width: w, height: h }, type: "png" })],
  });
}
const cellMargins = { top: 70, bottom: 70, left: 130, right: 130 };
function tcell(text, { bold = false, fill = null, w = null } = {}) {
  return new TableCell({
    children: [new Paragraph({ spacing: { line: 280 },
      children: [new TextRun({ text, bold, size: 21, color: "000000", font: F.song })] })],
    shading: fill ? { type: ShadingType.CLEAR, fill } : undefined,
    margins: cellMargins,
    width: w ? { size: w, type: WidthType.PERCENTAGE } : undefined,
  });
}
function table(headers, rows, widths) {
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: "8fa3b8" },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: "8fa3b8" },
      left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: "d5dde5" },
      insideVertical: { style: BorderStyle.NONE },
    },
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true,
        children: headers.map((t, i) => tcell(t, { bold: true, fill: "eef3f8", w: widths[i] })) }),
      ...rows.map(r => new TableRow({ cantSplit: true,
        children: r.map((t, i) => tcell(t, { w: widths[i] })) })),
    ],
  });
}
function tableTitle(text) {
  return new Paragraph({ keepNext: true, alignment: AlignmentType.CENTER, spacing: { before: 160, after: 80 },
    children: [new TextRun({ text, bold: true, size: 21, color: "000000", font: F.song })] });
}

const children = [
  h1("四、系统实现与交互"),

  h2("4.1 平台实现"),
  body([["火巡智策是一套前后端一体的森林火情处置平台，采用任务驱动主线：报警建立任务后，研判、调度、执行与归档在同一条任务链上自动衔接。"]]),
  body([["前端以 Vue 工作台承载报警输入、态势展示与操作反馈；FastAPI 负责请求校验、任务状态与接口编排；六角色智能体经 Agent/Skill/Tool 链分解任务、调用能力，火情负荷、电量、药剂、时间等安全关键数字由确定性规则引擎统一计算；YOLO 检测与 VLM 视觉理解双路接入（PWM-Net 复现权重可同端点切换），GIS/气象服务提供地形、水源、道路与实时天气，", false], ["多源接入", true], ["统一标注数据来源。"]]),
  body([["任务建立后，", false], ["任务状态", true], ["、方案版本、审批事件与轮次结果持续写入 SQLite，并经 SSE 实时事件推送至工作台；", false], ["方案审批", true], ["门禁确保生成不等于执行，任务结束自动完成", false], ["报告归档", true], ["。"]], { after: 120 }),

  h2("4.2 功能界面"),
  body([["工作台按一次任务的处置顺序组织为四个功能区（实景见图4-1 中排），用户\u201c看得到、点得动、会反馈\u201d。"]], { after: 40 }),
  body([["（一）任务输入区：", true], ["承接报警建档。指挥员输入报警地点或在地图上指定火点坐标，上传航拍图片、多帧序列或视频，并可补充目标时限与出动约束，快速建立标准化火情任务。"]]),
  body([["（二）火场态势区：", true], ["把分散数据收拢为同屏态势。二维战术地图叠加等高线、真实路网、水源与火情范围圈，左上火情等级卡直读等级、过火面积与趋势，有人任务时疏散路线与出口同屏标注；三维地形可查坡度地貌，实时天气、检测证据窗与人员观察一屏尽览。"]]),
  body([["（三）调度决策区：", true], ["回答\u201c为什么这样调度\u201d。十二架无人机按侦察、灭火、支援分组呈现状态与电量；方案摘要给出任务分工、时间窗、硬约束与资源缺口，处置结论按可控、可维持、不可控三态展示；批准、调整、驳回、终止均在此完成，保留人工决策权。"]]),
  body([["（四）反馈报告区：", true], ["支撑持续跟踪与复盘。每五分钟一轮次更新火势负荷、药剂消耗与机群状态，演化曲线标注重规划时点，支持逐轮回放与多任务对比，报告可在线查看或导出，历史任务全程可回溯。"]], { after: 120 }),

  h2("4.3 操作流程"),
  body([["一次完整处置沿九步闭环推进（流程见图4-1 下排）：用户只在报警、确认与再确认三个节点介入，其余步骤由系统自动完成。"]], { after: 40 }),
  body([["①报警建档（用户）：", true], ["输入地点或坐标，上传航拍图片、多帧序列或视频，补充时限与资源约束；"]], { noIndent: true }),
  body([["②自动取数（系统）：", true], ["查询地形坡度、植被、水源道路、气象、机群与库存；"]], { noIndent: true }),
  body([["③火情感知（系统）：", true], ["检测模型与 VLM 产出火焰烟雾、视觉规模与人员观察；"]], { noIndent: true }),
  body([["④综合研判（系统）：", true], ["融合多源事实，计算火情负荷、风险状态与资源约束；"]], { noIndent: true }),
  body([["⑤方案生成（系统）：", true], ["给出侦察、灭火、支援与补给安排及三态处置结论；"]], { noIndent: true }),
  body([["⑥方案确认（用户）：", true], ["批准、调整或驳回；批准后锁定资源进入执行；"]], { noIndent: true }),
  body([["⑦轮次执行（系统）：", true], ["按统一分钟核心推进，每五分钟反馈火势、电量与药剂；"]], { noIndent: true }),
  body([["⑧", true], ["反馈重规划", true], ["（系统＋用户）：", true], ["异常或约束变化触发新方案版本，关键调整再次经用户确认；"]], { noIndent: true }),
  body([["⑨结束归档（系统）：", true], ["扑灭后机群返航回收，任务形成报告归档。"]], { noIndent: true, after: 120 }),

  figure(`${ROOT}/docs/pdf-assets/fig4-1.png`, 580),
  caption("图4-1  系统实现与交互综合图：平台装配（上）· 四个功能区实景（中）· 九步操作流程（下）"),

  // 附录
  new Paragraph({
    heading: HeadingLevel.HEADING_2, pageBreakBefore: true,
    spacing: { before: 120, after: 140 },
    children: [new TextRun({ text: "附录  图注与术语核对表（队员核对用，非正文）", bold: true, size: 28, color: "000000", font: F.hei })],
  }),
  body([["正文名称与界面元素、图4-1 区域的对应关系如下，供排版与核对素材使用；最终 PDF 正文只使用用户语言。"]]),
  tableTitle("表4-1  正文名称与界面元素对应"),
  table(
    ["正文名称", "界面元素 / 组件", "素材位置"],
    [
      ["任务输入区", "现场影像接入（拖拽上传 / 选择文件 / 现场采集）、演练模拟、现场环境", "图4-1（一）；截图 2-analysis-upload"],
      ["火场态势区", "战术地图与图层开关、火情等级浮层卡、三维地形、协作流", "图4-1（二）；截图 1-overview-map"],
      ["调度决策区", "调度建议（方案摘要 / 触发器 / 数字来源条）、机群出动、审批按钮组", "图4-1（三）；截图 6-dispatch-plan"],
      ["反馈报告区", "火情演化曲线、资源消耗、轮次监测结果、推演回放、报告查看、历史对比", "图4-1（四）；截图 7-dispatch-feedback"],
      ["指挥员问答", "Agent 协作页问答面板", "截图 4-agents"],
      ["无人机管理页", "机群花名册与遥测", "截图 3-fleet"],
    ],
    [20, 46, 34]
  ),
  tableTitle("表4-2  术语口径核对"),
  table(
    ["术语", "正文口径"],
    [
      ["FLP（火情负荷）", "综合面积、燃料、坡度、风速的处置负荷值，界面同时给平方米直读"],
      ["SOC", "无人机电量百分比；预计返航 SOC ≥ 25% 为硬约束"],
      ["W20 / C6", "水剂（植被火）与二氧化碳药剂（电气/设备火），同架次不混装"],
      ["三态结论", "可控 / 可维持压制 / 不可控（请求增援），与缺口原因码同源输出"],
      ["审批门", "生成方案不等于执行；批准、调整、驳回、终止全程留痕"],
      ["轮次", "每 5 分钟一轮的火势、电量、药剂与机群状态反馈"],
    ],
    [26, 74]
  ),
];

const doc = new Document({
  styles: { default: { document: {
    run: { font: F.song, size: 24, color: "000000" },
    paragraph: { spacing: { line: 312 } },
  } } },
  sections: [{
    properties: { page: {
      size: { width: 11906, height: 16838 },
      margin: { top: 1417, bottom: 1417, left: 1701, right: 1417 },
    } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, font: F.song })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("written", OUT); });
