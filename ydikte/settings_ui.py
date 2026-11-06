"""The settings window. Runs as its own process and talks to the app only through files:
it edits config.toml and .env, and the running app picks the changes up by itself.
"""

import base64
import ctypes as C
import logging
import tkinter as tk
import tkinter.font as tkfont

from . import audio, config, gfx, hotkey, tray
from . import winapi as w

log = logging.getLogger("ydikte")

TITLE = "YDikte Ayarları"
BG = "#0F1117"
CARD = "#181B23"
FIELD = "#232732"
HOVER = "#2C3140"
TEXT = "#F4F5F7"
MUTED = "#8E94A3"
ACCENT = "#FF5A4F"
OK = "#2EE6A6"
WARN = "#FFB020"
WIDTH = 500

NAMES = {
    "rctrl": "Sağ Ctrl", "lctrl": "Sol Ctrl", "ctrl": "Ctrl", "rshift": "Sağ Shift", "lshift": "Sol Shift",
    "shift": "Shift", "ralt": "AltGr", "lalt": "Sol Alt", "alt": "Alt", "win": "Win", "lwin": "Sol Win",
    "rwin": "Sağ Win", "capslock": "Caps Lock", "scrolllock": "Scroll Lock", "space": "Boşluk",
    "pause": "Pause", "insert": "Insert", "apps": "Menü tuşu",
}
_KEYSYMS = {
    "Control_R": "rctrl", "Control_L": "lctrl", "Shift_R": "rshift", "Shift_L": "lshift",
    "Alt_R": "ralt", "Alt_L": "lalt", "Win_L": "lwin", "Win_R": "rwin", "Caps_Lock": "capslock",
    "Scroll_Lock": "scrolllock", "Pause": "pause", "Insert": "insert", "App": "apps", "space": "space",
    "Tab": "tab", "Return": "enter", "Home": "home", "End": "end", "Prior": "pageup", "Next": "pagedown",
    "Delete": "delete", "Num_Lock": "numlock",
}
_MODIFIER_ORDER = ("lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt", "lwin", "rwin")


def keysym_to_name(keysym):
    if keysym in _KEYSYMS:
        return _KEYSYMS[keysym]
    if len(keysym) == 1 and keysym.isascii() and keysym.isalnum():
        return keysym.lower()
    if keysym[0] == "F" and keysym[1:].isdigit():
        return keysym.lower()
    return None


def combine_keys(names):
    """Modifiers first, in a fixed order, so the same keys always give the same text."""
    modifiers = [n for n in _MODIFIER_ORDER if n in names]
    others = sorted(n for n in names if n not in _MODIFIER_ORDER)
    return "+".join(modifiers + others)


def pretty_hotkey(text):
    return " + ".join(NAMES.get(part, part.upper()) for part in str(text).split("+"))


def _image(png):
    return tk.PhotoImage(data=base64.b64encode(png), format="png")


