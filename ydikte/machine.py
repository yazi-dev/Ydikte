"""The dictation state machine. Pure logic: no Windows calls, time is injected."""

from dataclasses import dataclass

# Inputs
DOWN, UP, OTHER, ESC, TICK, DONE, ABORT = "down", "up", "other", "esc", "tick", "done", "abort"

# Outputs
START_REC = "start_rec"          # open the mic
DISCARD_REC = "discard_rec"      # close the mic, throw the audio away
FINISH_REC = "finish_rec"        # close the mic, send the audio to the pipeline
CANCEL_JOB = "cancel_job"        # kill a transcription that is running
SHOW_HOLD = "show_hold"
SHOW_HANDS_FREE = "show_hands_free"
SHOW_BUSY = "show_busy"
HIDE_PILL = "hide_pill"
SHOW_CANCELLED = "show_cancelled"
NOTIFY_AUTOSTOP = "notify_autostop"

# States
IDLE, PRESSED, HOLDING, AWAIT_TAP, HANDS_FREE, PROCESSING, SUPPRESSED = (
    "idle", "pressed", "holding", "await_tap", "hands_free", "processing", "suppressed",
)

RECORDING_STATES = (PRESSED, HOLDING, HANDS_FREE)


@dataclass
class Timing:
    hold_threshold: float = 0.20   # shorter than this is a tap, longer is hold-to-talk
    double_tap: float = 0.35       # max gap between the two taps of a double-tap
    shortcut_guard: float = 0.80   # a key pressed this soon after the hotkey means "shortcut"
    max_recording: float = 300.0   # hard stop, for held and hands-free sessions alike


class Machine:
    """Feed it hotkey events and clock ticks, execute the actions it returns.

    The mic opens on key-down so the first word is not clipped. A tap or a
    shortcut such as RightCtrl+C closes it again and the audio is dropped.
    `guard` is true when the hotkey is made only of modifiers, because only then
    can pressing another key mean the user was typing a shortcut.
    """

    def __init__(self, timing=None, guard=True):
        self.timing = timing or Timing()
        self.guard = guard
        self.state = IDLE
        self.key_down = False
        self._at = 0.0
        self._until = 0.0

    def _set(self, state, at=0.0):
        self.state = state
        self._at = at

    def _dropped(self):
        return SUPPRESSED if self.key_down else IDLE

    def feed(self, event, now):
        if event == DOWN:
            self.key_down = True
        elif event == UP:
            self.key_down = False
        handler = getattr(self, "_on_" + self.state)
        return handler(event, now) or []

    def _press(self, now):
        self._set(PRESSED, now)
        return [START_REC]

    def _on_idle(self, event, now):
        if event == DOWN:
            return self._press(now)

    def _on_pressed(self, event, now):
        if event == UP:
            self._until = now + self.timing.double_tap
            self._set(AWAIT_TAP)
            return [DISCARD_REC]
        if event == OTHER and self.guard:
            self._set(SUPPRESSED)
            return [DISCARD_REC]
        if event == ESC:
            self._set(SUPPRESSED)
            return [DISCARD_REC]
        if event == ABORT:
            self._set(self._dropped())
            return [DISCARD_REC]
        if event == TICK and now - self._at >= self.timing.hold_threshold:
            self.state = HOLDING
            return [SHOW_HOLD]

    def _on_holding(self, event, now):
        if event == UP:
            self._set(PROCESSING)
            return [FINISH_REC, SHOW_BUSY]
        if event == OTHER and self.guard and now - self._at < self.timing.shortcut_guard:
            self._set(SUPPRESSED)
            return [DISCARD_REC, HIDE_PILL]
        if event == ESC:
            self._set(self._dropped())
            return [DISCARD_REC, SHOW_CANCELLED]
        if event == ABORT:
            self._set(self._dropped())
            return [DISCARD_REC, HIDE_PILL]
        if event == TICK and now - self._at >= self.timing.max_recording:
            self._set(PROCESSING)
            return [FINISH_REC, SHOW_BUSY, NOTIFY_AUTOSTOP]

    def _on_await_tap(self, event, now):
        if event == DOWN:
            if now <= self._until:
                self._set(HANDS_FREE, now)
                return [START_REC, SHOW_HANDS_FREE]
            return self._press(now)
        if event in (OTHER, ESC, ABORT):
            self._set(IDLE)
        elif event == TICK and now > self._until:
            self._set(IDLE)

    def _on_hands_free(self, event, now):
        if event == DOWN:
            self._set(PROCESSING)
            return [FINISH_REC, SHOW_BUSY]
        if event == ESC:
            self._set(self._dropped())
            return [DISCARD_REC, SHOW_CANCELLED]
        if event == ABORT:
            self._set(self._dropped())
            return [DISCARD_REC, HIDE_PILL]
        if event == TICK and now - self._at >= self.timing.max_recording:
            self._set(PROCESSING)
            return [FINISH_REC, SHOW_BUSY, NOTIFY_AUTOSTOP]

    def _on_processing(self, event, now):
        if event == ESC:
            self._set(IDLE)
            return [CANCEL_JOB, SHOW_CANCELLED]
        if event == ABORT:
            self._set(IDLE)
            return [CANCEL_JOB, HIDE_PILL]
        if event == DONE:
            self._set(IDLE)
            return [HIDE_PILL]

    def _on_suppressed(self, event, now):
        if event == UP:
            self._set(IDLE)
        elif event == DOWN:  # the matching key-up was lost, so this is a fresh press
            return self._press(now)
