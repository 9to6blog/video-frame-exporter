from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

import cv2


class VideoOpenError(RuntimeError):
    """Raised when OpenCV cannot open or inspect a video."""


class FrameWriteError(RuntimeError):
    """Raised when a decoded frame cannot be written."""


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    frame_count: int
    fps: float
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps if self.fps > 0 else 0.0


@dataclass(frozen=True)
class ExportResult:
    exported: int
    first_frame: int
    last_frame: int
    cancelled: bool
    output_dir: Path


def probe_video(path: str | Path) -> VideoInfo:
    video_path = Path(path)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise VideoOpenError(f"영상을 열 수 없습니다: {video_path}")

    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()

    if frame_count <= 0 or width <= 0 or height <= 0:
        raise VideoOpenError("영상 정보를 읽지 못했습니다. 지원되지 않는 코덱일 수 있습니다.")

    return VideoInfo(
        path=video_path,
        frame_count=frame_count,
        fps=fps,
        width=width,
        height=height,
    )


def read_frame(path: str | Path, frame_index: int):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise VideoOpenError(f"영상을 열 수 없습니다: {path}")

    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_index)))
        ok, frame = capture.read()
    finally:
        capture.release()

    if not ok or frame is None:
        raise VideoOpenError(f"{frame_index}번 프레임을 읽지 못했습니다.")
    return frame


def _write_frame(frame, path: Path, image_format: str, jpeg_quality: int) -> None:
    ext = ".jpg" if image_format == "jpg" else f".{image_format}"
    params: list[int] = []
    if image_format == "jpg":
        params = [cv2.IMWRITE_JPEG_QUALITY, max(1, min(100, jpeg_quality))]
    elif image_format == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
    elif image_format == "webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, max(1, min(100, jpeg_quality))]

    ok, encoded = cv2.imencode(ext, frame, params)
    if not ok:
        raise FrameWriteError(f"이미지 인코딩에 실패했습니다: {path.name}")

    try:
        encoded.tofile(str(path))  # Windows의 한글 경로를 지원합니다.
    except OSError as exc:
        raise FrameWriteError(f"이미지 저장에 실패했습니다: {path}") from exc


def export_frames(
    video_path: str | Path,
    output_dir: str | Path,
    start_frame: int,
    end_frame: int | None,
    image_format: str = "png",
    jpeg_quality: int = 95,
    progress_callback: Callable[[int, int, int], None] | None = None,
    cancel_event: Event | None = None,
) -> ExportResult:
    """Export an inclusive frame range in decode order."""
    if start_frame < 0:
        raise ValueError("시작 프레임은 0 이상이어야 합니다.")
    if end_frame is not None and end_frame < start_frame:
        raise ValueError("끝 프레임은 시작 프레임보다 크거나 같아야 합니다.")
    if image_format not in {"png", "jpg", "webp"}:
        raise ValueError("지원하지 않는 이미지 형식입니다.")

    source = Path(video_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise VideoOpenError(f"영상을 열 수 없습니다: {source}")

    reported_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    estimated_end = end_frame if end_frame is not None else max(start_frame, reported_count - 1)
    total = end_frame - start_frame + 1 if end_frame is not None else max(1, reported_count - start_frame)
    digits = max(6, len(str(estimated_end)))
    suffix = "jpg" if image_format == "jpg" else image_format
    exported = 0
    cancelled = False
    last_frame = start_frame - 1

    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_index = start_frame
        while end_frame is None or frame_index <= end_frame:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break

            ok, frame = capture.read()
            if not ok or frame is None:
                break

            output_path = destination / f"frame_{frame_index:0{digits}d}.{suffix}"
            _write_frame(frame, output_path, image_format, jpeg_quality)
            exported += 1
            last_frame = frame_index

            if progress_callback is not None:
                progress_callback(exported, total, frame_index)
            frame_index += 1
    finally:
        capture.release()

    return ExportResult(
        exported=exported,
        first_frame=start_frame,
        last_frame=last_frame,
        cancelled=cancelled,
        output_dir=destination,
    )
