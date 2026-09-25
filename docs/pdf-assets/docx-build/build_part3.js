// 第三部分 3.3–3.6 协同·控制·执行·反馈复盘 — docx 生成（沿用 build_part4 排版风格）
const {
  Document, Packer, Paragraph, TextRun, ImageRun,
  AlignmentType, HeadingLevel,
} = require("docx");
const fs = require("fs");
const { imageSize } = require("image-size");

const ROOT = "E:/开发/2026ican";
const A = `${ROOT}/docs/pdf-assets`;
const EV = `${A}/evidence`;
const OUT = `${A}/火巡智策_第三部分_3.3至3.6_正文.docx`;

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
function h3(text) {
  return new Paragraph({
    keepNext: true,
    spacing: { before: 200, after: 100, line: 340, lineRule: "atLeast" },
    children: [new TextRun({ text, bold: true, size: 24, color: "000000", font: F.hei })],
  });
}
function body(text, opts = {}) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    indent: opts.noIndent ? undefined : { firstLine: 480 },
    spacing: { line: 312, after: opts.after ?? 60 },
    children: [new TextRun({ text, bold: !!opts.bold, size: 24, color: "000000", font: F.song })],
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
    keepNext: true,
    alignment: AlignmentType.CENTER, spacing: { before: 160, after: 40 },
    children: [new ImageRun({ data: buf, transformation: { width: w, height: h }, type: "png" })],
  });
}

const children = [];

/* ============ 3.3 协同层——多源融合 ============ */
children.push(h2("3.3 协同层——多源融合"));
children.push(body("协同层接收报警地点、航拍影像与用户要求，把地形、气象、植被、水源、道路、机群与库存等多源信息组织成一份来源明确、单位统一、可随方案版本追踪的任务态势，交由控制层计算。", { noIndent: true }));
children.push(h3("（一）环境信息汇聚"));
children.push(body("系统以报警地点或经纬度为入口，在事发点周边关联紫金山示范林区的地理与气象条件：SRTM 30 米高程、坡度与坡向刻画地形起伏；ESA WorldCover 土地覆盖给出可燃植被类别；Open-Meteo 提供风速、风向、温度、湿度与降水；OpenStreetMap 给出水体、取水候选与道路网；高德地图承担地点解析、底图与空间交互。全部数据支持在线与离线两种工作方式：示范林区范围内离线成果优先，范围外自动回退在线查询，断网时降级演示数据。每项结果同时保留来源、方式、采集时间、坐标系与状态，过期数据带陈旧标记，使环境信息既能进入规则计算，也可事后追溯。"));
children.push(h3("（二）机群资源状态汇聚"));
children.push(body("机群采用 2+6+4 编成共 12 架无人机：R1—R2 侦察、E1—E6 灭火、S1—S4 支援，其中 S3/S4 具备多用途能力、可参与直接压制。系统逐架记录位置、电量（SOC）、健康度、信号强度、飞行速度、载荷模块与机载药剂；库存同步管理 W20 水剂（以升计）、C6 二氧化碳（以千克计）、备用电池与支援物资。用户提出的目标处置时间、最大出动数与禁用设备作为约束条件一并进入任务态势。"));
children.push(h3("（三）统一任务态势"));
children.push(body("协同层对不同来源的字段、单位与时间统一后，形成火情、环境、人员、资源、约束五类状态。每次环境刷新生成一份不可变的环境快照（以内容哈希为标识），方案版本绑定其生成时的快照：新观测产生新快照，新方案引用新快照，历史方案保留原决策依据。六个智能体角色通过共享黑板读取同一份结构化上下文，保证侦察、灭火、支援与审批角色使用同一口径。"));
children.push(body("统一任务态势完成后，控制层进一步预测火势发展，并生成满足多重约束的调度方案。"));

children.push(figure(`${A}/fig3-3.png`, 620));
children.push(caption("图3-3 多源环境与资源态势融合机制"));

