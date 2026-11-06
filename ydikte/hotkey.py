"""Hotkey parsing and matching. Pure logic: no Windows calls."""

DOWN, UP, OTHER, ESC = "down", "up", "other", "esc"

VK_ESCAPE = 0x1B
L_CTRL, R_CTRL, L_SHIFT, R_SHIFT, L_ALT, R_ALT, L_WIN, R_WIN = (
    0xA2, 0xA3, 0xA0, 0xA1, 0xA4, 0xA5, 0x5B, 0x5C,
)

_MODIFIERS = {
    "ctrl": (L_CTRL, R_CTRL), "lctrl": (L_CTRL,), "rctrl": (R_CTRL,),
    "shift": (L_SHIFT, R_SHIFT), "lshift": (L_SHIFT,), "rshift": (R_SHIFT,),
    "alt": (L_ALT, R_ALT), "lalt": (L_ALT,), "ralt": (R_ALT,), "altgr": (R_ALT,),
    "win": (L_WIN, R_WIN), "lwin": (L_WIN,), "rwin": (R_WIN,),
}
_NAMED = {
    "capslock": 0x14, "scrolllock": 0x91, "pause": 0x13, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "apps": 0x5D, "menu": 0x5D,
    "numlock": 0x90,
}
_NAMED.update({f"f{n}": 0x6F + n for n in range(1, 25)})
_TYPING_VKS = {0x20, 0x09, 0x0D} | set(range(0x30, 0x3A)) | set(range(0x41, 0x5B))


class HotkeyError(ValueError):
    pass


class Part:
    """One key of the hotkey. `keys` are the VKs (or scan codes) that satisfy it."""

    def __init__(self, keys, is_scan=False, swallow=True):
        self.keys = keys
        self.is_scan = is_scan
        self.swallow = swallow

    def matches(self, vk, sc):
        return (sc if self.is_scan else vk) in self.keys


def _parse_int(text, token):
    try:
        return int(text, 0)
    except ValueError:
        raise HotkeyError(f"{token!r} içindeki tuş kodu geçersiz, örnek: vk:0x7C veya sc:0x5D") from None


def parse(text):
    tokens = [t.strip().lower() for t in str(text).split("+") if t.strip()]
    if not tokens:
        raise HotkeyError("kısayol boş")
    parts = []
    for tok in tokens:
        if tok in ("esc", "escape"):
            raise HotkeyError("Esc iptal için ayrılmış")
        if tok in _MODIFIERS:
            parts.append(Part(_MODIFIERS[tok], swallow=False))
        elif tok in _NAMED:
            parts.append(Part((_NAMED[tok],)))
        elif tok.startswith("vk:"):
            vk = _parse_int(tok[3:], tok)
            if vk == VK_ESCAPE:
                raise HotkeyError("Esc iptal için ayrılmış")
            is_mod = any(vk in keys for keys in _MODIFIERS.values())
            parts.append(Part((vk,), swallow=not is_mod))
        elif tok.startswith("sc:"):
            parts.append(Part((_parse_int(tok[3:], tok),), is_scan=True))
        elif len(tok) == 1 and tok.isascii() and tok.isalnum():
            parts.append(Part((ord(tok.upper()),)))
        else:
            raise HotkeyError(f"bilinmeyen tuş: {tok!r}")
    if len(parts) == 1 and not parts[0].is_scan and parts[0].keys[0] in _TYPING_VKS:
        raise HotkeyError(f"tek başına {tokens[0]!r} normal yazmayı bozar, ctrl+{tokens[0]} gibi birleştir")
    return parts


class Matcher:
    """Turns raw key events into hotkey events and decides what to swallow.

    Modifiers are always passed through, so RightCtrl+C keeps working when
    RightCtrl is the hotkey. Other hotkey keys are swallowed while the hotkey is
    active, so F13 or CapsLock do nothing else. Esc is never swallowed.
    """

    def __init__(self, parts):
        self.parts = parts
        self.down = [set() for _ in parts]
        self.active = False
        self._swallowed = set()

    @property
    def only_modifiers(self):
        return all(not p.swallow for p in self.parts)

    @property
    def needs_mask(self):
        """True if releasing the hotkey alone would open Start or focus a menu bar."""
        masked = {L_ALT, R_ALT, L_WIN, R_WIN}
        return any(not p.is_scan and masked & set(p.keys) for p in self.parts)

    def held_modifiers(self):
        """Hotkey modifiers currently held while the hotkey is active."""
        if not self.active:
            return []
        return sorted(key for part, down in zip(self.parts, self.down)
                      if not part.swallow and not part.is_scan for key in down)

    def reset(self):
        self.down = [set() for _ in self.parts]
        self.active = False
        self._swallowed.clear()

    def on_key(self, vk, sc, is_down):
        """Returns (swallow, events)."""
        if vk == VK_ESCAPE:
            return False, [ESC] if is_down else []
        index = next((i for i, p in enumerate(self.parts) if p.matches(vk, sc)), None)
        if index is None:
            return False, [OTHER] if is_down else []
        part = self.parts[index]
        key = sc if part.is_scan else vk
        events = []
        if is_down:
            self.down[index].add(key)  # auto-repeat lands here too and adds nothing
            if not self.active and all(self.down):
                self.active = True
                events.append(DOWN)
            if part.swallow and self.active:
                self._swallowed.add(key)
                return True, events
            return False, events
        self.down[index].discard(key)
        swallowed = key in self._swallowed
        self._swallowed.discard(key)
        if self.active and not all(self.down):
            self.active = False
            events.append(UP)
        return swallowed, events

    def prune(self, is_physically_down, skip=None):
        """Forget modifiers whose key-up we missed (lock screen, elevated window).

        Swallowed keys are left alone: Windows does not update the async key
        state for them, so they always read as released.
        """
        events = []
        for part, down in zip(self.parts, self.down):
            if part.is_scan or part.swallow:
                continue
            for key in list(down):
                if key != skip and not is_physically_down(key):
                    down.discard(key)
        if self.active and not all(self.down):
            self.active = False
            events.append(UP)
        return events
