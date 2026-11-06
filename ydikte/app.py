"""The background app: wires hook, state machine, mic, pipeline, pill and tray together."""

import ctypes as C
import logging
import queue
import subprocess
import threading
import time
from logging.handlers import RotatingFileHandler

from . import __version__, config, elevate, hotkey, machine as m, pipeline, tray as tray_mod
from . import winapi as w
from .audio import Recorder
from .hook import KeyboardHook
from .insert import foreground_blocks_input, insert_text, send_mask_key, send_plain_esc
from .net import Cancelled, CancelToken
from .pill import RED, Pill

log = logging.getLogger("ydikte")

WM_WAKE = w.WM_APP + 2
WM_SHOW_SETTINGS = w.WM_APP + 3
TIMER_FAST, TIMER_SLOW = 1, 2
FAST_MS, SLOW_MS = 66, 2000
REHOOK_SECS = 300
MSGFLT_ALLOW = 1
MAIN_CLASS = "YDikteMain"
CMD_ENABLED, CMD_LOGIN, CMD_SETTINGS, CMD_LOG, CMD_QUIT = 1, 2, 3, 4, 5


def setup_logging():
    handler = RotatingFileHandler(config.LOG_PATH, maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _timing(cfg):
    t = cfg["timing"]
    return m.Timing(
        hold_threshold=t["hold_threshold_ms"] / 1000,
        double_tap=t["double_tap_ms"] / 1000,
        shortcut_guard=t["shortcut_guard_ms"] / 1000,
        max_recording=float(t["max_recording_secs"]),
    )


class App:
    recorder_class = Recorder

    def __init__(self):
        self.cfg = config.load_config()
        self.keys = config.load_keys()
        self._stamp = config.stamp()
        self.enabled = True
        self.events = queue.SimpleQueue()
        self.job = None
        self._last_rehook = time.monotonic()
        parts = hotkey.parse(self.cfg["hotkey"])

        self._make_window()
        self.recorder = self.recorder_class(self.cfg["audio"]["input_device"])
        self.pill = Pill(lambda: self.recorder.level)
        self.pill.enabled = self.cfg["ui"]["pill"]
        self.icons = {name: tray_mod.load_icon(f"tray_{name}") for name in ("ready", "off", "live")}
        self.elevated = elevate.is_elevated()
        self._warned_elevated = False
        self.tray = tray_mod.Tray(self.hwnd)
        self._update_tray()

        self.hook = KeyboardHook(parts, self._on_hook_events, self._on_esc_rewrite)
        self.machine = m.Machine(_timing(self.cfg), guard=self.hook.only_modifiers)

        w.user32.SetTimer(self.hwnd, TIMER_SLOW, SLOW_MS, None)
        w.wtsapi32.WTSRegisterSessionNotification(self.hwnd, 0)
        pipeline.sweep_temp()
        log.info("started v%s, hotkey=%s, backend=%s, elevated=%s", __version__, self.cfg["hotkey"],
                 self.cfg["transcription"]["backend"], self.elevated)

    def _make_window(self):
        self._wndproc = w.WNDPROC(self._on_message)
        self._class = w.WNDCLASSW()
        self._class.lpfnWndProc = self._wndproc
        self._class.hInstance = w.kernel32.GetModuleHandleW(None)
        self._class.lpszClassName = MAIN_CLASS
        w.user32.RegisterClassW(C.byref(self._class))
        self._msg_taskbar = w.user32.RegisterWindowMessageW("TaskbarCreated")
        self.hwnd = w.user32.CreateWindowExW(0, MAIN_CLASS, "YDikte", 0, 0, 0, 0, 0,
                                             None, None, self._class.hInstance, None)
        # A second launch at normal rights must still reach an elevated copy.
        w.user32.ChangeWindowMessageFilterEx(self.hwnd, WM_SHOW_SETTINGS, MSGFLT_ALLOW, None)

    # ---- messages ------------------------------------------------------------

    def run(self):
        msg = w.W.MSG()
        while w.user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            w.user32.TranslateMessage(C.byref(msg))
            w.user32.DispatchMessageW(C.byref(msg))
        self._shutdown()

    def _on_message(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_WAKE:
                self._drain()
                return 0
            if message == w.WM_TIMER:
                self._on_timer(wparam)
                return 0
            if message == WM_SHOW_SETTINGS:
                self._open_settings()
                return 0
            if message == tray_mod.WM_TRAY:
                event = lparam & 0xFFFF
                if event == w.WM_RBUTTONUP:
                    self._open_menu()
                elif event == w.WM_LBUTTONUP:
                    self._open_settings()
                return 0
            if message == w.WM_WTSSESSION_CHANGE:
                if wparam == w.WTS_SESSION_LOCK:
                    self._feed(m.ABORT)
                elif wparam == w.WTS_SESSION_UNLOCK:
                    self.hook.rehook()
                return 0
            if message == self._msg_taskbar:
                self.tray.readd()
                return 0
            if message == w.WM_DESTROY:
                w.user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("error handling window message %#x", message)
        return w.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _post(self, item):
        self.events.put(item)
        w.user32.PostMessageW(self.hwnd, WM_WAKE, 0, 0)

    def _on_hook_events(self, events, when):
        """Runs on the hook thread: hand over and return at once."""
        self._post(("keys", events, when))

    def _on_esc_rewrite(self, held):
        """Runs on the hook thread. Keystrokes are sent from the main thread."""
        self._post(("call", lambda: send_plain_esc(held)))

    def _drain(self):
        while True:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                return
            if item[0] == "keys":
                for event in item[1]:
                    self._feed(event, item[2])
            else:
                item[1]()

    def _on_timer(self, timer_id):
        if timer_id == TIMER_FAST:
            self._feed(m.TICK)
            if self.machine.state in (m.PRESSED, m.HOLDING):
                self.hook.prune()
            if self.pill.animating:
                self.pill.tick()
            self._sync_fast_timer()
        elif timer_id == TIMER_SLOW:
            self._maybe_reload()
            self._warn_about_elevated_window()
            if time.monotonic() - self._last_rehook > REHOOK_SECS and self.machine.state == m.IDLE:
                self.hook.rehook()
                self._last_rehook = time.monotonic()

    def _warn_about_elevated_window(self):
        """The hotkey is deaf over an elevated window, so say why instead of just not working."""
        if self.elevated or self._warned_elevated or not self.enabled:
            return
        if foreground_blocks_input():
            self._warned_elevated = True
            log.info("focused window is elevated, hotkey cannot work there")
            self.tray.notify(
                "YDikte bu pencerede çalışamaz",
                "Pencere yönetici olarak açılmış. Windows bu yüzden kısayolu engelliyor. "
                "Çözüm: Ayarlar > Yönetici pencerelerinde de çalış.", warning=True)

    def _sync_fast_timer(self):
        needed = self.pill.animating or self.machine.state != m.IDLE
        if needed:
            w.user32.SetTimer(self.hwnd, TIMER_FAST, FAST_MS, None)
        else:
            w.user32.KillTimer(self.hwnd, TIMER_FAST)

    # ---- state machine actions ----------------------------------------------

    def _feed(self, event, now=None):
        if event == m.DOWN and self.hook.needs_mask:
            send_mask_key()
        before = self.machine.state
        for action in self.machine.feed(event, now if now is not None else time.monotonic()):
            self._do(action)
        if before != self.machine.state:
            self._update_tray()
        self._sync_fast_timer()

    def _do(self, action):
        if action == m.START_REC:
            self.recorder.start(self._on_mic_error)
        elif action == m.DISCARD_REC:
            self.recorder.discard()
        elif action == m.FINISH_REC:
            self._start_job(self.recorder.finish())
        elif action == m.CANCEL_JOB:
            if self.job:
                self.job.cancel()
                self.job = None
            log.info("transcription cancelled")
        elif action == m.SHOW_HOLD:
            self.pill.show_hold()
        elif action == m.SHOW_HANDS_FREE:
            self.pill.show_hands_free()
        elif action == m.SHOW_BUSY:
            self.pill.show_busy()
        elif action == m.HIDE_PILL:
            self.pill.hide()
        elif action == m.SHOW_CANCELLED:
            self.pill.show_flash("İptal edildi", seconds=0.8)
        elif action == m.NOTIFY_AUTOSTOP:
            limit = int(self.cfg["timing"]["max_recording_secs"])
            self.tray.notify("YDikte", f"Kayıt {limit // 60} dakika sonunda kendiliğinden durdu.")

    def _on_mic_error(self, message):
        def report():
            self._feed(m.ABORT)
            self.pill.show_flash("Mikrofon yok", RED, 2.5)
            self._sync_fast_timer()
            self.tray.notify(
                "YDikte: mikrofon açılamadı",
                "Ayarlar > Gizlilik ve güvenlik > Mikrofon: \"Masaüstü uygulamalarının "
                "mikrofonunuza erişmesine izin verin\" açık olmalı.", warning=True)
        self._post(("call", report))

    # ---- transcription job ---------------------------------------------------

    def _start_job(self, audio_future):
        token = CancelToken()
        self.job = token
        cfg, keys = self.cfg, self.keys

        def stage(label):
            self._post(("call", lambda: self._job_stage(token, label)))

        def work():
            outcome = {}
            try:
                pcm = audio_future.result(timeout=5)
                result = pipeline.process(pcm, cfg, keys, token, stage)
                outcome["result"] = result
                if result.text:
                    token.check()
                    text = result.text + (" " if cfg["insert"]["trailing_space"] else "")
                    warning = insert_text(text, cfg["insert"]["restore_clipboard"], token,
                                          cfg["insert"]["method"])
                    if warning:
                        result.warnings.append(warning)
                log.info("done: seconds=%.1f loudness=%d backend=%s cleaned=%s timings=%s chars=%d skipped=%r",
                         len(pcm) / 32000, result.loudness, result.backend, result.cleaned,
                         {k: round(v, 2) for k, v in result.timings.items()},
                         len(result.text), result.skipped)
            except Cancelled:
                return
            except pipeline.TranscribeError as exc:
                log.error("transcription failed: %s", exc)
                outcome["error"] = str(exc)
            except Exception as exc:
                log.exception("job failed")
                outcome["error"] = f"{type(exc).__name__}: {exc}"
            self._post(("call", lambda: self._job_done(token, outcome)))

        threading.Thread(target=work, name="job", daemon=True).start()

    def _job_stage(self, token, label):
        if token is self.job and self.machine.state == m.PROCESSING:
            self.pill.show_busy(label)

    def _job_done(self, token, outcome):
        if token is not self.job:
            return    # cancelled meanwhile
        self.job = None
        self._feed(m.DONE)
        result = outcome.get("result")
        if "error" in outcome:
            self.pill.show_flash("Yazıya dökülemedi", RED, 2.5)
            self.tray.notify("YDikte: yazıya dökülemedi", outcome["error"], warning=True)
        elif result and result.skipped:
            self.pill.show_flash(result.skipped)
        if result:
            for warning in result.warnings:
                self.tray.notify("YDikte", warning, warning=True)
        self._sync_fast_timer()

    # ---- tray ----------------------------------------------------------------

    def _status_text(self):
        t = self.cfg["transcription"]
        backend = {"local": "yerel", "auto": "otomatik"}.get(t["backend"], t["backend"])
        target = pipeline.llm_target(self.cfg, self.keys)
        admin = "  ·  yönetici" if self.elevated else ""
        return f"{self.cfg['hotkey']}  ·  {backend}  ·  temizleme {'açık' if target else 'kapalı'}{admin}"

    def _update_tray(self):
        state = getattr(getattr(self, "machine", None), "state", m.IDLE)
        if not self.enabled:
            icon, tip = "off", "YDikte: kapalı"
        elif state in m.RECORDING_STATES:
            icon, tip = "live", "YDikte: kayıt yapıyor"
        elif state == m.PROCESSING:
            icon, tip = "ready", "YDikte: yazıya döküyor"
        else:
            icon, tip = "ready", f"YDikte: hazır ({self.cfg['hotkey']})"
        self.tray.set(self.icons[icon], tip)

    def _open_menu(self):
        items = [
            (0, f"YDikte {__version__}  ·  {self._status_text()}", w.MF_GRAYED),
            None,
            (CMD_ENABLED, "Açık", w.MF_CHECKED if self.enabled else 0),
            (CMD_LOGIN, "Oturum açılışında başlat", w.MF_CHECKED if tray_mod.login_enabled() else 0),
            None,
            (CMD_SETTINGS, "Ayarlar…", 0),
            (CMD_LOG, "Günlüğü aç", 0),
            None,
            (CMD_QUIT, "Çıkış", 0),
        ]
        chosen = self.tray.popup(items)
        if chosen == CMD_ENABLED:
            self._set_enabled(not self.enabled)
        elif chosen == CMD_LOGIN:
            tray_mod.set_login(not tray_mod.login_enabled())
        elif chosen == CMD_SETTINGS:
            self._open_settings()
        elif chosen == CMD_LOG:
            subprocess.Popen(["notepad.exe", str(config.LOG_PATH)], close_fds=True)
        elif chosen == CMD_QUIT:
            w.user32.DestroyWindow(self.hwnd)

    @staticmethod
    def _open_settings():
        subprocess.Popen([str(elevate.pythonw()), str(config.HOME / "ydikte.pyw"), "--settings"],
                         cwd=str(config.HOME), close_fds=True)

    def _set_enabled(self, enabled):
        if not enabled:
            self._feed(m.ABORT)
            self.machine.key_down = False
            self.machine.state = m.IDLE
        self.enabled = enabled
        self.hook.set_enabled(enabled)
        self._update_tray()
        log.info("enabled=%s", enabled)

    # ---- settings reload -----------------------------------------------------

    def _maybe_reload(self):
        stamp = config.stamp()
        if stamp == self._stamp or self.machine.state != m.IDLE:
            return
        self._stamp = stamp
        try:
            cfg = config.load_config()
            parts = hotkey.parse(cfg["hotkey"])
        except (config.ConfigError, hotkey.HotkeyError) as exc:
            log.error("settings not applied: %s", exc)
            self.tray.notify("YDikte: ayarlar uygulanmadı", str(exc), warning=True)
            return
        admin_changed = cfg["app"]["run_as_admin"] != self.cfg["app"]["run_as_admin"]
        self.cfg = cfg
        if admin_changed and self._apply_admin_setting():
            return
        self.keys = config.load_keys()
        self.hook.set_parts(parts)
        self.machine = m.Machine(_timing(cfg), guard=self.hook.only_modifiers)
        self.recorder.device_name = cfg["audio"]["input_device"]
        self.pill.enabled = cfg["ui"]["pill"]
        self._update_tray()
        log.info("settings reloaded, hotkey=%s, backend=%s", cfg["hotkey"], cfg["transcription"]["backend"])

    def _apply_admin_setting(self):
        """Returns True if this copy is exiting because the rights have to change."""
        wanted = self.cfg["app"]["run_as_admin"]
        if wanted == self.elevated:
            return False
        if wanted:
            if not elevate.relaunch_elevated():
                self.tray.notify("YDikte", "Windows onayı verilmedi, normal yetkiyle çalışmaya devam ediliyor.")
                return False
        elif not elevate.relaunch_normal():
            self.tray.notify("YDikte", "Normal yetkiye dönmek için YDikte'den çıkıp yeniden başlat.")
            return False
        w.user32.DestroyWindow(self.hwnd)
        return True

    def _shutdown(self):
        if self.job:
            self.job.cancel()
        self.recorder.discard()
        self.tray.remove()
        w.wtsapi32.WTSUnRegisterSessionNotification(self.hwnd)
        log.info("stopped")


def _acquire_instance(relaunched):
    """Returns the mutex, or None if another copy runs. A relaunch waits for its parent to exit."""
    deadline = time.monotonic() + 6
    while True:
        mutex = w.kernel32.CreateMutexW(None, False, "Local\\YDikteSingleInstance")
        error = C.get_last_error()
        # 183: it exists. 5: it exists and belongs to an elevated copy.
        if mutex and error != 183:
            return mutex
        if mutex:
            w.kernel32.CloseHandle(mutex)
        if not relaunched or time.monotonic() > deadline:
            return None
        time.sleep(0.2)


def run_app(app_class=App, relaunched=False):
    w.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))  # per-monitor v2
    w.shell32.SetCurrentProcessExplicitAppUserModelID("YDikte")
    setup_logging()
    mutex = _acquire_instance(relaunched)
    if mutex is None:
        # Already running: opening it again means "show me the settings".
        existing = w.user32.FindWindowW(MAIN_CLASS, None)
        if existing and not relaunched:
            w.user32.PostMessageW(existing, WM_SHOW_SETTINGS, 0, 0)
        return 0
    try:
        cfg = config.load_config()
        if cfg["app"]["run_as_admin"] and not elevate.is_elevated() and not relaunched:
            w.kernel32.CloseHandle(mutex)   # the elevated copy needs it
            if elevate.relaunch_elevated():
                return 0
            mutex = _acquire_instance(False)    # consent refused: run normally
        app = app_class()
    except (config.ConfigError, hotkey.HotkeyError) as exc:
        log.error("cannot start: %s", exc)
        w.user32.MessageBoxW(None, f"config.toml dosyasını düzeltip yeniden başlat.\n\n{exc}", "YDikte",
                             w.MB_ICONWARNING)
        return 1
    if not config.ENV_PATH.exists() and app.cfg["llm"]["provider"] != "none":
        log.info("no .env: cleanup is off, raw transcripts will be inserted")
    app.run()
    del mutex
    return 0


__all__ = ["App", "run_app"]