/* ============ 3.4 控制层——预测调度 ============ */
children.push(h2("3.4 控制层——预测调度"));
children.push(body("控制层接收协同层输出的统一任务态势，由确定性规则完成火势预测、约束校验、候选评分与结论裁决，九步技能链固定执行顺序：火情感知、环境评估、火情评估、人员评估、候选生成、约束过滤、调度评分、审批准备与报告归档。全部安全关键数字可复算，多智能体负责组织工具调用、分工与解释。", { noIndent: true }));
children.push(h3("（一）火势负荷与发展预测"));
children.push(body("火场以一百平方米网格组织，每格以火情负荷 FLP 表示处置负荷：B_i = 10 × I_i × K_fuel × K_wind × K_slope。其中火焰强度来自视觉研判，三个修正因子取自环境快照——植被类别映射 K_fuel（疏草 0.8、一般林地 1.0、致密可燃物 1.3），风速分档映射 K_wind（4 米/秒以内 1.0，4—6 米/秒 1.2，6 米/秒以上 1.5），坡度映射 K_slope（15°以内 1.0，15°—30° 1.15，30°以上 1.3）。火势按统一分钟核心推进：FLP_(t+1) = FLP_t × (1 + g/60) − S_t，每分钟同时记录自然增长、有效压制与净变化，压制量由喷洒量、药剂效率与天气修正相乘得到。该层输出当前负荷、发展趋势、重点方向与控制时间区间。"));
children.push(h3("（二）候选方案生成与约束校验"));
children.push(body("系统并不默认派出全部无人机，而是在出动上限内枚举全部候选组合并逐一校验。过滤先行：故障、健康度不足、电量不足、药剂不匹配或航程不可行者直接淘汰；电量执行三条阈值——执行新任务不低于 35%、返航不低于 25%、应急预留 15%。药剂严格匹配：W20 水剂用于植被火，C6 二氧化碳用于电气、油类热点，同一架次不混装，消耗分别以升和千克记账。取水水源须同时满足可用、安全、容量、路线、取水后电量与补给收益六项条件。人员状态进入方案分支，决定疏散保护与机动预留。每个候选组合经统一分钟核心预测 120 分钟处置过程，再按时间 0.40、负荷 0.30、能耗 0.15、物资 0.10、轮次变化 0.05 的权重评分，输出推荐方案与备选方案。当压制持续不足且证据成立时，出动上限自动由 4 架放宽至编成上限 8 架，扩编方案仍需再次确认。"));
children.push(h3("（三）三态决策与用户确认"));
children.push(body("结论统一为三态：可控制（输出时间区间）、维持压制（时限内未完成）、不可控制（同时列明资源缺口）。方案内容包括机群任务分配、药剂、作业高度、到场顺序、补给方式与控制时间区间。多智能体按九步链路分工协作，FLP、SOC、药剂、数量与时间等数字全部出自规则引擎。方案生成后进入待确认（awaiting_confirmation）状态，由用户批准、调整或拒绝；批准后锁定资源进入执行，拒绝须填写原因并留痕。"));
children.push(body("上述 FLP 与分钟推进公式使“火有多大、还在长多大、能否压住”全部可复算。方案经用户确认后转入执行层，由三类无人机子群按照任务编组协同处置。"));

children.push(figure(`${A}/fig3-4.png`, 620));
children.push(caption("图3-4 火势预测与多约束调度决策机制"));
children.push(figure(`${EV}/e34-plan-summary.png`, 560));
children.push(caption("图3-4a 方案摘要与数字来源标注（平台界面截图）"));