class Settings:
    def __init__(self, root):
        self.root = root
        self.images = []        # Tk forgets images that Python stops referencing
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.cfg = config.load_config()
        self.keys = config.load_keys()
        self._saved_after = None

        root.title(TITLE)
        root.configure(bg=BG)
        root.resizable(False, False)
        try:
            root.iconbitmap(str(config.ASSETS / "logo.ico"))
        except tk.TclError:
            pass
        self.font = ("Segoe UI", 10)
        self.font_bold = ("Segoe UI Semibold", 10)
        self.font_small = ("Segoe UI", 9)
        self.measure = tkfont.Font(root, font=self.font)
        self._button_cache = {}

        # The content sits in a canvas so it can scroll on small or highly scaled screens.
        self.scroller = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
        self.scroller.pack()
        self.body = tk.Frame(self.scroller, bg=BG)
        self.scroller.create_window(self.s(16), self.s(14), anchor="nw", window=self.body)
        self.build()
        root.update_idletasks()
        width = self.body.winfo_reqwidth() + self.s(32)
        full = self.body.winfo_reqheight() + self.s(28)
        visible = min(full, root.winfo_screenheight() - self.s(90))
        self.scroller.configure(width=width, height=visible, scrollregion=(0, 0, width, full))
        if visible < full:
            root.bind_all("<MouseWheel>", lambda e: self.scroller.yview_scroll(-e.delta // 120, "units"))
        root.bind_all("<Escape>", lambda e: self.cancel_capture())

    def s(self, value):
        return int(round(value * self.scale))

    def keep(self, image):
        self.images.append(image)
        return image

    # ---- building blocks -----------------------------------------------------

    def card(self, title, rows_height):
        width, height = self.s(WIDTH), self.s(rows_height)
        png = gfx.rounded_rect_png(width, height, self.s(12), CARD, BG)
        holder = tk.Canvas(self.body, width=width, height=height, bg=BG, highlightthickness=0, bd=0)
        holder.create_image(0, 0, anchor="nw", image=self.keep(_image(png)))
        holder.create_text(self.s(16), self.s(13), anchor="w", text=title.upper(), fill=MUTED,
                           font=("Segoe UI Semibold", 8))
        holder.pack(pady=(0, self.s(10)))
        inner = tk.Frame(holder, bg=CARD)
        holder.create_window(self.s(16), self.s(26), anchor="nw", window=inner,
                             width=width - self.s(32), height=height - self.s(34))
        return inner

    def row(self, parent, label, hint=None):
        frame = tk.Frame(parent, bg=CARD)
        frame.pack(fill="x", pady=self.s(4))
        text = tk.Frame(frame, bg=CARD)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=label, bg=CARD, fg=TEXT, font=self.font, anchor="w").pack(anchor="w")
        if hint:
            tk.Label(text, text=hint, bg=CARD, fg=MUTED, font=self.font_small, anchor="w",
                     justify="left").pack(anchor="w")
        return frame

    def toggle(self, parent, value, on_change):
        width, height = self.s(38), self.s(21)
        images = {
            state: self.keep(_image(gfx.toggle_png(width, height, state, ACCENT, "#3A3F4D", "#FFFFFF", CARD)))
            for state in (True, False)
        }
        state = {"on": bool(value)}
        label = tk.Label(parent, image=images[state["on"]], bg=CARD, cursor="hand2", bd=0)

        def click(_event):
            state["on"] = not state["on"]
            label.configure(image=images[state["on"]])
            on_change(state["on"])

        label.bind("<Button-1>", click)
        label.pack(side="right")
        return label

    def segmented(self, parent, options, value, on_change):
        """A row of choices with one selected. `options` is [(value, label)]."""
        height = self.s(30)
        pad = self.s(3)
        padding = self.s(11)
        probe = tk.Label(parent, font=self.font)
        widths = []
        for _, text in options:
            probe.configure(text=text)
            widths.append(probe.winfo_reqwidth() - self.s(4) + padding)
        probe.destroy()
        total = sum(widths) + pad * 2
        canvas = tk.Canvas(parent, width=total, height=height, bg=CARD, highlightthickness=0, bd=0)
        canvas.create_image(0, 0, anchor="nw", image=self.keep(_image(
            gfx.rounded_rect_png(total, height, self.s(8), FIELD, CARD))))
        marks = []
        x = pad
        selected = {"value": value}
        items = []
        for (option, text), seg in zip(options, widths):
            mark = self.keep(_image(gfx.rounded_rect_png(seg, height - pad * 2, self.s(6), ACCENT, FIELD)))
            mark_id = canvas.create_image(x, pad, anchor="nw", image=mark, state="hidden")
            text_id = canvas.create_text(x + seg / 2, height / 2, text=text, fill=TEXT, font=self.font)
            items.append((option, mark_id, text_id))
            marks.append((x, x + seg, option))
            x += seg

        def paint():
            for option, mark_id, text_id in items:
                chosen = option == selected["value"]
                canvas.itemconfigure(mark_id, state="normal" if chosen else "hidden")
                canvas.itemconfigure(text_id, fill="#FFFFFF" if chosen else "#C6CAD4")

        def click(event):
            for left, right, option in marks:
                if left <= event.x < right and option != selected["value"]:
                    selected["value"] = option
                    paint()
                    on_change(option)

        canvas.bind("<Button-1>", click)
        canvas.configure(cursor="hand2")
        paint()
        return canvas

    def button_images(self, text):
        """Rounded normal and hover backgrounds sized to fit `text`."""
        width = self.measure.measure(text) + self.s(26)
        height = self.s(30)
        cached = self._button_cache.get(width)
        if cached is None:
            cached = tuple(_image(gfx.rounded_rect_png(width, height, self.s(8), color, CARD))
                           for color in (FIELD, HOVER))
            self._button_cache[width] = cached
        return cached

    def button(self, parent, text, command):
        label = tk.Label(parent, bg=CARD, fg=TEXT, font=self.font, cursor="hand2", compound="center", bd=0)
        state = {}

        def set_text(new_text):
            state["images"] = self.button_images(new_text)
            label.configure(text=new_text, image=state["images"][0])

        label.bind("<Button-1>", lambda e: command(e))
        label.bind("<Enter>", lambda e: label.configure(image=state["images"][1]))
        label.bind("<Leave>", lambda e: label.configure(image=state["images"][0]))
        set_text(text)
        label.set_text = set_text
        label.pack(side="right")
        return label

    # ---- the window ----------------------------------------------------------

    def build(self):
        self.build_header()
        self.build_hotkey()
        self.build_transcription()
        self.build_cleanup()
        self.build_behavior()
        self.footer = tk.Label(self.body, text="Değişiklikler otomatik uygulanır", bg=BG, fg=MUTED,
                               font=self.font_small)
        self.footer.pack(anchor="center")

    def build_header(self):
        header = tk.Frame(self.body, bg=BG)
        header.pack(fill="x", pady=(0, self.s(12)))
        logo = self.keep(tk.PhotoImage(file=str(config.ASSETS / "logo_64.png")))
        shrink = max(1, round(64 / self.s(40)))
        small = self.keep(logo.subsample(shrink, shrink))
        tk.Label(header, image=small, bg=BG, bd=0).pack(side="left", padx=(self.s(2), self.s(10)))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="YDikte", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(titles, text="Basılı tut, konuş, bırak.", bg=BG, fg=MUTED, font=self.font_small).pack(anchor="w")
        self.status = tk.Label(header, bg=BG, font=self.font_small)
        self.status.pack(side="right")
        self.refresh_status()

    def refresh_status(self):
        running = bool(w.user32.FindWindowW("YDikteMain", None))
        self.status.configure(text="●  Çalışıyor" if running else "●  Kapalı", fg=OK if running else MUTED)
        self.root.after(2000, self.refresh_status)

    def build_hotkey(self):
        inner = self.card("Kısayol", 96)
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(self.s(4), 0))
        left = tk.Frame(row, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        self.hotkey_label = tk.Label(left, text=pretty_hotkey(self.cfg["hotkey"]), bg=CARD, fg=TEXT,
                                     font=("Segoe UI Semibold", 13), anchor="w")
        self.hotkey_label.pack(anchor="w")
        self.hotkey_hint = tk.Label(left, text="Basılı tut: dikte  ·  Çift dokun: eller serbest  ·  Esc: iptal",
                                    bg=CARD, fg=MUTED, font=self.font_small, anchor="w")
        self.hotkey_hint.pack(anchor="w")
        self.capture_button = self.button(row, "Değiştir", lambda e: self.start_capture())
        self.capturing = False
        self.pressed = set()

    def start_capture(self):
        self.capturing = True
        self.pressed = set()
        self.hotkey_label.configure(text="Tuşlara bas…", fg=ACCENT)
        self.hotkey_hint.configure(text="Bırakınca kaydedilir. Vazgeçmek için Esc.", fg=MUTED)
        self.root.bind("<KeyPress>", self.on_capture_press)
        self.root.bind("<KeyRelease>", self.on_capture_release)
        self.root.focus_force()

    def cancel_capture(self):
        if self.capturing:
            self.stop_capture()
            self.hotkey_label.configure(text=pretty_hotkey(self.cfg["hotkey"]), fg=TEXT)
            self.reset_hint()

    def stop_capture(self):
        self.capturing = False
        self.root.unbind("<KeyPress>")
        self.root.unbind("<KeyRelease>")

    def reset_hint(self):
        self.hotkey_hint.configure(text="Basılı tut: dikte  ·  Çift dokun: eller serbest  ·  Esc: iptal", fg=MUTED)

    def on_capture_press(self, event):
        if event.keysym == "Escape":
            return
        name = keysym_to_name(event.keysym)
        if name:
            self.pressed.add(name)

    def on_capture_release(self, event):
        if not self.capturing or not self.pressed:
            return
        text = combine_keys(self.pressed)
        self.stop_capture()
        try:
            hotkey.parse(text)
        except hotkey.HotkeyError as exc:
            self.hotkey_label.configure(text=pretty_hotkey(self.cfg["hotkey"]), fg=TEXT)
            self.hotkey_hint.configure(text=f"Olmaz: {exc}", fg=WARN)
            return
        self.cfg["hotkey"] = text
        self.save(None, "hotkey", text)
        self.hotkey_label.configure(text=pretty_hotkey(text), fg=TEXT)
        if "ralt" in text.split("+"):
            self.hotkey_hint.configure(text="Dikkat: Türkçe klavyede bu tuş AltGr'dir, @ gibi karakterleri etkiler.",
                                       fg=WARN)
        else:
            self.reset_hint()

    def build_transcription(self):
        inner = self.card("Yazıya dökme", 150)
        t = self.cfg["transcription"]
        row = self.row(inner, "Motor", None)
        self.segmented(row, [("local", "Yerel"), ("groq", "Groq"), ("openai", "OpenAI"), ("auto", "Otomatik")],
                       t["backend"], lambda v: self.save("transcription", "backend", v)).pack(side="right")
        row = self.row(inner, "Dil", None)
        language = t["language"] if t["language"] in ("auto", "tr", "en") else "auto"
        self.segmented(row, [("auto", "Otomatik"), ("tr", "Türkçe"), ("en", "English")], language,
                       lambda v: self.save("transcription", "language", v)).pack(side="right")
        row = self.row(inner, "Mikrofon", None)
        self.build_mic_menu(row)

    def build_mic_menu(self, parent):
        current = self.cfg["audio"]["input_device"]
        choices = [("", "Windows varsayılanı")] + [(n, n) for n in audio.list_devices()]
        name = next((text for value, text in choices if value == current), current or choices[0][1])
        menu = tk.Menu(self.root, tearoff=0, bg=FIELD, fg=TEXT, activebackground=ACCENT,
                       activeforeground="#FFFFFF", bd=0, font=self.font)
        button = self.button(parent, f"{name}  ▾", lambda e: menu.tk_popup(e.x_root, e.y_root))

        def choose(value, text):
            button.set_text(f"{text}  ▾")
            self.save("audio", "input_device", value)

        for value, text in choices:
            menu.add_command(label=text, command=lambda v=value, t=text: choose(v, t))

    def build_cleanup(self):
        inner = self.card("Metin temizleme", 174)
        row = self.row(inner, "Sağlayıcı", None)
        self.segmented(row, [("auto", "Otomatik"), ("openrouter", "OpenRouter"), ("openai", "OpenAI"),
                             ("groq", "Groq"), ("none", "Kapalı")], self.cfg["llm"]["provider"]
                       if self.cfg["llm"]["provider"] != "custom" else "auto",
                       lambda v: self.save("llm", "provider", v)).pack(side="right")
        for name, label in (("openrouter", "OpenRouter anahtarı"), ("openai", "OpenAI anahtarı"),
                            ("groq", "Groq anahtarı")):
            self.key_row(inner, name, label)

    def key_row(self, parent, name, label):
        row = self.row(parent, label, None)
        width, height = self.s(232), self.s(26)
        holder = tk.Canvas(row, width=width, height=height, bg=CARD, highlightthickness=0, bd=0)
        holder.create_image(0, 0, anchor="nw", image=self.keep(_image(
            gfx.rounded_rect_png(width, height, self.s(6), FIELD, CARD))))
        entry = tk.Entry(holder, bg=FIELD, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0,
                         font=self.font, show="•", disabledbackground=FIELD)
        holder.create_window(self.s(10), height // 2, anchor="w", window=entry, width=width - self.s(44))
        clear = holder.create_text(width - self.s(14), height // 2, text="×", fill=MUTED,
                                   font=("Segoe UI", 12), state="hidden")
        # A label, because canvas items cannot sit on top of an embedded entry.
        hint = tk.Label(holder, bg=FIELD, fg=MUTED, font=self.font_small, bd=0, cursor="xterm")
        hint.bind("<Button-1>", lambda e: entry.focus_set())
        holder.pack(side="right")

        def show_state():
            has_key = bool(self.keys.get(name))
            if entry.get() or self.root.focus_get() is entry:
                hint.place_forget()
            else:
                hint.configure(text="••••••••  kayıtlı" if has_key else "Yapıştır ve Enter'a bas")
                hint.place(x=self.s(10), y=height // 2, anchor="w")
            holder.itemconfigure(clear, state="normal" if has_key else "hidden")

        def commit(_event=None):
            value = entry.get().strip()
            if value:
                self.set_key(name, value)
                entry.delete(0, "end")
                self.root.focus_set()
            show_state()

        def remove(_event):
            self.set_key(name, "")
            entry.delete(0, "end")
            show_state()

        holder.tag_bind(clear, "<Button-1>", remove)
        entry.bind("<FocusIn>", lambda e: show_state())
        entry.bind("<FocusOut>", commit)
        entry.bind("<Return>", commit)
        entry.bind("<KeyRelease>", lambda e: show_state())
        show_state()

    def build_behavior(self):
        inner = self.card("Davranış", 214)
        ins = self.cfg["insert"]
        self.toggle(self.row(inner, "Önceki panoyu geri getir"), ins["restore_clipboard"],
                    lambda v: self.save("insert", "restore_clipboard", v))
        self.toggle(self.row(inner, "Metnin sonuna boşluk ekle"), ins["trailing_space"],
                    lambda v: self.save("insert", "trailing_space", v))
        self.toggle(self.row(inner, "Kayıt göstergesini göster"), self.cfg["ui"]["pill"],
                    lambda v: self.save("ui", "pill", v))
        self.toggle(self.row(inner, "Oturum açılışında başlat"), tray.login_enabled(), self.set_login)
        self.toggle(self.row(inner, "Yönetici pencerelerinde de çalış",
                             "Yönetici olarak açılmış terminaller için. Her başlatmada Windows onay ister."),
                    self.cfg["app"]["run_as_admin"], lambda v: self.save("app", "run_as_admin", v))

    # ---- saving --------------------------------------------------------------

    def flash(self, message="Kaydedildi", color=OK):
        self.footer.configure(text=message, fg=color)
        if self._saved_after:
            self.root.after_cancel(self._saved_after)
        self._saved_after = self.root.after(
            1800, lambda: self.footer.configure(text="Değişiklikler otomatik uygulanır", fg=MUTED))

    def save(self, section, key, value):
        try:
            config.update_config(section, key, value)
            self.flash()
        except (OSError, config.ConfigError) as exc:
            log.error("could not save %s.%s: %s", section, key, exc)
            self.flash(f"Kaydedilemedi: {exc}", WARN)

    def set_key(self, name, value):
        try:
            config.update_env(config.KEY_NAMES[name], value)
            self.keys[name] = value
            self.flash("Anahtar kaydedildi" if value else "Anahtar silindi")
        except OSError as exc:
            log.error("could not save the %s key: %s", name, exc.__class__.__name__)
            self.flash("Anahtar kaydedilemedi", WARN)

    def set_login(self, enabled):
        try:
            tray.set_login(enabled)
            self.flash()
        except OSError as exc:
            self.flash(f"Kaydedilemedi: {exc}", WARN)


def _focus_existing():
    hwnd = w.user32.FindWindowW(None, TITLE)
    if hwnd:
        w.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        w.user32.SetForegroundWindow(hwnd)


def run_settings():
    w.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    w.shell32.SetCurrentProcessExplicitAppUserModelID("YDikte")
    mutex = w.kernel32.CreateMutexW(None, False, "Local\\YDikteSettings")
    if C.get_last_error() in (183, 5):
        _focus_existing()
        return 0
    root = tk.Tk()
    Settings(root)
    root.update_idletasks()
    width, height = root.winfo_reqwidth(), root.winfo_reqheight()
    x = (root.winfo_screenwidth() - width) // 2
    y = max(0, (root.winfo_screenheight() - height) // 2 - 20)
    root.geometry(f"+{x}+{y}")
    root.mainloop()
    del mutex
    return 0
