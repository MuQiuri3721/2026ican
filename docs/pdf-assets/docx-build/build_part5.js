// 第五部分 创新与验证 — docx 初稿生成（Profile A 正式排版）
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, Header, Footer, PageNumber, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType,
} = require("docx");
const fs = require("fs");
const { imageSize } = require("image-size");

const ROOT = "E:/开发/2026ican";
const OUT = `${ROOT}/docs/pdf-assets/火巡智策_第五部分_创新与验证_初稿.docx`;

// ---------- 组件 ----------
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
// segs: [text, bold?]
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
function tcell(text, { bold = false, fill = null, w = null, align = AlignmentType.LEFT } = {}) {
  return new TableCell({
    children: [new Paragraph({ alignment: align, spacing: { line: 280 },
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

// ---------- 正文 ----------
const children = [
  h1("五、创新与验证"),

  h2("5.1 核心创新"),
  body([["本系统的创新不在单一识别模型，而在于把视觉理解、真实环境、机群资源与确定性决策组织为一个可审批、可执行、可重规划的闭环处置体系。"]]),
  body([["（一）从识别到闭环处置。", true], ["常见识别系统产出单次告警，处置衔接靠人工。本系统将报警、感知、研判、调度、审批、执行与复盘连为持续任务链：方案按版本管理，每五分钟反馈火势与机群状态，异常自动触发", false], ["重规划", false], ["，任务结束自动归档，火情处置从\u201c看一次\u201d变为\u201c管到底\u201d。"]]),
  body([["（二）模型理解与规则决策分离。", true], ["大模型直接给出处置数字存在幻觉风险。本系统中 VLM 只产出结构化视觉观察并经契约守卫校验，火情负荷、电量、药剂与时间全部由冻结规则计算，界面逐项标注数字来源，模型无法越过规则拍板。"]]),
  body([["（三）真实环境进入调度。", true], ["环境数据在许多系统中只是背景展示。本系统把坡度、燃料与实测风速接入火情负荷计算，水源按六项条件参与补给决策，环境快照与方案版本绑定、可按当时环境复算，真实环境由此成为决策变量。"]]),
  body([["（四）三子群动态协同。", true], ["固定编队难以跟随火情变化。本系统按 2 侦察＋6 灭火＋4 支援三子群动态编组，疏导、补给、故障接替与返航换电自动重组，方案与关键调整始终经人工审批门确认。"]]),
  body([["由此，系统从\u201c识别一次火情\u201d扩展为\u201c处置一场火灾\u201d：识别的结果不再是一段告警信息，而是一条有人把关、可审计、能跟随火情滚动推进的处置任务。"]], { after: 120 }),
  figure(`${ROOT}/docs/pdf-assets/fig5-1.png`, 580),
  caption("图5-1  从单点识别到闭环协同处置的能力扩展"),

  h2("5.2 场景验证"),
  body([["场景验证回答同一个问题：火情、人员、约束、电量与库存变化时，系统能否形成正确且互不相同的闭环决策。六类业务场景覆盖全部关键变化维度（见表5-1），每组均在浏览器端真实执行并留存截图与事件记录。"]]),
  tableTitle("表5-1  六类业务场景与系统行为"),
  table(
    ["场景", "关键输入", "系统行为与证据"],
    [
      ["S1 一般林地·无人", "一般火情，资源充足", "侦察/灭火/物流编组出动，输出可控方案与处置时间窗"],
      ["S2 发现人员", "人员确认存在", "支援机执行通信广播与疏散引导，灭火机留守保护疏散通道"],
      ["S3 用户调整", "限制出动数量或修改目标时限", "生成新方案版本，资源与时间变化以调整事件留痕"],
      ["S4 SOC 不足", "航程后接近返航阈值", "自动返航充电或换电、备机接替，返航 SOC 不低于 25%"],
      ["S5 库存不足", "药剂或备用电池不足", "输出资源缺口与不可控结论，不给出虚假完成时间"],
      ["S6 拒绝方案", "驳回或终止", "释放资源锁并归档任务状态，处置原因必填留痕"],
    ],
    [22, 30, 48]
  ),
  body([["三组代表结果取自冻结场景当日重跑的轮次账本，曲线见图5-2。"]], { after: 40 }),
  figure(`${ROOT}/docs/pdf-assets/fig5-2.png`, 580),
  caption("图5-2  典型场景与系统验证结果（左：六类场景；中：三组真实重跑曲线；右：工程门禁）"),
  body([["（一）正常小火：闭环收敛。", true], ["初始 45 FLP 的一般火情，系统规划出动 8 架（灭火作业 4 架），首轮压制 27.8 FLP（同期自然增长约 0.3），次轮火势负荷降至 0 并自动扑灭归档。调度规模、药剂消耗与处置时间窗全部闭合。"]]),
  body([["（二）补给间歇：真实后勤循环。", true], ["600 平方米火情限 2 架出动，灭火机喷洒后须返航补水充电，12 轮净变化呈\u201c降-降-增\u201d三轮周期：作业轮强压、补给轮弱压、充电轮短暂回升，机群归位后再次压低。曲线如实出现回升，结论诚实标注\u201c可维持压制\u201d，未虚构单调下降。"]]),
  body([["（三）资源不足：诚实增援。", true], ["7200 FLP 大火远超机群压制能力，系统不生成虚假时间窗，而是给出\u201c不可控\u201d结论与缺口原因（压制能力不足），建议请求增援。三种火情分别得到可控、可维持、不可控三态结论，决策随资源与火情真实变化。"]], { after: 160 }),

  h2("5.3 工程验证"),
  body([["数值一致性", true], ["由统一分钟推进回归保证：同一任务连续推进 10 分钟与分两次 5＋5 分钟推进结果一致；1 分钟与 8 分钟航程给出不同返航时刻；合法的零增长率不再被默认值覆盖，全链火势增量为零。"]]),
  body([["资源守恒", true], ["按轮次账本核验：水剂按升、二氧化碳药剂按千克分键计量，消耗、补给与库存逐轮守恒且不为负；每架次预计返航 SOC 不低于 25% 的硬约束在方案与执行两侧同时校验。"]]),
  body([["数据有效性", true], ["以对照测试锁定：改变坡度、植被或风速会相应改变火情负荷；替换合格水源会改变补给选择；环境快照与方案版本绑定，历史方案可按当时环境复算。"]]),
  body([["模型与接口", true], ["行为如实呈现：VLM 真实调用、限流回退与失败状态分列展示，检测零框时如实回落并标注；接口契约禁止模型输出火情负荷、调度等关键数值，来源标注贯穿界面、报告与事件流。"]]),
  body([["系统门禁", true], ["在提交前统一实跑：后端规则回归 pytest 193 项全部通过，后端语法检查与前端生产构建零错误，浏览器场景 23 轮全部通过、六场景专项验收 6/6；视觉模型指标单独引用训练评测——自训 YOLO11n 在 D-Fire 官方测试集 4,306 张上 mAP50 0.665、单帧推理 1.4 毫秒。平台功能通过与模型识别精度分列表述，不互相替代；上述证据汇总于图5-2 右栏。"]], { after: 160 }),

  // 附录：最终测试结果表
  new Paragraph({
    heading: HeadingLevel.HEADING_2, pageBreakBefore: true,
    spacing: { before: 120, after: 140 },
    children: [new TextRun({ text: "附录  最终测试结果表（队员核对用，非正文）", bold: true, size: 28, color: "000000", font: F.hei })],
  }),
  body([["下表全部数字来自 2026-09-20 当日统一实跑，均可由命令输出复核。"]], { noIndent: false }),
  tableTitle("表5-2  提交前统一实跑记录"),
  table(
    ["验证项", "命令 / 方式", "结果"],
    [
      ["后端规则回归", "pytest -q", "193 passed（26.8s）"],
      ["后端语法检查", "python -m py_compile main.py pipeline.py", "通过"],
      ["前端生产构建", "npm run build", "通过（零错误）"],
      ["浏览器场景", "e2e/_suite_runner.py（R1-R23）", "23/23 全过"],
      ["六场景专项验收", "e2e/acceptance_six.py", "6/6 通过（截图归档 e2e/artifacts/j1）"],
      ["冻结场景复跑", "data/frozen_scenarios A/B/C 经 API 重跑", "A 扑灭归档 / B 可维持压制 / C 不可控增援"],
      ["视觉模型评测", "eval_dfire.py（D-Fire 官方测试集）", "mAP50 0.665，smoke 0.72 / fire 0.61，单帧 1.4ms"],
    ],
    [24, 40, 36]
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
    children: children.filter(Boolean),
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log("written", OUT); });