/* ============ 3.5 执行层——协同处置 ============ */
children.push(h2("3.5 执行层——协同处置"));
children.push(body("执行层把确认后的方案转换为侦察、压制、疏散、通信与补给任务，锁定相应资源后按分钟推进；平台实时展示每架无人机的执行状态与资源消耗。", { noIndent: true }));
children.push(h3("（一）2+6+4 任务编组"));
children.push(body("R1 承担全程主监测，火情升至 III 级时 R2 加入复核，侦察子群持续回传图像与火情变化。E1—E6 依载荷模块执行火线压制、重点热点处置与疏散通道保护，按方案分批到场。S1—S4 承担通信中继、广播照明、人员指引、药剂与电池运输和后备侦察，S3/S4 可作为多用途力量直接参与压制。每架无人机独立记录位置、电量、机载药剂与状态，避免把子群抽象成一台机器。任务分配与状态变化实时上图，指挥员可逐架核查。"));
children.push(h3("（二）人员状态驱动的处置分支"));
children.push(body("机群任务随人员信息动态调整优先级：确认有人时，支援机执行广播、照明与疏散路线引导，灭火编队保留一架电量最低的灭火机专门保护疏散通道；确认无人时，支援机转向通信中继、物资运输、电池前送与补水保障；状态不明时，侦察与支援力量先行复核，并减少出动上限以保留机动资源。人员状态一旦变化，作为重规划事件进入反馈复盘层。"));
children.push(h3("（三）交替作业与轮换补给"));
children.push(body("无人机依剩余药剂、电量、航程与预计接替时间错峰返航，避免压制编队同时退出火线。单机依次经历飞行、作业、返航、补给与再次出动状态，分钟核心同步更新电量与药剂余量：基地补水按升扣减水剂库存并消耗 W20 模块，C6 按千克更换模块，更换电池将电量恢复至 95% 并扣减电池库存，就地取水仅在批准水源处进行并扣减水源容量，余水回注与报废药剂同样入账。补给间歇允许火情短时回升；后备机与完成补给的无人机接替后继续压制，真实执行状态持续回传反馈复盘层。"));
children.push(body("执行状态与新观测持续回传至反馈复盘层，用于判断处置效果并触发后续调整。"));

children.push(figure(`${A}/fig3-5.png`, 620));
children.push(caption("图3-5 2+6+4 无人机子群协同处置机制"));
children.push(figure(`${EV}/e35-fleet-cards.png`, 560));
children.push(caption("图3-5a 机群状态卡片（平台界面截图）"));

/* ============ 3.6 反馈复盘层——闭环优化 ============ */
children.push(h2("3.6 反馈复盘层——闭环优化"));
children.push(body("反馈复盘层持续比较火情增长与有效压制，识别风变、人员变化、电量与资源事件，按需重构方案并再次确认；任务结束后沉淀全生命周期证据，使系统成为闭环而非一次性方案。", { noIndent: true }));
children.push(h3("（一）分钟推进与五分钟反馈"));
children.push(body("系统内部按 1 分钟推进火情、电量、药剂与无人机状态，前端按 5 分钟形成一个反馈轮次。每轮账本依次记录起始负荷（before）、自然增长（growth）、有效压制（suppression）、净变化（net）与结束负荷（after），满足“起始 + 增长 − 压制 = 结束”的守恒关系；同时记录作业中、返航中、补给中的无人机，W20 与 C6 消耗、库存变化与新观测校正。界面结论由账本直接判定：火情下降、补给间歇短时回升或持续增长，均有数字支撑。账本守恒与时间分片等价性（一个 10 分钟轮与十个 1 分钟轮结果严格一致）由自动化测试背书。"));
children.push(h3("（二）事件触发与方案重构"));
children.push(body("火情负荷超过方案基线 20%（下限 20 FLP）、风速跨档、人员状态变化、电量低于返航阈值、单机失能、信号下降、水源失效或连续三轮净增长时触发重规划。系统保存当前任务快照、调整资源锁、生成新的方案版本并记录触发原因；新方案绑定最新环境快照，重新进入用户确认门禁，确认后以新资源状态继续执行。关键事件可提前触发评估，不必机械等待完整轮次。压制持续不足三轮时，自动放宽出动上限至编成上限并再次提请确认。"));
children.push(h3("（三）任务回放与报告归档"));
children.push(body("任务报告保存输入文件哈希、视觉与环境数据来源标注、环境快照、全部方案版本、审批记录、逐轮账本、事件时间线、电量与两类药剂消耗、库存变化、最终控制结论与资源缺口。前端提供趋势曲线（重规划轮以金色标注）、逐轮回放、多任务对比与报告查看器；报告支持在线查看、原始数据下载与图文版导出，使每一次方案调整都可解释、可审计。"));
children.push(body("由此形成“感知理解—预测调度—协同处置—反馈优化—再次感知”的完整闭环。"));

children.push(figure(`${A}/fig3-6.png`, 620));
children.push(caption("图3-6 感知—执行—反馈—重规划闭环"));
children.push(figure(`${EV}/e36-analysis-replay.png`, 560));
children.push(caption("图3-6a 数据分析与逐轮回放（平台界面截图）"));

const doc = new Document({
  sections: [{
    properties: { page: { margin: { top: 1000, bottom: 1000, left: 1200, right: 1200 } } },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("written", OUT);
});
