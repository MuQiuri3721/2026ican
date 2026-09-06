# -*- coding: utf-8 -*-
"""
02_run_cases.py — 案例运行器（第1天下午核心任务）

做什么：
  按 data/vlm-testcases/cases.json 的案例定义，逐档（A/B/C）调用 glm-4.6v-flash，
  自动完成四层判卷并落盘：
    1) 调用与解析：JSON解析失败允许一次"只修复格式"的重试（prompt-v1 §一）
    2) 结构检查：必填字段 + 枚举取值 + 身份回显（task_id/轮次/图片编号照抄）
    3) 禁止项扫描：FLP/面积/风速/无人机调度/absent 等红线词
    4) 人工预期检查：cases.json 里每组的 checks_common / checks_extra
  每组案例生成 CASE-XXX/ 目录：images/ metadata.json expected.json mock_yolo.json
  runs/<档>/request.json(去Key) raw_response.json parsed.json + review.md

用法：
  python scripts/02_run_cases.py --cases CASE-001 CASE-002 ...
  （不带 --cases 则跑所有 tiers 非空的案例）
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import vlm_api  # noqa: E402
from vlm_api import (GAP_BETWEEN_CALLS, chat, image_to_data_url,  # noqa: E402
                     load_api_key, masked_request_sample)

RAW_DIR = ROOT / "data" / "vlm-testcases" / "_raw_images"
CASES_JSON = ROOT / "data" / "vlm-testcases" / "cases.json"
LOGS_DIR = ROOT / "logs"

# ============ 冻结的系统提示词（与 docs/vlm-delivery/prompt-v1.md §二 完全一致） ============
SYSTEM_PROMPT_V1 = '''你是森林火灾侦察视觉分析模块。你只负责从给定图片、PWM-YOLO检测结果和环境摘要中提取可见事实、趋势、冲突与不确定性。仅输出符合vlm-analysis-v1的JSON，不输出Markdown。禁止计算或编造FLP、火场平方米面积、风速、增长率、无人机数量、药剂量、SOC、路线和完成时间。未看到人员只能写not_observed，不能写absent。视觉水体只能写water_candidate。图像证据不足时写uncertain并列出missing_inputs。不得修改输入中的传感器、GIS或PWM-YOLO数值。human_summary只能复述结构化观察，不得新增数字或行动指令。

【vlm-analysis-v1 输出结构定义】
输出一个JSON对象，所有字段必须全部出现，取值只能从竖线分隔的选项中选一个，"..."表示填文字。未观察到时evidence填空字符串""。

{
  "schema_version": "vlm-analysis-v1",
  "task_id": "...（照抄输入的任务编号）",
  "round_index": 0（照抄输入的轮次数字）,
  "image_ids": ["..."]（照抄输入的图片编号列表）,
  "prompt_version": "v1",
  "image_quality": {
    "usable": true|false,
    "quality_level": "good|acceptable|poor",
    "problems": ["blurry|too_dark|overexposed|obstruction|low_resolution|none"],
    "missing_inputs": ["..."]（缺什么输入就写什么名字，没有就填[]）
  },
  "fire_observation": {
    "fire_presence": "flame_observed|smoke_only|none_observed|uncertain",
    "affected_layer": "ground|surface|canopy|mixed|not_determinable",
    "canopy_involvement": "observed|not_observed|uncertain",
    "visual_scale": "small|medium|large|not_determinable"
  },
  "smoke_trend": {
    "smoke_density": "none|light|medium|heavy",
    "image_plane_drift": "none_observed|left|right|up|down|variable|uncertain",
    "temporal_trend": "intensifying|weakening|stable|unclear|first_round_no_comparison"
  },
  "object_clues": {
    "people": {"state": "observed|not_observed", "evidence": "..."},
    "road": {"state": "observed|not_observed", "evidence": "..."},
    "building": {"state": "observed|not_observed", "evidence": "..."},
    "power_equipment": {"state": "observed|not_observed", "evidence": "..."},
    "water": {"state": "water_candidate|not_observed", "evidence": "..."},
    "obstacle": {"state": "observed|not_observed", "evidence": "..."}
  },
  "review": {
    "conflicts": ["..."]（图片与YOLO结果、或前后帧之间的矛盾，没有填[]）,
    "manual_review_required": true|false,
    "human_summary": "..."（两三句话，只能复述上面的观察，不得新增数字或行动指令）
  }
}

【取值边界】
- fire_presence：只在画面中能看到明火时选flame_observed；只看到烟没有火选smoke_only，不得凭烟推断明火。
- affected_layer：ground=地面腐殖质火、surface=地表灌木杂草火、canopy=树冠火、mixed=多层同时燃烧。
- visual_scale：只是画面中的视觉规模，与真实面积无关，禁止输出任何平方米数字。
- image_plane_drift：只是烟雾在画面平面上的移动方向，不是风向，禁止输出风速或真实风向。
- temporal_trend：只有一轮图片时必须选first_round_no_comparison；前后变化看不出时选unclear，不得强行判断。
- people.state：未看到人员只能not_observed，禁止absent。
- water.state：画面中的水体只能标记water_candidate，是否可取水不归你判断。
- conflicts中若YOLO检测结果与画面明显不符（如YOLO标了火焰但画面看不到），必须写明。'''

REPAIR_INSTRUCTION = ("你上一条回复不是合法JSON。请只修复格式：重新输出完整的一个JSON对象，"
                      "判断内容保持不变，不要任何解释文字，不要使用Markdown代码围栏。")

# ---- 提示词版本管理 ----
# v2试验版 = v1原文（骨架内版本号改为v2）+ 收尾格式硬性要求。
# 起因：v1实测10/10次输出```围栏（内容正确但违反"只允许纯JSON"），
# 依据方案5.3/冻结纪律：不改已冻结文本，递增版本号试验。
# v3定稿版 = v2 + 枚举字段归属规则。
# 起因：v2实测发现模型把first_round_no_comparison填进image_plane_drift
# （该值只属于temporal_trend），补一条取值归属说明。
# v4试验版 = v3 + 多图轮次趋势判断 + 树冠字段枚举补充。
# 起因：v3全量20次实测发现两个残留问题——
#   1) 时间对比组2/3案例temporal_trend仍填first_round_no_comparison
#      （系统提示词"只有一轮图片时必须选first_round_no_comparison"与
#        运行时多图说明冲突，系统提示词占上风，需在提示词内澄清）；
#   2) CASE-002C把not_determinable填进canopy_involvement
#      （该值只属于affected_layer/visual_scale）。
FENCE_RULE = ("\n\n【输出格式硬性要求】\n"
              "- 回复的第一个字符必须是\"{\"，最后一个字符必须是\"}\"。\n"
              "- 禁止使用```代码围栏，禁止输出JSON对象之外的任何文字。")
ENUM_RULE = ("\n\n【枚举取值归属】\n"
             "- first_round_no_comparison 只能填在 smoke_trend.temporal_trend。\n"
             "- smoke_trend.image_plane_drift 只能从 none_observed|left|right|up|down|variable|uncertain "
             "中选；单张图片看不出烟雾移动方向时填 uncertain。")
ENUM_RULE_V4 = ("\n\n【枚举取值归属】\n"
                "- first_round_no_comparison 只能填在 smoke_trend.temporal_trend。\n"
                "- smoke_trend.image_plane_drift 只能从 none_observed|left|right|up|down|variable|uncertain "
                "中选；单张图片看不出烟雾移动方向时填 uncertain。\n"
                "- fire_observation.canopy_involvement 只能从 observed|not_observed|uncertain 中选；"
                "not_determinable 只属于 affected_layer 和 visual_scale。")
FRAME_RULE = ("\n\n【多图轮次的趋势判断】\n"
              "- 本轮输入包含多张图片（帧序列）时，temporal_trend 必须比较帧间火势/烟量变化"
              "（intensifying|weakening|stable|unclear四选一），禁止填 first_round_no_comparison。\n"
              "- 只有当本轮仅有单张图片且上一轮分析为null时，才填 first_round_no_comparison。")


def system_prompt_for(version):
    if version == "v1":
        return SYSTEM_PROMPT_V1
    if version == "v2":
        return SYSTEM_PROMPT_V1.replace(
            '"prompt_version": "v1"', '"prompt_version": "v2"') + FENCE_RULE
    if version == "v3":
        return SYSTEM_PROMPT_V1.replace(
            '"prompt_version": "v1"', '"prompt_version": "v3"') + FENCE_RULE + ENUM_RULE
    if version == "v4":
        return SYSTEM_PROMPT_V1.replace(
            '"prompt_version": "v1"', '"prompt_version": "v4"') + FENCE_RULE + ENUM_RULE_V4 + FRAME_RULE
    sys.exit("[错误] 未知提示词版本: %r（支持 v1 / v2 / v3 / v4）" % version)

# ============ demo 输入占位（地理/气象队员交付前用，方案4.1） ============
SCENE_DEMO = {"林地类型": "针阔混交林（demo占位）", "坡度": "未知",
              "水源概况": "未知", "备注": "地理队员交付前使用demo摘要"}
WEATHER_DEMO = {"风": None, "能见度": None, "温度_c": None,
                "备注": "气象观测暂缺（demo占位）"}
CAMERA_NULL = {"无人机编号": None, "飞行高度_m": None, "航向": None,
               "镜头参数": None, "云台角度": None}

TIER_DESC = {
    "missing": "A档：无YOLO（yolo_status=missing）",
    "fixture_empty": "B档：空fixture（detections=[]，验证空结果不阻断观察）",
    "fixture": "C档：fixture含人工框（mode=fixture, source=manual_fixture）",
    "fixture_wrong": "C档：故意错误的fixture（画面无火却给火焰框，测矛盾上报）",
}

# ============ 枚举表（与提示词【输出结构定义】一一对应） ============
ENUMS = {
    "image_quality.quality_level": ["good", "acceptable", "poor"],
    "fire_observation.fire_presence": ["flame_observed", "smoke_only", "none_observed", "uncertain"],
    "fire_observation.affected_layer": ["ground", "surface", "canopy", "mixed", "not_determinable"],
    "fire_observation.canopy_involvement": ["observed", "not_observed", "uncertain"],
    "fire_observation.visual_scale": ["small", "medium", "large", "not_determinable"],
    "smoke_trend.smoke_density": ["none", "light", "medium", "heavy"],
    "smoke_trend.image_plane_drift": ["none_observed", "left", "right", "up", "down", "variable", "uncertain"],
    "smoke_trend.temporal_trend": ["intensifying", "weakening", "stable", "unclear", "first_round_no_comparison"],
}
PROBLEM_ITEMS = ["blurry", "too_dark", "overexposed", "obstruction", "low_resolution", "none"]
CLUE_STATES = {
    "people": ["observed", "not_observed"],
    "road": ["observed", "not_observed"],
    "building": ["observed", "not_observed"],
    "power_equipment": ["observed", "not_observed"],
    "water": ["water_candidate", "not_observed"],
    "obstacle": ["observed", "not_observed"],
}

# ============ 红线禁止项（方案5.1"禁止计算或编造"清单） ============
FORBIDDEN_PATTERNS = [
    (r"FLP|fire_cells|火势潜值", "FLP/火势潜值（后端专属）"),
    (r"平方米|平米|㎡|m²|km²|平方公里", "面积数字"),
    (r"风速|米/秒|米每秒|m/s", "风速"),
    (r"增长率|增速", "增长率"),
    (r"\d+\s*架|无人机数|无人机数量|SOC|续航|悬停|航线|飞行路线", "无人机调度信息"),
    (r"W20|药剂|灭火剂", "药剂量"),
    (r"灭火效率|控制时间|扑灭时间|完成时间", "效率/时间预估"),
    (r"absent", "absent（禁用词，应为not_observed）"),
    (r"可以取水|可取水|适合取水|适合灭火|水源可用", "取水判断"),
]


def sha16(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def get_field(obj, path):
    cur = obj
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None, False
        cur = cur[key]
    return cur, True


# ============ 输入构造 ============
def yolo_payload(tier_def, frames):
    """按方案3.2生成对应档位的PWM-YOLO输入。"""
    kind = tier_def["yolo"]
    if kind == "missing":
        return {"yolo_status": "missing", "note": "PWM-YOLO服务未接入，本轮无检测结果"}
    payloads = []
    for f in frames:
        detections = tier_def.get("detections", []) if f["order"] == 1 else []
        payloads.append({"schema_version": "yolo-observation-v1", "mode": "fixture",
                         "source": "manual_fixture", "frame_id": f["frame_id"],
                         "detections": detections})
    return payloads


def build_user_text(case, tier_def, frames):
    frame_ids = "、".join(
        "%s（相对时间%+d秒，第%d/%d张）" % (f["frame_id"], f["time_offset_s"],
                                          f["order"], len(frames))
        for f in frames)
    lines = [
        "任务信息：task_id=%s, round_index=%d, 报警地点=%s" % (
            case["task_id"], case["round_index"], case["task_name"]),
        "任务：分析第%d轮火场图片，并与上一有效轮次比较。" % case["round_index"],
        "图片顺序：%s" % frame_ids,
    ]
    if len(frames) > 1:
        # 多图案例（时间对比组）：temporal_trend应比较帧间变化，而非套用"首轮无比较"
        lines.append("说明：本轮含多张图片，按相对时间先后视为同一火场的帧序列；"
                     "temporal_trend请比较帧间火势/烟量变化（上一轮分析为null，无需与上一轮比较）。")
    lines += [
        "PWM-YOLO结果：%s" % json.dumps(yolo_payload(tier_def, frames), ensure_ascii=False),
        "相机与无人机元数据：%s" % json.dumps(CAMERA_NULL, ensure_ascii=False),
        "地理环境摘要：%s" % json.dumps(SCENE_DEMO, ensure_ascii=False),
        "气象观测：%s" % json.dumps(WEATHER_DEMO, ensure_ascii=False),
        "上一轮分析：null",
        "请严格按vlm-analysis-v1输出。",
    ]
    return "\n".join(lines)


def build_messages(case, tier_def, frames, prompt_version="v1"):
    parts = [{"type": "image_url",
              "image_url": {"url": image_to_data_url(RAW_DIR / f["file"])}}
             for f in frames]
    parts.append({"type": "text", "text": build_user_text(case, tier_def, frames)})
    return [{"role": "system", "content": system_prompt_for(prompt_version)},
            {"role": "user", "content": parts}]


# ============ 判卷 ============
def extract_json(text):
    t = (text or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        return None, "未找到JSON花括号"
    try:
        return json.loads(t[i:j + 1]), None
    except ValueError as e:
        return None, "json.loads失败: %s" % str(e)[:80]


def validate_structure(o):
    """必填字段 + 类型 + 枚举。返回问题描述列表（空=通过）。"""
    P = []
    for k in ["schema_version", "task_id", "round_index", "image_ids", "prompt_version",
              "image_quality", "fire_observation", "smoke_trend", "object_clues", "review"]:
        if k not in o:
            P.append("缺少顶层字段 %s" % k)
    if P:
        return P
    if o["schema_version"] != "vlm-analysis-v1":
        P.append("schema_version错误: %r" % o["schema_version"])
    if not isinstance(o["task_id"], str) or not o["task_id"]:
        P.append("task_id非字符串")
    if not isinstance(o["round_index"], int) or isinstance(o["round_index"], bool):
        P.append("round_index非整数")
    if not isinstance(o["image_ids"], list):
        P.append("image_ids非列表")
    if not isinstance(o["prompt_version"], str) or not o["prompt_version"]:
        P.append("prompt_version非字符串")

    iq = o.get("image_quality", {})
    if not isinstance(iq.get("usable"), bool):
        P.append("image_quality.usable非布尔")
    if not isinstance(iq.get("missing_inputs"), list):
        P.append("image_quality.missing_inputs非列表")
    if not isinstance(iq.get("problems"), list):
        P.append("image_quality.problems非列表")
    else:
        bad = [x for x in iq["problems"] if x not in PROBLEM_ITEMS]
        if bad:
            P.append("problems含非法项: %r" % bad)

    for path, allowed in ENUMS.items():
        v, ok = get_field(o, path)
        if not ok:
            P.append("缺少字段 %s" % path)
        elif v not in allowed:
            P.append("%s取值非法: %r" % (path, v))

    oc = o.get("object_clues", {})
    for name, allowed in CLUE_STATES.items():
        c = oc.get(name)
        if not isinstance(c, dict) or "state" not in c or "evidence" not in c:
            P.append("object_clues.%s结构不完整" % name)
            continue
        if c["state"] not in allowed:
            P.append("object_clues.%s.state非法: %r" % (name, c["state"]))
        if not isinstance(c["evidence"], str):
            P.append("object_clues.%s.evidence非字符串" % name)

    rv = o.get("review", {})
    if not isinstance(rv.get("conflicts"), list):
        P.append("review.conflicts非列表")
    if not isinstance(rv.get("manual_review_required"), bool):
        P.append("review.manual_review_required非布尔")
    if not isinstance(rv.get("human_summary"), str):
        P.append("review.human_summary非字符串")
    return P


def identity_echo(o, case, frames, version="v1"):
    """身份回显检查：task_id/轮次/图片编号必须照抄输入。"""
    P = []
    if o.get("task_id") != case["task_id"]:
        P.append("task_id未照抄: %r（应 %r）" % (o.get("task_id"), case["task_id"]))
    if o.get("round_index") != case["round_index"]:
        P.append("round_index未照抄: %r（应 %r）" % (o.get("round_index"), case["round_index"]))
    want = [f["frame_id"] for f in frames]
    got = o.get("image_ids")
    if not isinstance(got, list) or [str(x) for x in got] != want:
        P.append("image_ids与输入不符: %r（应 %r）" % (got, want))
    if version not in str(o.get("prompt_version", "")):
        P.append("prompt_version未标%s: %r" % (version, o.get("prompt_version")))
    return P


def scan_forbidden(text):
    hits = []
    for pattern, desc in FORBIDDEN_PATTERNS:
        m = re.search(pattern, text)
        if m:
            s, e = max(0, m.start() - 12), min(len(text), m.end() + 12)
            hits.append({"desc": desc, "snippet": text[s:e].replace("\n", " ")})
    return hits


def eval_check(o, check):
    """执行一条人工预期检查，返回 (是否通过, 实际值描述)。"""
    op = check["op"]
    if op == "usable_or_missing":
        usable, _ = get_field(o, "image_quality.usable")
        missing, _ = get_field(o, "image_quality.missing_inputs")
        return (usable is False or bool(missing)), "usable=%r, missing_inputs=%r" % (usable, missing)
    val, ok = get_field(o, check["field"])
    if not ok:
        return False, "字段缺失"
    if op == "eq":
        return val == check["value"], "实际 %r" % (val,)
    if op == "ne":
        return val != check["value"], "实际 %r" % (val,)
    if op == "in":
        return val in check["values"], "实际 %r" % (val,)
    if op == "nonempty":
        v = val.strip() if isinstance(val, str) else val
        return bool(v), "实际 %r" % (str(val)[:50],)
    if op == "empty":
        v = (val.strip() if isinstance(val, str) else val)
        return not v, "实际 %r" % (str(val)[:50],)
    if op == "contains_any":
        vals = val if isinstance(val, list) else [val]
        hit = [v for v in check["values"] if v in vals]
        return bool(hit), "实际 %r，命中 %r" % (val, hit)
    return False, "未知op: %r" % op


# ============ 案例目录 ============
def setup_case_dir(case, prompt_version="v1"):
    """确保 CASE-XXX/ 目录齐备（幂等），返回帧信息列表。"""
    case_dir = ROOT / "data" / "vlm-testcases" / case["case_id"]
    img_dir = case_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, img in enumerate(case["images"], 1):
        src = RAW_DIR / img
        if not src.exists():
            sys.exit("[错误] %s 缺图片 %s" % (case["case_id"], src))
        dst = img_dir / img
        if not dst.exists():
            shutil.copy2(src, dst)
        frames.append({"frame_id": "%s-R%d-F%d" % (case["case_id"], case["round_index"], i),
                       "file": img, "order": i,
                       "time_offset_s": 0 if i == 1 else 30 * (i - 1),
                       "sha256_16": sha16(src), "size_kb": round(src.stat().st_size / 1024)})
    metadata = {
        "case_id": case["case_id"], "scenario": case["scenario"],
        "task_id": case["task_id"], "task_name": case["task_name"],
        "round_index": case["round_index"], "prompt_version": prompt_version,
        "model": "glm-4.6v-flash", "temperature": 0.1, "max_tokens": 2048,
        "frames": frames,
        "source": case.get("source"), "license": case.get("license"),
        "source_note": case.get("source_note"),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    (case_dir / "metadata.json").write_text(dumps(metadata), encoding="utf-8")

    exp_path = case_dir / "expected.json"
    if not exp_path.exists():  # 人工预期一经写出不自动覆盖
        expected = {
            "case_id": case["case_id"],
            "verified": {"date": "2026-09-06", "method": "人工看图核验（视觉工具辅助）",
                         "basis": case.get("verification", "")},
            "checks_common": case.get("checks_common", []),
            "checks_extra": case.get("checks_extra", {}),
            "auto_checks": "结构/枚举/身份回显/禁止项扫描由02_run_cases.py自动执行，不在本文件重复",
        }
        exp_path.write_text(dumps(expected), encoding="utf-8")

    (case_dir / "mock_yolo.json").write_text(dumps({
        "note": "各档位的PWM-YOLO输入定义（人工fixture，非PWM-YOLO真实输出）",
        "tiers": {td["tier"]: yolo_payload(td, frames) for td in case.get("tiers", [])},
    }), encoding="utf-8")
    return frames


# ============ 单档执行 ============
def run_tier(api_key, case, tier_def, frames, case_dir, prompt_version="v1"):
    tier = tier_def["tier"]
    kind = tier_def["yolo"]
    # v1证据存runs/<档>；试验版存runs/<档>-pN（如A-p2、A-p3），互不覆盖
    label = tier if prompt_version == "v1" else "%s-p%s" % (tier, prompt_version[-1])
    messages = build_messages(case, tier_def, frames, prompt_version)
    user_text = build_user_text(case, tier_def, frames)

    print("  [%s|Tier %s] 调用中..." % (case["case_id"], label), flush=True)
    res = chat(api_key, messages)
    repair_used = False
    parsed, parse_err = None, None

    if res["success"]:
        parsed, parse_err = extract_json(res["content"])
        if parsed is None:
            print("      ...JSON解析失败，发起一次格式修复重试（prompt-v1允许一次）", flush=True)
            time.sleep(GAP_BETWEEN_CALLS)
            res2 = chat(api_key, messages + [
                {"role": "assistant", "content": res["content"]},
                {"role": "user", "content": REPAIR_INSTRUCTION}])
            if res2["success"]:
                parsed, parse_err = extract_json(res2["content"])
                repair_used = True
                res = res2  # 以修复轮为准留档
            else:
                res = res2
                repair_used = True

    # ---- 判卷 ----
    structural = []
    if "```" in res["content"]:
        structural.append("输出包含Markdown代码围栏(```)")
    if parsed is None:
        structural.append("JSON无法解析: %s" % parse_err)
    else:
        structural += validate_structure(parsed)
        structural += identity_echo(parsed, case, frames, prompt_version)
    forbidden_hits = scan_forbidden(res["content"]) if res["content"] else []

    checks = list(case.get("checks_common", [])) + list(case.get("checks_extra", {}).get(tier, []))
    check_results = []
    for c in checks:
        ok, actual = (eval_check(parsed, c) if parsed is not None else (False, "模型输出未解析"))
        check_results.append({"desc": c["desc"], "expr": "%s %s %s" % (
            c["field"], c["op"], c.get("value") or c.get("values") or ""), "pass": ok, "actual": actual})

    if not res["success"]:
        verdict = "FAILED_API"
    elif parsed is None:
        verdict = "FAIL_STRUCTURE"
    elif structural or forbidden_hits:
        verdict = "FAIL"
    elif all(r["pass"] for r in check_results):
        verdict = "PASS"
    else:
        verdict = "FAIL"

    # ---- 落盘 ----
    tdir = case_dir / "runs" / label  # v1存runs/<档>，v2试验存runs/<档>-p2，不覆盖v1证据
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "request.json").write_text(dumps({
        "note": "已去除Key与Base64图片数据（方案红线：任何Key不入库）",
        "request": masked_request_sample(messages), "user_text": user_text,
    }), encoding="utf-8")
    (tdir / "raw_response.json").write_text(dumps({
        "called_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "http_status": res["http_status"], "latency_ms": res["latency_ms"],
        "retries_used": res["retries_used"], "format_repair_retry_used": repair_used,
        "usage": res["usage"], "error": res["error"],
        "content_raw": res["content"],   # 模型原始输出，一字不改（方案红线：不人工改写）
    }), encoding="utf-8")
    if parsed is not None:
        final = dict(parsed)
        final["yolo_status"] = "missing" if tier == "A" else "fixture"
        final["mode"] = None if tier == "A" else "fixture"
        final["source"] = None if tier == "A" else "manual_fixture"
        final["model"] = res["model"]
        final["analyzed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (tdir / "parsed.json").write_text(dumps(final), encoding="utf-8")

    npass = sum(1 for r in check_results if r["pass"])
    print("      -> %s（预期检查 %d/%d，结构问题 %d 项，禁止项 %d 处）" % (
        verdict, npass, len(check_results), len(structural), len(forbidden_hits)), flush=True)

    return {"tier": tier, "label": label, "kind": kind, "verdict": verdict,
            "prompt_version": prompt_version, "res": res,
            "repair_used": repair_used, "structural": structural,
            "forbidden_hits": forbidden_hits, "check_results": check_results}


def write_review(case, frames, tier_results, case_dir):
    L = []
    L.append("# %s 测试记录（02_run_cases.py 自动生成）" % case["case_id"])
    L.append("")
    L.append("- 生成时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("- 模型: glm-4.6v-flash | 提示词: %s | temperature 0.1 / max_tokens 2048"
             % tier_results[0].get("prompt_version", "v1"))
    L.append("- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/")
    L.append("- 场景: %s" % case["scenario"])
    L.append("- 图片: %s" % "，".join("%s=%s" % (f["frame_id"], f["file"]) for f in frames))
    L.append("- 人工核验依据: %s" % case.get("verification", ""))
    L.append("")
    for tr in tier_results:
        res, usage = tr["res"], tr["res"]["usage"]
        L.append("## Tier %s（%s）" % (tr.get("label", tr["tier"]),
                                       TIER_DESC.get(tr["kind"], tr["kind"])))
        L.append("")
        L.append("- 调用: HTTP %s | 耗时 %.1fs | 限流重试 %d 次 | 格式修复重试 %s" % (
            res["http_status"], res["latency_ms"] / 1000, res["retries_used"],
            "是" if tr["repair_used"] else "否"))
        if usage:
            L.append("- tokens: prompt=%s completion=%s (reasoning=%s)" % (
                usage.get("prompt_tokens"), usage.get("completion_tokens"),
                usage.get("completion_tokens_details", {}).get("reasoning_tokens")))
        if res["error"]:
            L.append("- 错误: %s" % res["error"])
        L.append("- 结构检查: %s" % ("通过" if not tr["structural"] else "未通过"))
        for p in tr["structural"]:
            L.append("  - [问题] %s" % p)
        L.append("- 禁止项扫描: %s" % ("未发现" if not tr["forbidden_hits"] else "发现 %d 处" % len(tr["forbidden_hits"])))
        for h in tr["forbidden_hits"]:
            L.append("  - [违规] %s …%s…" % (h["desc"], h["snippet"]))
        npass = sum(1 for r in tr["check_results"] if r["pass"])
        L.append("- 预期检查: %d/%d 通过" % (npass, len(tr["check_results"])))
        for r in tr["check_results"]:
            L.append("  - [%s] %s：%s（%s）" % ("PASS" if r["pass"] else "FAIL",
                                              r["desc"], r["expr"], r["actual"]))
        L.append("- 结论: **%s**" % tr["verdict"])
        L.append("")
    (case_dir / "review.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*", default=None,
                    help="只跑指定案例，如 --cases CASE-001 CASE-003")
    ap.add_argument("--tiers", nargs="*", default=None,
                    help="只跑指定档位，如 --tiers A B（用于重跑失败档）")
    ap.add_argument("--prompt-version", dest="prompt_version", default="v1",
                    choices=["v1", "v2", "v3", "v4"],
                    help="提示词版本（v2=围栏修复，v3=+枚举归属，v4=+多图趋势与树冠枚举补充）")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    cases_doc = json.loads(CASES_JSON.read_text(encoding="utf-8"))
    api_key = load_api_key()
    print("=" * 60)
    print("案例运行开始  模型: glm-4.6v-flash  提示词: %s  时间: %s"
          % (args.prompt_version, datetime.now().strftime("%Y-%m-%d %H:%M:%S")), flush=True)
    print("=" * 60, flush=True)

    LOGS_DIR.mkdir(exist_ok=True)
    summary = {"test_name": "case_run", "date": datetime.now().isoformat(timespec="seconds"),
               "model": "glm-4.6v-flash", "prompt_version": args.prompt_version,
               "cases": [], "totals": {"calls": 0, "pass": 0, "fail": 0,
                                       "failed_api": 0, "fail_structure": 0}}

    for case in cases_doc["cases"]:
        if args.cases and case["case_id"] not in args.cases:
            continue
        if not case.get("tiers"):
            print("[跳过] %s（tiers为空，待第2天补齐）" % case["case_id"], flush=True)
            continue

        tiers_todo = [td for td in case["tiers"]
                      if not args.tiers or td["tier"] in args.tiers]
        if not tiers_todo:
            print("[跳过] %s（本次未选中档位）" % case["case_id"], flush=True)
            continue
        print("[%s] %s" % (case["case_id"], case["scenario"]), flush=True)
        frames = setup_case_dir(case, args.prompt_version)
        case_dir = ROOT / "data" / "vlm-testcases" / case["case_id"]
        tier_results = []
        for idx, td in enumerate(tiers_todo):
            if idx > 0:
                time.sleep(GAP_BETWEEN_CALLS)  # 限流保护：调用间隔6秒
            tier_results.append(run_tier(api_key, case, td, frames, case_dir,
                                         args.prompt_version))

        write_review(case, frames, tier_results, case_dir)
        verdicts = [t["verdict"] for t in tier_results]
        if args.prompt_version == "v1" and not args.tiers:
            # 案例状态只由当前冻结版(v1)的完整运行更新；部分重跑/试验版不改状态
            case["status"] = "tested_pass" if all(v == "PASS" for v in verdicts) else "tested_fail"
            case["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        summary["cases"].append({
            "case_id": case["case_id"], "status": case["status"],
            "tiers": [{"tier": t["tier"], "verdict": t["verdict"],
                       "latency_ms": t["res"]["latency_ms"],
                       "structural_problems": len(t["structural"]),
                       "forbidden_hits": len(t["forbidden_hits"]),
                       "expected_pass": sum(1 for r in t["check_results"] if r["pass"]),
                       "expected_total": len(t["check_results"])} for t in tier_results]})
        for t in tier_results:
            summary["totals"]["calls"] += 1
            if t["verdict"] == "PASS":
                summary["totals"]["pass"] += 1
            elif t["verdict"] == "FAILED_API":
                summary["totals"]["failed_api"] += 1
            elif t["verdict"] == "FAIL_STRUCTURE":
                summary["totals"]["fail_structure"] += 1
            else:
                summary["totals"]["fail"] += 1
        print("[%s] 完成: %s\n" % (case["case_id"], " / ".join(
            "Tier%s=%s" % (t["tier"], t["verdict"]) for t in tier_results)), flush=True)

    t = summary["totals"]
    print("=" * 60)
    print("总结: 调用 %d 次 | PASS %d | FAIL %d | FAIL_STRUCTURE %d | FAILED_API %d"
          % (t["calls"], t["pass"], t["fail"], t["fail_structure"], t["failed_api"]), flush=True)
    log_path = LOGS_DIR / ("case_run_%s.json" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    log_path.write_text(dumps(summary), encoding="utf-8")
    print("记录已保存: %s（已确认不含Key）" % log_path.relative_to(ROOT), flush=True)

    CASES_JSON.write_text(dumps(cases_doc), encoding="utf-8")  # 回写案例状态
    print("cases.json 状态已更新", flush=True)


if __name__ == "__main__":
    main()
