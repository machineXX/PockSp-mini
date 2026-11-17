"""Appearance shared by the user viewer's instrument screens."""

import math
from colorsys import hsv_to_rgb
import tkinter as tk
from tkinter import ttk


BG = "#f5f5f7"
PANEL = "#ffffff"
FG = "#1d1d1f"
MUTED = "#68686e"
ACCENT = "#0066cc"
LINE = "#e3e3e8"
TRACK = "#e8e8ed"
FONT = "Microsoft YaHei UI"
NUMBERS = "Segoe UI Semibold"


def wavelength_color(nm):
    hue = 0.76 * max(0, min(1, (710 - nm) / 330))
    brightness = 0.72 if nm < 400 or nm > 730 else 0.92
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in hsv_to_rgb(hue, 0.8, brightness))


def rounded_image(root, fill, outline=None):
    size, radius = 24, 8
    picture = tk.PhotoImage(master=root, width=size, height=size)
    for y in range(size):
        offset = max(radius - y - 0.5, y - (size - radius) + 0.5, 0)
        left = math.ceil(radius - math.sqrt(radius * radius - offset * offset))
        right = size - left
        picture.put(fill, to=(left, y, right, y + 1))
        if outline:
            if y in (0, size - 1):
                picture.put(outline, to=(left, y, right, y + 1))
            else:
                picture.put(outline, to=(left, y, left + 1, y + 1))
                picture.put(outline, to=(right - 1, y, right, y + 1))
    return picture


def style_viewer(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=FG, font=(FONT, 10))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Status.TLabel", foreground=MUTED)
    style.configure("Online.TLabel", foreground="#1e7850")
    style.configure("Surface.TFrame", background=PANEL)
    style.configure("Track.TFrame", background=TRACK)
    style.configure("SurfaceMuted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Section.TLabel", background=PANEL, font=(FONT, 12, "bold"))
    style.configure("Metric.TLabel", background=PANEL, font=(NUMBERS, 27))
    style.configure("ExposureValue.TLabel", background=PANEL, font=(NUMBERS, 16))
    style.configure("Separator.TFrame", background=LINE)
    style.configure("TCombobox", padding=(9, 6), foreground=FG, arrowcolor=MUTED,
                    bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, arrowsize=11)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL), ("disabled", BG)],
              foreground=[("readonly", FG), ("disabled", MUTED)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", "#e8f1fd")
    root.option_add("*TCombobox*Listbox.selectForeground", FG)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                    rowheight=47, relief="flat", borderwidth=0, lightcolor=PANEL,
                    darkcolor=PANEL, bordercolor=PANEL)
    style.configure("Treeview.Heading", background="#f5f5f7", foreground=MUTED, padding=(7, 8),
                    relief="flat", borderwidth=0, lightcolor="#f5f5f7", darkcolor="#f5f5f7",
                    bordercolor="#f5f5f7")
    style.map("Treeview.Heading", background=[("active", "#f5f5f7")])

    images = []
    buttons = (
        ("TButton", "#e9e9ee", "#e1e1e8", "#d7d7e0", "#ededf1", FG, "#929299", (12, 7)),
        ("Primary.TButton", "#0071e3", "#0067cf", "#005ab7", "#e8edf4", PANEL, "#8a94a4", (13, 7)),
        ("Segment.TButton", TRACK, "#dedee5", "#d5d5de", TRACK, "#4f4f56", "#929299", (12, 6)),
        ("Selected.TButton", PANEL, PANEL, PANEL, PANEL, FG, FG, (12, 6)),
        ("Span.TButton", TRACK, "#dedee5", "#d5d5de", TRACK, "#4f4f56", "#929299", (10, 7)),
        ("ActiveSpan.TButton", "#e7f0fc", "#dceafb", "#cddff6", "#e7f0fc", ACCENT, ACCENT, (10, 7)),
    )
    for name, normal, hover, pressed, disabled, foreground, muted, padding in buttons:
        normal_image, hover_image, pressed_image, disabled_image, focus_image = current = (
            rounded_image(root, normal), rounded_image(root, hover), rounded_image(root, pressed),
            rounded_image(root, disabled), rounded_image(root, normal, "#7cafe9"),
        )
        images.extend(current)
        element = name + ".surface"
        style.element_create(element, "image", normal_image, ("disabled", disabled_image),
                             ("pressed", pressed_image), ("focus", focus_image), ("active", hover_image),
                             border=8, padding=0, sticky="nswe")
        style.layout(name, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"}),
            ]}),
        ]})])
        style.configure(name, foreground=foreground, padding=padding)
        style.map(name, foreground=[("disabled", muted), ("!disabled", foreground)])
    style.configure("Segment.TButton", background=TRACK)
    style.configure("Selected.TButton", background=TRACK)
    return images


class Surface(tk.Canvas):
    """Rounded background with a normal Tk layout inside its padded bounds."""

    def __init__(self, parent, *, height=80, width=1, fill=PANEL, border=LINE, inset=13, radius=18):
        super().__init__(parent, bg=BG, height=height, width=width, highlightthickness=0)
        self.fill, self.border, self.inset, self.radius = fill, border, inset, radius
        self.inner = ttk.Frame(self, style="Track.TFrame" if fill == TRACK else "Surface.TFrame")
        self.window = self.create_window(inset, inset, anchor="nw", window=self.inner)
        self.bind("<Configure>", self.resize)

    def resize(self, event):
        w, h = event.width - 1, event.height - 1
        r = min(self.radius, w // 2, h // 2)
        self.delete("surface")
        self.create_polygon(
            r, 0, w-r, 0, w-r, 0, w, 0, w, r, w, r,
            w, h-r, w, h-r, w, h, w-r, h, w-r, h,
            r, h, r, h, 0, h, 0, h-r, 0, h-r,
            0, r, 0, r, 0, 0, r, 0, fill=self.fill, outline=self.border,
            smooth=True, splinesteps=20, tags="surface",
        )
        self.tag_lower("surface")
        self.itemconfigure(self.window, width=max(1, event.width - 2 * self.inset),
                           height=max(1, event.height - 2 * self.inset))
