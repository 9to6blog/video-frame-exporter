from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from extractor_core import ExportResult, VideoInfo, export_frames, probe_video, read_frame


APP_TITLE = "FrameDrop - 영상 프레임 추출기"
VIDEO_TYPES = [
    ("영상 파일", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv *.mpeg *.mpg"),
    ("모든 파일", "*.*"),
]


def format_seconds(seconds: float) -> str:
    if seconds <= 0:
        return "00:00.000"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:06.3f}"
    return f"{minutes:02d}:{sec:06.3f}"


class FrameExporterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("920x720")
        self.minsize(760, 620)

        self.video_info: VideoInfo | None = None
        self.current_frame = 0
        self.preview_image: ImageTk.PhotoImage | None = None
        self.preview_job: str | None = None
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.events: queue.Queue[tuple] = queue.Queue()

        self.video_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="all")
        self.start_var = tk.StringVar(value="0")
        self.end_var = tk.StringVar(value="0")
        self.format_var = tk.StringVar(value="png")
        self.quality_var = tk.IntVar(value=95)
        self.info_var = tk.StringVar(value="영상을 선택해 주세요.")
        self.frame_label_var = tk.StringVar(value="프레임 0")
        self.status_var = tk.StringVar(value="준비")

        self._configure_style()
        self._build_ui()
        self.after(80, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("맑은 고딕", 18, "bold"))
        style.configure("Section.TLabel", font=("맑은 고딕", 10, "bold"))
        style.configure("Accent.TButton", font=("맑은 고딕", 10, "bold"), padding=(16, 9))
        style.configure("TButton", padding=(10, 6))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=20)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="영상 프레임 추출기", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="영상의 모든 프레임 또는 원하는 구간을 이미지로 저장합니다.").pack(anchor="w", pady=(2, 16))

        file_row = ttk.Frame(root)
        file_row.pack(fill="x")
        ttk.Entry(file_row, textvariable=self.video_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="영상 선택", command=self._choose_video).pack(side="left", padx=(8, 0))
        ttk.Label(root, textvariable=self.info_var).pack(anchor="w", pady=(6, 10))

        preview_box = ttk.Frame(root, relief="solid", borderwidth=1)
        preview_box.pack(fill="both", expand=True)
        self.preview_label = tk.Label(
            preview_box,
            text="미리보기",
            bg="#16191d",
            fg="#aeb6bf",
            font=("맑은 고딕", 12),
            compound="center",
        )
        self.preview_label.pack(fill="both", expand=True)
        self.preview_label.bind("<Configure>", lambda _event: self._schedule_preview())

        timeline = ttk.Frame(root)
        timeline.pack(fill="x", pady=(10, 2))
        self.frame_scale = ttk.Scale(timeline, from_=0, to=0, command=self._on_scale)
        self.frame_scale.pack(side="left", fill="x", expand=True)
        ttk.Label(timeline, textvariable=self.frame_label_var, width=22, anchor="e").pack(side="left", padx=(10, 0))

        range_box = ttk.LabelFrame(root, text="추출 범위", padding=10)
        range_box.pack(fill="x", pady=(12, 0))
        ttk.Radiobutton(range_box, text="전체 프레임", variable=self.mode_var, value="all", command=self._refresh_range_state).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(range_box, text="구간 지정", variable=self.mode_var, value="range", command=self._refresh_range_state).grid(row=0, column=1, sticky="w", padx=(18, 14))

        ttk.Label(range_box, text="시작").grid(row=0, column=2, padx=(8, 4))
        self.start_spin = ttk.Spinbox(range_box, textvariable=self.start_var, width=9, from_=0, to=0)
        self.start_spin.grid(row=0, column=3)
        self.start_button = ttk.Button(range_box, text="현재 프레임", command=self._set_start)
        self.start_button.grid(row=0, column=4, padx=(5, 12))

        ttk.Label(range_box, text="끝").grid(row=0, column=5, padx=(0, 4))
        self.end_spin = ttk.Spinbox(range_box, textvariable=self.end_var, width=9, from_=0, to=0)
        self.end_spin.grid(row=0, column=6)
        self.end_button = ttk.Button(range_box, text="현재 프레임", command=self._set_end)
        self.end_button.grid(row=0, column=7, padx=(5, 0))
        range_box.columnconfigure(1, weight=1)

        settings = ttk.Frame(root)
        settings.pack(fill="x", pady=(12, 0))
        ttk.Label(settings, text="저장 위치", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.output_var, state="readonly").grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        ttk.Button(settings, text="폴더 변경", command=self._choose_output).grid(row=1, column=4, padx=(8, 0), pady=(4, 0))
        ttk.Label(settings, text="형식", style="Section.TLabel").grid(row=0, column=5, padx=(18, 5), sticky="e")
        format_combo = ttk.Combobox(settings, textvariable=self.format_var, values=("png", "jpg", "webp"), width=7, state="readonly")
        format_combo.grid(row=1, column=5, padx=(18, 5), pady=(4, 0))
        format_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_quality_state())
        ttk.Label(settings, text="품질").grid(row=0, column=6, padx=(5, 0))
        self.quality_spin = ttk.Spinbox(settings, textvariable=self.quality_var, from_=1, to=100, width=6)
        self.quality_spin.grid(row=1, column=6, padx=(5, 0), pady=(4, 0))
        settings.columnconfigure(0, weight=1)

        progress_row = ttk.Frame(root)
        progress_row.pack(fill="x", pady=(16, 0))
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(progress_row, textvariable=self.status_var, width=23, anchor="e").pack(side="left", padx=(10, 0))

        action_row = ttk.Frame(root)
        action_row.pack(fill="x", pady=(12, 0))
        self.cancel_button = ttk.Button(action_row, text="중단", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="right")
        self.export_button = ttk.Button(action_row, text="프레임 저장", style="Accent.TButton", command=self._start_export, state="disabled")
        self.export_button.pack(side="right", padx=(0, 8))
        self.open_button = ttk.Button(action_row, text="저장 폴더 열기", command=self._open_output, state="disabled")
        self.open_button.pack(side="left")

        self._refresh_range_state()
        self._refresh_quality_state()

    def _choose_video(self) -> None:
        selected = filedialog.askopenfilename(title="영상 선택", filetypes=VIDEO_TYPES)
        if not selected:
            return
        try:
            info = probe_video(selected)
        except Exception as exc:
            messagebox.showerror("영상을 열 수 없음", str(exc), parent=self)
            return

        self.video_info = info
        self.video_var.set(str(info.path))
        default_output = info.path.parent / f"{info.path.stem}_frames"
        self.output_var.set(str(default_output))
        last = info.frame_count - 1
        self.start_var.set("0")
        self.end_var.set(str(last))
        self.start_spin.configure(to=last)
        self.end_spin.configure(to=last)
        self.frame_scale.configure(to=last)
        self.frame_scale.set(0)
        self.current_frame = 0
        fps_text = f"{info.fps:.3f} FPS" if info.fps > 0 else "FPS 정보 없음"
        self.info_var.set(
            f"{info.width}×{info.height} · {info.frame_count:,}프레임 · {fps_text} · {format_seconds(info.duration_seconds)}"
        )
        self.export_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self._update_frame_label()
        self._schedule_preview()

    def _choose_output(self) -> None:
        initial = self.output_var.get() or str(Path.home())
        selected = filedialog.askdirectory(title="저장 폴더 선택", initialdir=initial)
        if selected:
            self.output_var.set(selected)
            self.open_button.configure(state="normal")

    def _on_scale(self, value: str) -> None:
        self.current_frame = int(round(float(value)))
        self._update_frame_label()
        self._schedule_preview()

    def _update_frame_label(self) -> None:
        info = self.video_info
        if info is None:
            self.frame_label_var.set("프레임 0")
            return
        timestamp = self.current_frame / info.fps if info.fps > 0 else 0
        self.frame_label_var.set(f"프레임 {self.current_frame:,} · {format_seconds(timestamp)}")

    def _schedule_preview(self) -> None:
        if self.video_info is None or self.worker is not None:
            return
        if self.preview_job is not None:
            self.after_cancel(self.preview_job)
        self.preview_job = self.after(130, self._request_preview)

    def _request_preview(self) -> None:
        self.preview_job = None
        info = self.video_info
        frame_index = self.current_frame
        if info is None:
            return

        def load() -> None:
            try:
                frame = read_frame(info.path, frame_index)
                self.events.put(("preview", frame_index, frame))
            except Exception as exc:
                self.events.put(("preview_error", str(exc)))

        threading.Thread(target=load, daemon=True).start()

    def _show_preview(self, frame_index: int, frame) -> None:
        if frame_index != self.current_frame:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        max_width = max(320, self.preview_label.winfo_width() - 12)
        max_height = max(180, self.preview_label.winfo_height() - 12)
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_image, text="")

    def _set_start(self) -> None:
        self.mode_var.set("range")
        self.start_var.set(str(self.current_frame))
        try:
            if int(self.end_var.get()) < self.current_frame:
                self.end_var.set(str(self.current_frame))
        except ValueError:
            self.end_var.set(str(self.current_frame))
        self._refresh_range_state()

    def _set_end(self) -> None:
        self.mode_var.set("range")
        self.end_var.set(str(self.current_frame))
        try:
            if int(self.start_var.get()) > self.current_frame:
                self.start_var.set(str(self.current_frame))
        except ValueError:
            self.start_var.set(str(self.current_frame))
        self._refresh_range_state()

    def _refresh_range_state(self) -> None:
        state = "normal" if self.mode_var.get() == "range" else "disabled"
        for widget in (self.start_spin, self.end_spin, self.start_button, self.end_button):
            widget.configure(state=state)

    def _refresh_quality_state(self) -> None:
        state = "disabled" if self.format_var.get() == "png" else "normal"
        self.quality_spin.configure(state=state)

    def _validated_range(self) -> tuple[int, int]:
        info = self.video_info
        if info is None:
            raise ValueError("먼저 영상을 선택해 주세요.")
        if self.mode_var.get() == "all":
            return 0, info.frame_count - 1
        try:
            start = int(self.start_var.get())
            end = int(self.end_var.get())
        except ValueError as exc:
            raise ValueError("시작과 끝 프레임은 정수로 입력해 주세요.") from exc
        if start < 0 or end < start or end >= info.frame_count:
            raise ValueError(f"범위는 0~{info.frame_count - 1} 안에서 시작 ≤ 끝이어야 합니다.")
        return start, end

    def _start_export(self) -> None:
        if self.worker is not None:
            return
        try:
            start, end = self._validated_range()
            quality = int(self.quality_var.get())
            if not 1 <= quality <= 100:
                raise ValueError("품질은 1~100 사이로 입력해 주세요.")
        except ValueError as exc:
            messagebox.showwarning("입력 확인", str(exc), parent=self)
            return

        info = self.video_info
        assert info is not None
        output = Path(self.output_var.get())
        image_format = self.format_var.get()
        export_all = self.mode_var.get() == "all"
        extraction_end = None if export_all else end
        suffix = "jpg" if image_format == "jpg" else image_format
        if output.exists() and any(output.glob(f"frame_*.{suffix}")):
            confirmed = messagebox.askyesno(
                "기존 이미지 확인",
                "저장 폴더에 같은 형식의 프레임 이미지가 있습니다.\n같은 번호의 파일은 덮어쓸까요?",
                parent=self,
            )
            if not confirmed:
                return

        total = end - start + 1
        self.progress.configure(value=0, maximum=total)
        self.status_var.set(f"0 / {total:,}")
        self.cancel_event.clear()
        self.export_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        def on_progress(done: int, _total: int, frame_index: int) -> None:
            self.events.put(("progress", done, total, frame_index))

        def work() -> None:
            try:
                result = export_frames(
                    info.path,
                    output,
                    start,
                    extraction_end,
                    image_format=image_format,
                    jpeg_quality=quality,
                    progress_callback=on_progress,
                    cancel_event=self.cancel_event,
                )
                self.events.put(("done", result, total, export_all))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker is not None:
            self.cancel_event.set()
            self.status_var.set("중단하는 중…")
            self.cancel_button.configure(state="disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "preview":
                    self._show_preview(event[1], event[2])
                elif kind == "preview_error":
                    self.preview_label.configure(image="", text="미리보기를 불러오지 못했습니다.")
                elif kind == "progress":
                    _, done, total, frame_index = event
                    if done > int(float(self.progress.cget("maximum"))):
                        self.progress.configure(maximum=done)
                    self.progress.configure(value=done)
                    self.status_var.set(f"{done:,} / {total:,} · #{frame_index:,}")
                elif kind == "done":
                    self._finish_export(event[1], event[2], event[3])
                elif kind == "error":
                    self._finish_with_error(event[1])
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    def _finish_export(self, result: ExportResult, requested_total: int, exported_all: bool) -> None:
        self.worker = None
        self.export_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        if result.cancelled:
            self.status_var.set(f"중단됨 · {result.exported:,}장 저장")
            messagebox.showinfo(
                "추출 중단",
                f"작업을 중단했습니다.\n이미 저장된 {result.exported:,}장은 유지됩니다.",
                parent=self,
            )
        elif not exported_all and result.exported < requested_total:
            self.status_var.set(f"완료 · {result.exported:,}장")
            messagebox.showwarning(
                "영상 끝에 도달",
                f"요청한 범위보다 영상이 먼저 끝났습니다.\n{result.exported:,}장을 저장했습니다.",
                parent=self,
            )
        else:
            self.status_var.set(f"완료 · {result.exported:,}장 저장")
            messagebox.showinfo(
                "저장 완료",
                f"{result.exported:,}장의 프레임을 저장했습니다.\n\n{result.output_dir}",
                parent=self,
            )

    def _finish_with_error(self, message: str) -> None:
        self.worker = None
        self.export_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status_var.set("오류")
        messagebox.showerror("추출 실패", message, parent=self)

    def _open_output(self) -> None:
        path = Path(self.output_var.get())
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("폴더 열기 실패", str(exc), parent=self)


if __name__ == "__main__":
    app = FrameExporterApp()
    app.mainloop()
