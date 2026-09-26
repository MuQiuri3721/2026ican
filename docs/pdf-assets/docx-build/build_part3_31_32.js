// 3.1 感知层 / 3.2 理解层 — docx 初稿生成（Profile A 正式排版，风格同 build_part4）
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, Header, Footer, PageNumber, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType,
} = require("docx");
const fs = require("fs");
const { imageSize } = require("image-size");

const ROOT = "E:/开发/2026ican";
const OUT = `${ROOT}/docs/pdf-assets/火巡智策_3.1感知层与3.2理解层_初稿.docx`;

const F = { hei: { ascii: "Times New Roman", eastAsia: "SimHei" }, song: { ascii: "Times New Roman", eastAsia: "SimSun" } };

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2, keepNext: true,
    spacing: { before: 280, after: 140, line: 360, lineRule: "atLeast" },
    children: [new TextRun({ text, bold: true, size: 30, color: "000000", font: F.hei })],
  });
}
function sub(text) {
  // 内部短标题（（一）（二）（三））：加粗不进目录
  return new Paragraph({
    keepNext: true,
    spacing: { before: 200, after: 80, line: 312 },
    children: [new TextRun({ text, bold: true, size: 24, color: "000000", font: F.hei })],
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
    alignment: AlignmentType.CENTER, spacing: { before: 80, after: 240, line: 312 },
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
    children: [new Paragraph({ spacing: { line: 312 },
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
function codeLine(text) {
  return new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { line: 312, after: 60 },
    indent: { left: 480 },
    children: [new TextRun({ text, size: 20, color: "333333", font: { ascii: "Courier New", eastAsia: "SimSun" } })],
  });
}

const children = [
  h2("3.1 感知层——采集识别"),
  body([["感知层承担从报警到结构化检测结果的完整职责：用户报警地点触发侦察任务，侦察无人机抵达现场获取航拍图像，PWM-Net 在航拍影像上完成火焰与烟雾目标检测，结构化检测结果连同来源与状态标记，一并传递给理解层进行火情语义研判。"]]),

  sub("（一）航拍图像输入"),
  body([["火情报警中携带的地理位置是感知链路的起点。系统依据报警地点规划侦察任务，从无人机资源池中选择状态健康的侦察单元（R1/R2）获取现场航拍图像。感知入口支持单张图像与连续图像序列两种形态：单张图像用于火情首报的快速确认，连续序列按采集时间排列，为后续理解层的趋势判断提供时间依据。每张图像入库时同步保存任务编号、图像编号、采集时间与采集位置等基本上下文，作为只读信息贯穿后续处理链路。在竞赛演示环境中，页面图片上传接入的是同一条检测链路，属于演示输入方式，不涉及另一套算法。"]]),

  sub("（二）PWM-Net 检测"),
  body([["航拍森林火灾检测存在三重难点：目标尺度变化大（远距小火点与近距大面积火场并存）、烟雾边界模糊半透明、林区纹理与山影持续干扰。"]]),
  body([["感知层采用 PWM-Net 应对：以 YOLOv11n 为基础架构，主干替换为 ", false], ["PartialNet", true], ["，以部分通道注意力突出火焰与烟雾的关键语义通道；颈部嵌入 ", false], ["WTConv", true], [" 小波频域卷积，扩大感受野以联合增强烟雾的大尺度形态与火焰的高频边缘；检测头前引入 ", false], ["M2S", true], [" 多谱多尺度注意力，按低中高三谱带分解特征并生成门控，与三级空间尺度交互，兼顾局部细节与全局语义。"]]),
  body([["模型职责仅为火焰与烟雾两类目标检测，输出类别、检测框与置信度；真实火场面积、增长率与调度方案由后续层计算。模型参数量 7.8M，论文完整训练设置下在两个数据集上的精度指标如下表所示（推理速度为 RTX 4090、batch=1、FP32 桌面实测条件，不代表无人机机载端部署速度）："]], { after: 40 }),
  tableTitle("表 3-1  PWM-Net 在公开数据集上的检测精度（三轮训练均值±标准差）"),
  table(
    ["评测数据集", "mAP@50", "mAP@50:95"],
    [
      ["D-Fire（公开数据集）", "81.3±0.18%", "53.7±0.22%"],
      ["CQ-Fire（自建数据集）", "88.6±0.21%", "70.4±0.26%"],
    ],
    [40, 30, 30],
  ),
  body([["推理性能：RTX 4090、batch=1、FP32 条件下实测 145 FPS。上述结果为论文报告的完整训练设置产物；部署侧检测服务以独立进程接入，单帧推理延迟与调用状态经接口实时上报，前端如实展示。"]], { after: 40 }),
  figure(`${ROOT}/docs/图3-1_PWM-Net检测流程与结果.png`, 590),
  caption("图 3-1  PWM-Net 森林火灾航拍检测流程与结果"),

  sub("（三）结构化输出"),
  body([["检测模型以独立服务进程接入，输出结构化结果：单条检测含类别（class_name）、像素坐标框（box）与置信度（confidence），响应携带图像宽高并声明模型代号（model：pwm-yolo）与来源（source）。检测结果与任务编号、图像编号（image_ids）、采集时间（captured_at）等上下文构成完整感知记录，状态字段如实标记调用来源。真实调用返回样例（节选）："]]),
  codeLine('{"detections": [{"class_name": "smoke", "confidence": 0.757, "box": [21, 6, 706, 303]},'),
  codeLine('  {"class_name": "fire", "confidence": 0.341, "box": [322, 276, 349, 299]}],'),
  codeLine('  "image_width": 707, "image_height": 500,'),
  codeLine('  "source": "local-yolo-service", "model": "pwm-yolo"}'),
  figure(`${ROOT}/docs/素材_检测样例_检测图.jpg`, 420),
  caption("图 3-3  检测样例：原始航拍图与 PWM-YOLO 检测结果对照（本系统实测）"),
  body([["感知层回答的是\u201c图中有什么\u201d：火焰与烟雾在哪个位置、置信程度如何。但目标级结果仍缺乏业务语义——火势是在发展还是已被压制、现场是否存在人员风险，这些问题需要结合图像语义与时间上下文才能回答，由理解层完成。"]]),

  h2("3.2 理解层——火情研判"),
  body([["理解层解决从\u201c检测到目标\u201d到\u201c形成火情观察\u201d的语义鸿沟：航拍图像、PWM-Net 检测结果与上一轮结构化观察一同送入视觉语言模型，经过结构化理解、契约校验与来源标记，产出火情状态、烟雾趋势与人员观察等可供业务链直接使用的结构化火情观察。"]]),

  sub("（一）多模态信息输入"),
  body([["理解层的输入包含三类信息：其一，原始航拍图像或按采集时间排序的连续图像序列；其二，PWM-Net 输出的结构化检测结果；其三，上一轮产出的结构化观察。任务编号、轮次、图像编号（image_ids）、采集时间与环境摘要作为只读上下文注入，用于身份对齐与情境理解，其中的数值不参与模型的语义判断。多图输入严格按采集时间顺序进行，模型仅在存在多帧序列或上一轮观察记录时才输出时间维度的趋势判断，单图输入不会凭空产生趋势结论。需要特别强调的是，GIS 数据、传感器读数与检测模型输出的原始数值属于确定性数据，视觉模型不得改写。"]]),

  sub("（二）结构化火情理解"),
  body([["理解层的职责为明确可检查的业务项。火焰：判断可见性（fire_presence）、影响层级（affected_layer）与树冠卷入（canopy_involvement）。烟雾：给出浓度视觉等级（smoke_density）、图像平面漂移（image_plane_drift），连续输入时输出跨轮趋势（temporal_trend）。人员：识别现场人员线索，未观察到只能记 not_observed，不得写成\u201c确认无人\u201d——这是人员安全的关键措辞约束。模型另输出视觉规模（visual_scale：small/medium/large），仅描述画面占比，不解释为真实平方米面积。"]]),
  body([["不确定性同样显式标记：证据不足、图像质量与人工复核需求均有对应字段。全部输出遵循 vlm-analysis-v1 契约：图片质量、火情观察、烟雾趋势、对象线索（人员/道路/建筑/电力/水源/障碍物，各含状态与证据）与复核字段组，每项线索附文本证据。"]]),

  sub("（三）可信结果输出"),
  body([["理解层接入模型为 glm-4.6v-flash，提示词为冻结的 prompt-v4，输出契约 vlm-analysis-v1。工程守卫链：JSON 解析→字段与枚举校验→禁止项过滤（火情负荷、SOC、药剂、无人机数量等安全关键数字不得由视觉模型输出或覆盖）→缺字段定向修复重试一次，仍缺则如实呈现稀疏载荷。运行器注入 model、source、mode、analyzed_at，前端如实展示 real/fallback/failed 三态，回退不冒充真实结果。"]]),
  body([["交付实测：48 次调用内容正确 77/85（90.6%），红线 0 违规，响应中位数 19 秒。已知短板如实：水源线索漏检、画质自评偏乐观——两项仅作展示线索，水源决策走 GIS 与规则引擎。"]]),
  figure(`${ROOT}/docs/图3-2_VLM工程链路图.png`, 590),
  caption("图 3-2  VLM 火情结构化理解与可信输出链路"),
  body([["视觉模型只解释图像语义；FLP、SOC、药剂、无人机数量与处置时限等安全关键数字由确定性规则引擎计算。感知层回答\u201c图中有什么\u201d，理解层回答\u201c发生了什么\u201d——原始航拍图像至此成为可供控制层决策的结构化火情观察。"]]),
];

const doc = new Document({
  styles: { default: { document: { run: { font: F.song, size: 24 } } } },
  sections: [{
    properties: {
      page: { size: { width: 11906, height: 16838 }, margin: { top: 1417, bottom: 1417, left: 1701, right: 1417 } },
    },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "火巡智策 · 第三部分 技术内容（3.1/3.2 章节初稿）", size: 18, color: "888888", font: F.song })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(OUT, buffer);
  console.log("saved:", OUT);
});
