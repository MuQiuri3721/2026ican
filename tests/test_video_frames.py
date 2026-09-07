"""视频抽帧适配测试（BE-11 视频接入：mp4 主文件 → 均匀抽帧 → 检测/VLM 帧序列）。

对应 docs/api-contract.md §5.2（多帧序列）与 task_routes._extract_video_frames。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("cv2")
cv2 = pytest.importorskip("cv2")  # noqa: F811
np = pytest.importorskip("numpy")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.routes.task_routes import _extract_video_frames  # noqa: E402


def _make_video(path: Path, frames: int = 30, size=(64, 48)) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, size)
    assert writer.isOpened(), "cv2 无法创建测试视频（缺编码器）"
    for index in range(frames):
        frame = np.full((size[1], size[0], 3), min(255, 20 + index * 8), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_extract_video_frames_samples_evenly_and_decodes(tmp_path):
    video = _make_video(tmp_path / "clip.mp4", frames=30)
    saved = _extract_video_frames(video, max_frames=4)
    assert len(saved) == 4
    assert len({p.name for p in saved}) == 4
    for item in saved:
        data = item.read_bytes()
        assert data[:2] == b"\xff\xd8"  # JPEG 魔数（与上传校验同口径）
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None and decoded.size > 0
        item.unlink(missing_ok=True)


def test_extract_video_frames_caps_at_max(tmp_path):
    video = _make_video(tmp_path / "long.mp4", frames=200)
    saved = _extract_video_frames(video, max_frames=4)
    assert len(saved) == 4
    for item in saved:
        item.unlink(missing_ok=True)


def test_extract_video_frames_rejects_undecodable(tmp_path):
    fake = tmp_path / "broken.mp4"
    fake.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)  # 签名合法但内容不可解码
    with pytest.raises(Exception) as error:
        _extract_video_frames(fake)
    assert "422" in str(getattr(error.value, "status_code", "")) or "无法解码" in str(error.value)


def test_upload_video_with_frames_conflicts_422(tmp_path):
    """视频主文件与序列帧同传 → 422（在进入分析管线前快速失败）。"""
    from backend.app.main import app

    video = _make_video(tmp_path / "clip.mp4", frames=10)
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze/upload",
            files={
                "file": ("clip.mp4", video.read_bytes(), "video/mp4"),
                "frames": ("f.jpg", jpg.read_bytes(), "image/jpeg"),
            },
            data={"use_vlm": "false"},
        )
    assert response.status_code == 422
    assert "二选一" in response.json()["detail"]
