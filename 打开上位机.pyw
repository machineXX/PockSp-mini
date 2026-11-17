"""Windows instrument viewer for the SENSOR F user firmware's USB protocol."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk

import serial
from serial.tools import list_ports

from user_viewer_theme import ACCENT, BG, FONT, LINE, MUTED, NUMBERS, PANEL, TRACK, Surface, style_viewer, wavelength_color


MODES = {"spec": "光谱仪", "lux": "测光表", "flkr": "频率计"}
MODE_DATA = {"spec": "spectrum", "lux": "meter", "flkr": "flicker"}
EXPOSURE_FIELDS = ("光圈", "ISO", "快门")
ISO_VALUES = ("25", "50", "100", "200", "400", "800", "1600", "3200", "6400", "12800", "25600")
SPANS = (50, 200, 1000)
AUTO_PORT = "自动识别"
EMPTY = "—"
STATUS_LABELS = {
    "AUTO": "实时", "LIVE": "实时", "HOLD": "已定格", "WAIT": "等待新数据",
    "SAT": "曝光饱和", "Last frame": "上一帧", "OFF": "暂停",
    "Light signal too low": "光线过弱", "SAVE ERROR": "保存失败",
    "DARK": "频闪信号过弱", "OOR": "频率超出范围", "AMB": "频率待确认",
    "NO FLKR": "无明显频闪", "ERR": "采集异常", "REL FOR T.BASE": "松手进入时基设置",
}


def display_value(value, unit=""):
    return EMPTY if value in (None, "", "--") else f"{value} {unit}".rstrip()


def span_name(span):
    return "1 s" if span == 1000 else f"{span} ms"


@dataclass(frozen=True)
class Request:
    command: str
    reply_type: str
    deadline: float


class InstrumentPlot(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=PANEL, height=300, highlightthickness=0)
        self.content = None
        self.bind("<Configure>", lambda _event: self.draw())

    def show_trace(self, mode, data):
        content = (mode, data.get("plot_width"), data.get("plot_height"),
                   data.get("curve_y") if mode == "spec" else data.get("points"),
                   data.get("span_ms"), data.get("plot_style"),
                   data.get("axis_top"), data.get("axis_mid"))
        if content != self.content:
            self.content = content
            self.draw()

    def draw(self):
        self.delete("all")
        if not self.content:
            return
        mode, width, height, trace, span, style, top, middle = self.content
        if width is None or height is None or width < 2 or height < 2:
            return
        left, upper = 54, 14
        right = max(self.winfo_width() - 22, left + 1)
        bottom = max(self.winfo_height() - 40, upper + 1)

        def plot_x(x):
            return left + x * (right - left) / (width - 1)

        def plot_y(y):
            return upper + y * (bottom - upper) / (height - 1)

        ticks = ("100%", "50%", "0%") if mode == "spec" else (top, middle, "0")
        for i, tick in enumerate(ticks):
            y = upper + (bottom - upper) * i / 2
            self.create_line(left, y, right, y, fill=LINE)
            self.create_text(left - 10, y, text=tick, fill=MUTED, anchor="e", font=(FONT, 9))
        for i in range(5):
            x = left + (right - left) * i / 4
            tick = str(380 + i * 100) if mode == "spec" else f"{span * i / 4:g}"
            self.create_line(x, upper, x, bottom, fill="#eeeef2")
            self.create_text(x, bottom + 13, text=tick, fill=MUTED, font=(FONT, 9))
        self.create_text(right, bottom + 33, text="nm" if mode == "spec" else "ms",
                         fill=MUTED, anchor="e", font=(FONT, 9))
        if mode == "spec":
            for i in range(40):
                x0 = left + (right - left) * i / 40
                x1 = left + (right - left) * (i + 1) / 40
                self.create_rectangle(x0, bottom + 25, x1, bottom + 28,
                                      fill=wavelength_color(380 + i * 10), outline="")
        if not trace:
            self.create_text((left + right) / 2, (upper + bottom) / 2,
                             text="等待有效光谱" if mode == "spec" else "等待波形", fill=MUTED)
            return
        if mode == "spec":
            points = [(plot_x(i), plot_y(y)) for i, y in enumerate(trace)]
            if len(points) > 1:
                area = self.create_polygon(*points, (points[-1][0], bottom), (points[0][0], bottom),
                                           fill="#edf5ff", outline="")
                self.tag_lower(area)
        elif style == "envelope":
            points = []
            for (x, lo), (_, hi) in zip(trace[::2], trace[1::2]):
                xx, y0, y1 = plot_x(x), plot_y(lo), plot_y(hi)
                self.create_line(xx, y0, xx, y1, fill="#b5d3f7", tags="trace")
                points.append((xx, (y0 + y1) / 2))
        else:
            points = [(plot_x(x), plot_y(y)) for x, y in trace]
        if len(points) > 1:
            self.create_line(points, fill=ACCENT, width=2, capstyle="round", joinstyle="round", tags="trace")
        elif points:
            x, y = points[0]
            self.create_oval(x - 2, y - 2, x + 2, y + 2, fill=ACCENT, outline="", tags="trace")


class UserViewer:
    def __init__(self, root, port=None):
        self.root = root
        self.ser = None
        self.wanted = True
        self.pending = None
        self.action = None
        self.waiting_for_display = False
        self.state = None
        self.firmware = None
        self.last_meter_iso = None
        self.buffer = bytearray()
        self.next_retry = self.next_poll = 0.0
        self.connection = tk.StringVar(value="等待 USB")
        self.notice = tk.StringVar()
        self.port = tk.StringVar(value=port or AUTO_PORT)

        self.build_ui()
        self.render()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.author_dialog = None
        self.timer = self.root.after(40, self.tick)

    def build_ui(self):
        self.root.title("PockSp · 用户上位机")
        self.root.geometry(f"{min(1120, self.root.winfo_screenwidth() - 40)}x"
                           f"{min(755, self.root.winfo_screenheight() - 100)}")
        self.root.minsize(840, 570)
        self.root.configure(bg=BG)
        self.theme_images = style_viewer(self.root)

        header = ttk.Frame(self.root, padding=(28, 16, 28, 8))
        header.pack(fill="x")
        ttk.Label(header, text="PockSp", font=(NUMBERS, 26)).pack(side="left")
        ttk.Label(header, text="用户上位机", style="Muted.TLabel").pack(side="left", padx=(12, 0), pady=(8, 0))
        self.connect_button = ttk.Button(header, command=self.toggle_connection)
        self.connect_button.pack(side="right")
        self.port_box = ttk.Combobox(header, textvariable=self.port, width=13, state="readonly",
                                    postcommand=self.refresh_ports)
        self.port_box.pack(side="right", padx=(0, 8))
        ttk.Button(header, text="作者信息", command=self.show_author).pack(side="right", padx=(0, 8))
        self.refresh_ports()

        nav = ttk.Frame(self.root, padding=(28, 3, 28, 12))
        nav.pack(fill="x")
        segments = Surface(nav, height=40, width=302, fill=TRACK, border=TRACK, inset=4, radius=11)
        segments.pack(side="left")
        segments.inner.rowconfigure(0, weight=1)
        self.mode_buttons = {}
        for i, (mode, label) in enumerate(MODES.items()):
            segments.inner.columnconfigure(i, weight=1, uniform="mode")
            button = ttk.Button(segments.inner, text=label, width=0, style="Segment.TButton",
                                command=lambda value=mode: self.issue("mode " + value, "切换仪器"))
            button.grid(row=0, column=i, sticky="nsew")
            self.mode_buttons[mode] = button
        self.connection_label = ttk.Label(nav, textvariable=self.connection, style="Status.TLabel")
        self.connection_label.pack(side="right")
        self.connection_dot = ttk.Label(nav, text="●", style="Muted.TLabel")
        self.connection_dot.pack(side="right", padx=(0, 6))

        toolbar = ttk.Frame(self.root, padding=(28, 0, 28, 12))
        toolbar.pack(fill="x")
        self.hold_button = ttk.Button(toolbar, width=9, command=self.toggle_hold)
        self.hold_button.pack(side="left", padx=(0, 7))
        self.actions = {mode: ttk.Frame(toolbar) for mode in (*MODES, "settings")}
        spec = self.actions["spec"]
        self.layout_button = ttk.Button(spec, width=11, command=self.toggle_layout)
        self.layout_button.pack(side="left", padx=(0, 7))
        self.capture_button = ttk.Button(spec, text="保存到仪器", style="Primary.TButton",
                                         command=lambda: self.issue("capture", "保存光谱"))
        self.capture_button.pack(side="left", padx=(0, 7))

        lux = self.actions["lux"]
        self.exposure_button = ttk.Button(lux, width=12, command=lambda: self.issue("adjust", "曝光设置"))
        self.exposure_button.pack(side="left", padx=(0, 7))
        self.next_button = ttk.Button(lux, width=10, command=lambda: self.issue("next", "选择曝光"))
        self.next_button.pack(side="left")
        self.iso_frame = ttk.Frame(lux)
        self.iso = tk.StringVar()
        self.iso_box = ttk.Combobox(self.iso_frame, textvariable=self.iso, values=ISO_VALUES,
                                    width=7, state="readonly")
        self.iso_box.pack(side="left", padx=(6, 4))
        self.iso_box.bind("<<ComboboxSelected>>", lambda _event: self.update_controls())
        self.iso_button = ttk.Button(self.iso_frame, text="设置 ISO", command=self.set_iso)
        self.iso_button.pack(side="left")

        flkr = self.actions["flkr"]
        self.time_buttons = {}
        for span in SPANS:
            button = ttk.Button(flkr, text=span_name(span), style="Span.TButton",
                                command=lambda value=span: self.issue(f"timebase {value}", "设置时基"))
            button.pack(side="left", padx=(0, 5))
            self.time_buttons[span] = button
        self.close_settings = ttk.Button(self.actions["settings"], text="返回测量",
                                         command=lambda: self.issue("settings close", "返回测量"))
        self.close_settings.pack(side="left")

        self.cards = Surface(self.root, height=97, inset=13)
        self.metric_cells = []
        self.metrics = []
        for i in range(4):
            card = ttk.Frame(self.cards.inner, style="Surface.TFrame", padding=(11, 1))
            title = ttk.Label(card, style="SurfaceMuted.TLabel")
            value = ttk.Label(card, style="Metric.TLabel")
            title.pack(anchor="w")
            value.pack(anchor="w")
            self.metric_cells.append(card)
            self.metrics.append((title, value))

        body = ttk.Frame(self.root, padding=(28, 0, 28, 0))
        body.pack(fill="both", expand=True)
        self.body = body
        self.plot_card = Surface(body, height=310, inset=15)
        plot_header = ttk.Frame(self.plot_card.inner, style="Surface.TFrame", padding=(8, 0, 8, 4))
        plot_header.pack(fill="x")
        self.plot_title = ttk.Label(plot_header, style="Section.TLabel")
        self.plot_title.pack(side="left")
        self.record_label = ttk.Label(plot_header, style="SurfaceMuted.TLabel")
        self.record_label.pack(side="right")
        self.plot = InstrumentPlot(self.plot_card.inner)
        self.plot.pack(fill="both", expand=True)

        self.wait_card = Surface(body, height=220)
        self.wait = ttk.Label(self.wait_card.inner, anchor="center", style="SurfaceMuted.TLabel")
        self.wait.pack(fill="both", expand=True)

        self.meter = ttk.Frame(body)
        self.meter.columnconfigure(0, weight=6, uniform="exposure")
        self.meter.columnconfigure(1, weight=4, uniform="exposure")
        combinations = Surface(self.meter, height=245, inset=17)
        combinations.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        ttk.Label(combinations.inner, text="曝光组合", style="Section.TLabel").pack(anchor="w", pady=(0, 12))
        self.exposure_table = ttk.Treeview(
            combinations.inner, columns=("recommendation", "aperture", "iso", "shutter"),
            show="headings", height=3, selectmode="none",
        )
        for key, text in zip(self.exposure_table["columns"], ("方案", *EXPOSURE_FIELDS)):
            self.exposure_table.heading(key, text=text)
            self.exposure_table.column(key, width=105, minwidth=66, anchor="center")
        self.exposure_table.tag_configure("recommended", background="#e8f2ff", foreground=ACCENT)
        for index in range(3):
            self.exposure_table.insert("", "end", iid=str(index), tags=("recommended",) if index == 1 else ())
        self.exposure_table.pack(fill="x")

        settings = Surface(self.meter, height=245, inset=17)
        settings.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        ttk.Label(settings.inner, text="仪器设置", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.camera_values = []
        for name in EXPOSURE_FIELDS:
            row = ttk.Frame(settings.inner, style="Surface.TFrame")
            row.pack(fill="x", pady=(3, 3))
            ttk.Label(row, text=name, style="SurfaceMuted.TLabel").pack(side="left")
            value = ttk.Label(row, style="ExposureValue.TLabel")
            value.pack(side="right")
            self.camera_values.append(value)
            ttk.Frame(settings.inner, height=1, style="Separator.TFrame").pack(fill="x", pady=(0, 3))
        self.meter_note = ttk.Label(settings.inner, style="SurfaceMuted.TLabel")
        self.meter_note.pack(fill="x", pady=(5, 0))

        footer = ttk.Frame(self.root, padding=(28, 8, 28, 11))
        footer.pack(fill="x", side="bottom", before=self.body)
        status = ttk.Frame(footer)
        status.pack(fill="x", side="bottom")
        self.device_status = ttk.Label(status, style="Muted.TLabel")
        self.device_status.pack(side="right")
        ttk.Label(status, textvariable=self.notice, style="Status.TLabel").pack(side="left")

    def show_author(self):
        if self.author_dialog is not None and self.author_dialog.winfo_exists():
            self.author_dialog.lift()
            return

        dialog = tk.Toplevel(self.root)
        self.author_dialog = dialog
        dialog.title("PockSp · 作者信息")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

        card_path = Path(__file__).with_name("author-card.png")
        card = tk.PhotoImage(master=dialog, file=str(card_path)).subsample(3)
        label = ttk.Label(dialog, image=card)
        label.image = card
        label.pack(padx=12, pady=(12, 8))
        close_button = ttk.Button(dialog, text="关闭", command=dialog.destroy)
        close_button.pack(pady=(0, 12))
        close_button.focus_set()

    def refresh_ports(self):
        self.port_box.configure(values=(AUTO_PORT, *(p.device for p in list_ports.comports())))

    def toggle_connection(self):
        if self.wanted:
            self.wanted = False
            self.notice.set("")
            self.disconnect("USB 已断开")
        else:
            self.wanted = True
            self.next_retry = 0
            self.connection.set("正在连接 USB")
            self.render()

    def connect(self, now):
        self.next_retry = now + 1.5
        ports = list_ports.comports()
        selected = self.port.get()
        if selected == AUTO_PORT:
            candidates = [p.device for p in ports if (p.vid, p.pid) == (0x303A, 0x1001)]
            if len(candidates) != 1:
                self.connection.set("请选择串口" if candidates else "等待 USB 设备")
                return
            selected = candidates[0]
        if not any(p.device == selected for p in ports):
            self.connection.set(f"等待 {selected}")
            return
        connection = serial.Serial(baudrate=115200, timeout=0, write_timeout=0.25)
        connection.dtr = False
        connection.rts = False
        connection.port = selected
        try:
            connection.open()
        except (OSError, serial.SerialException):
            self.connection.set(f"{selected} 暂不可用，正在重试")
            return
        self.ser = connection
        self.connection.set(f"{selected} · 正在识别固件")
        self.request("stream off", "ack", prefix="\n")
        self.render()

    def disconnect(self, message):
        if self.ser is not None:
            self.ser.close()
        self.ser = self.pending = self.state = self.firmware = self.action = None
        self.last_meter_iso = None
        self.waiting_for_display = False
        self.buffer.clear()
        self.next_retry = time.monotonic() + 1.5
        self.connection.set(message)
        self.render()

    def request(self, command, reply_type, prefix=""):
        try:
            self.ser.write(f"{prefix}{command}\n".encode("ascii"))
        except (OSError, serial.SerialException):
            self.disconnect("USB 写入失败，正在重连")
            return
        self.pending = Request(command, reply_type, time.monotonic() + 3.0)

    def read_packets(self):
        self.buffer.extend(self.ser.read(min(self.ser.in_waiting or 1, 16384)))
        while self.ser is not None and b"\n" in self.buffer:
            line, _, self.buffer = self.buffer.partition(b"\n")
            try:
                packet = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(packet, dict):
                self.receive(packet)
        if len(self.buffer) > 16384:
            self.buffer.clear()

    def receive(self, packet):
        pending = self.pending
        kind = packet.get("type")
        if pending is None or kind not in (pending.reply_type, "error"):
            return
        self.pending = None
        if pending.command == "stream off":
            self.request("info", "info")
        elif pending.command == "info":
            if (packet.get("profile") != "user" or packet.get("protocol") != 1 or
                    not isinstance(packet.get("firmware"), str)):
                self.wanted = False
                self.disconnect("此设备未提供用户版 USB 协议 v1")
                return
            self.firmware = packet["firmware"]
            version = self.firmware.removeprefix("sensor-f-tcs3448-").removesuffix("-user-product")
            self.connection.set(f"{self.ser.port} · 用户固件 {version}")
            self.notice.set("")
            self.next_poll = 0
        elif pending.command == "status":
            if kind != "error" and self.valid_display(packet):
                if packet["page"] == "settings":
                    settings = packet["settings"]
                    packet["settings"] = {key: settings.get(key, "") for key in ("ssid", "url")}
                if self.action and self.action[2] != self.control_context(packet):
                    self.action = None
                    self.notice.set("仪器页面已变化，请重试操作")
                self.waiting_for_display = False
                if packet != self.state:
                    self.state = packet
                    self.render()
                else:
                    self.update_controls()
            self.next_poll = time.monotonic() + 0.23
        elif self.action is not None:
            _, label, _ = self.action
            self.action = None
            self.waiting_for_display = True
            self.next_poll = 0
            if packet.get("ok"):
                self.notice.set("" if label == "切换仪器" else label + " · 已执行")
            else:
                reason = {"busy": "仪器暂忙", "unavailable": "当前状态无法执行"}.get(
                    packet.get("code"), packet.get("error", packet.get("code", "操作失败")))
                self.notice.set(f"{label} · {reason}")
            self.update_controls()

    @staticmethod
    def valid_display(packet):
        mode, page = packet.get("mode"), packet.get("page")
        return (packet.get("protocol") == 1 and isinstance(mode, str) and mode in MODES and
                "boot_id" in packet and isinstance(packet.get("records"), int) and
                page in ("measure", "adjust", "spectrum_large", "settings") and
                isinstance(packet.get("settings" if page == "settings" else MODE_DATA[mode]), dict))

    @staticmethod
    def control_context(state):
        meter = state.get("meter", {})
        return (state["boot_id"], state["mode"], state["page"], state.get("held"),
                meter.get("selected"), meter.get("editing"))

    def issue(self, command, label):
        if not self.action_ready():
            return
        self.action = (command, label, self.control_context(self.state))
        self.notice.set(label + "…")
        self.update_controls()

    def tick(self):
        now = time.monotonic()
        try:
            if self.ser is None:
                if self.wanted and now >= self.next_retry:
                    self.connect(now)
            else:
                self.read_packets()
                if self.pending and now >= self.pending.deadline:
                    if self.action or self.waiting_for_display:
                        self.notice.set("操作回执超时，重连后请确认仪器状态")
                    self.disconnect("设备无响应，正在重连")
                elif self.ser is not None and self.pending is None and self.firmware:
                    if self.action:
                        command, _, _ = self.action
                        self.request(command, "ack")
                    elif now >= self.next_poll:
                        self.request("status", "display")
        except (OSError, serial.SerialException):
            self.disconnect("USB 已断开，正在等待重连")
        self.timer = self.root.after(35, self.tick)

    def action_ready(self):
        return self.ser is not None and self.state is not None and self.action is None and not self.waiting_for_display

    def toggle_hold(self):
        if self.state:
            held = self.state.get("held")
            self.issue("resume" if held else "hold", "恢复实时" if held else "定格")

    def toggle_layout(self):
        if self.state:
            large = self.state["page"] == "spectrum_large"
            self.issue("view normal" if large else "view large", "切换光谱视图")

    def set_iso(self):
        if self.iso.get() in ISO_VALUES:
            self.issue("iso " + self.iso.get(), "设置 ISO")

    def render(self):
        state = self.state
        mode = state["mode"] if state else None
        page = state["page"] if state else None
        editing = page == "adjust"
        data = state.get(MODE_DATA[mode], {}) if mode else {}
        self.connect_button.configure(text="断开 USB" if self.ser else "停止等待" if self.wanted else "连接 USB")
        self.port_box.configure(state="disabled" if self.ser else "readonly")
        self.connection_dot.configure(style="Online.TLabel" if self.state else "Muted.TLabel")
        visible_actions = "settings" if page == "settings" else mode
        for key, frame in self.actions.items():
            if key == visible_actions:
                if not frame.winfo_manager():
                    frame.pack(side="left")
            else:
                frame.pack_forget()
        self.hold_button.configure(text="恢复实时" if state and state.get("held") else "定格")
        self.layout_button.configure(text="普通视图" if page == "spectrum_large" else "光谱大图")
        self.record_label.configure(text=f"板内记录 {state['records']} / 64" if mode == "spec" else "")
        if mode != "lux" or editing:
            self.iso_frame.pack_forget()
        elif not self.iso_frame.winfo_manager():
            self.iso_frame.pack(side="left")
        if mode == "lux" and "camera" in data:
            current_iso = data["camera"][1]
            if current_iso != self.last_meter_iso:
                self.iso.set(current_iso if current_iso in ISO_VALUES else "")
                self.last_meter_iso = current_iso
        self.exposure_button.configure(text=("保存所选档位" if data.get("editing") else "调节所选项")
                                       if editing else "曝光设置",
                                       style="Primary.TButton" if data.get("editing") else "TButton")
        self.next_button.configure(text="下一档" if data.get("editing") else "下一项")
        if editing and mode == "lux":
            if not self.next_button.winfo_manager():
                self.next_button.pack(side="left")
        else:
            self.next_button.pack_forget()

        if page == "settings":
            self.show_body(self.wait_card)
            settings = state["settings"]
            self.wait.configure(text=f"仪器设置 · {settings.get('ssid', '')}    {settings.get('url', '')}")
            readings = ()
        elif mode == "spec":
            self.show_body(self.plot_card)
            self.plot_title.configure(text="相对光谱")
            self.plot.show_trace(mode, data)
            readings = (("色温", display_value(data.get("cct"), "K")),
                        ("显色指数 Ra", display_value(data.get("ra"))),
                        ("照度", display_value(data.get("illumination"), "lx")),
                        ("蓝光占比 B%", display_value(data.get("blue_ratio"), "%")))
        elif mode == "flkr":
            readings = (("频率", display_value(data.get("frequency"), "Hz")),
                        ("当前时基", span_name(data["span_ms"])))
            if editing:
                self.show_body(self.wait_card)
                self.wait.configure(text="选择时基后返回波形")
                readings += (("仪器待选时基", span_name(data["selection_ms"])),)
            else:
                self.show_body(self.plot_card)
                self.plot_title.configure(text="频闪波形")
                self.plot.show_trace(mode, data)
            for span, button in self.time_buttons.items():
                button.configure(style="ActiveSpan.TButton" if data["span_ms"] == span else "Span.TButton")
        elif mode == "lux":
            self.show_body(self.meter)
            readings = self.render_meter(data, editing)
        else:
            self.show_body(self.wait_card)
            self.wait.configure(text="接入仪器开始测量")
            readings = ()

        if readings and not self.cards.winfo_manager():
            self.cards.pack(before=self.body, fill="x", padx=28, pady=(0, 12))
        elif not readings:
            self.cards.pack_forget()
        for i, (label, value) in enumerate(self.metrics):
            active = i < len(readings)
            self.cards.inner.columnconfigure(i, weight=int(active), uniform="metric" if active else "")
            if active:
                name, text = readings[i]
                label.configure(text=name)
                value.configure(text=text)
                self.metric_cells[i].grid(row=0, column=i, sticky="ew")
            else:
                self.metric_cells[i].grid_remove()
        self.update_device_status(state, data)
        self.update_controls()

    def show_body(self, widget):
        for other in (self.plot_card, self.meter, self.wait_card):
            if other != widget:
                other.pack_forget()
        if not widget.winfo_manager():
            widget.pack(fill="both", expand=True)

    def render_meter(self, data, editing):
        fixed, selected = data["fixed"], data["selected"]
        camera = data["camera"]
        for value, setting in zip(self.camera_values, camera):
            value.configure(text=display_value(setting))
        for i, label in enumerate(("备选组合", "推荐组合", "备选组合")):
            values = [display_value(data[key][i]) for key in ("aperture", "sensitivity", "time")]
            if data["valid"]:
                values[fixed] = camera[fixed]
            values[1] = values[1].removeprefix("ISO ")
            self.exposure_table.item(str(i), values=(label, *values))
        if editing:
            note = f"当前选择 {EXPOSURE_FIELDS[selected]}"
            if data.get("editing"):
                note += " · 待保存 " + display_value(data.get("value"))
        else:
            note = ""
        self.meter_note.configure(text=note)
        return (("照度", display_value(data.get("illumination"), "lx")),
                ("色温", display_value(data.get("temperature"), "K")),
                ("固定 " + EXPOSURE_FIELDS[fixed], display_value(camera[fixed])),
                ("曝光偏差", display_value(data.get("exposure"))))

    def update_device_status(self, state, data):
        if not state:
            self.device_status.configure(text="")
            return
        battery = display_value(state.get("battery_percent"), "%")
        wifi = {"off": "热点关闭", "on": "热点已开启", "starting": "热点启动中",
                "stopping": "热点关闭中", "error": "热点错误"}.get(state.get("wifi"), "")
        if state.get("wifi_connected"):
            wifi = "热点已连接"
        status = data.get("status", "")
        reference = {"REF": "参考读数", "CAL": "已校准"}.get(data.get("reference"), "")
        parts = [STATUS_LABELS.get(status, status), reference,
                 f"电量 {battery}" + (" · 充电中" if state.get("charging") else ""), wifi]
        self.device_status.configure(text="  ·  ".join(filter(None, parts)))

    def update_controls(self):
        state = self.state or {}
        mode, page = state.get("mode"), state.get("page")
        ready = self.action_ready()
        has_spectrum = bool(state.get("spectrum", {}).get("curve_y"))
        if state.get("spectrum", {}).get("status") in ("WAIT", "SAT", "Last frame"):
            has_spectrum = False
        has_data = {"spec": has_spectrum, "lux": state.get("meter", {}).get("valid"),
                    "flkr": state.get("flicker", {}).get("points")}
        can_choose_iso = ready and mode == "lux" and page == "measure"
        enabled = {
            self.hold_button: ready and page in ("measure", "spectrum_large")
            and (state.get("held") or has_data.get(mode)),
            self.layout_button: ready and mode == "spec",
            self.capture_button: ready and has_spectrum and state.get("records", 64) < 64,
            self.exposure_button: ready and mode == "lux",
            self.next_button: ready and mode == "lux" and page == "adjust",
            self.iso_button: can_choose_iso and self.iso.get() in ISO_VALUES,
            self.close_settings: ready and page == "settings",
        }
        enabled.update({button: ready and mode == "flkr" for button in self.time_buttons.values()})
        for instrument, button in self.mode_buttons.items():
            button.configure(style="Selected.TButton" if mode == instrument else "Segment.TButton")
            enabled[button] = ready and (mode != instrument or page == "settings")
        for button, active in enabled.items():
            button.configure(state="normal" if active else "disabled")
        self.iso_box.configure(state="readonly" if can_choose_iso else "disabled")

    def close(self):
        self.root.after_cancel(self.timer)
        if self.ser:
            self.ser.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="USB serial port, for example COM7")
    args = parser.parse_args()
    root = tk.Tk()
    UserViewer(root, args.port)
    root.mainloop()


if __name__ == "__main__":
    main()
