"""Unit tests for the parts with no Windows side effects, plus cloud calls against a local mock.

Run from the project folder: python -m unittest discover -s tests -v
"""

import http.server
import json
import logging
import sys
import threading
import time
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ydikte import config, hotkey, machine as m, net, pipeline  # noqa: E402
from ydikte.hotkey import Matcher  # noqa: E402

DEFAULT_TEXT = config.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")


def machine(guard=True):
    return m.Machine(m.Timing(), guard=guard)


class MachineTests(unittest.TestCase):
    def test_hold_records_then_transcribes(self):
        s = machine()
        self.assertEqual(s.feed(m.DOWN, 0.0), [m.START_REC])
        self.assertEqual(s.feed(m.TICK, 0.1), [])
        self.assertEqual(s.feed(m.TICK, 0.25), [m.SHOW_HOLD])
        self.assertEqual(s.feed(m.UP, 2.0), [m.FINISH_REC, m.SHOW_BUSY])
        self.assertEqual(s.state, m.PROCESSING)
        self.assertEqual(s.feed(m.DONE, 3.0), [m.HIDE_PILL])
        self.assertEqual(s.state, m.IDLE)

    def test_single_tap_drops_audio_and_shows_nothing(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        self.assertEqual(s.feed(m.UP, 0.08), [m.DISCARD_REC])
        self.assertEqual(s.feed(m.TICK, 1.0), [])
        self.assertEqual(s.state, m.IDLE)

    def test_double_tap_starts_hands_free_third_tap_stops(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.UP, 0.08)
        self.assertEqual(s.feed(m.DOWN, 0.2), [m.START_REC, m.SHOW_HANDS_FREE])
        self.assertEqual(s.feed(m.UP, 0.28), [])
        self.assertEqual(s.state, m.HANDS_FREE)
        self.assertEqual(s.feed(m.TICK, 60.0), [])
        self.assertEqual(s.feed(m.DOWN, 61.0), [m.FINISH_REC, m.SHOW_BUSY])
        self.assertEqual(s.feed(m.UP, 61.1), [])
        self.assertEqual(s.state, m.PROCESSING)

    def test_slow_second_tap_is_a_new_press(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.UP, 0.08)
        self.assertEqual(s.feed(m.DOWN, 1.0), [m.START_REC])
        self.assertEqual(s.state, m.PRESSED)

    def test_hands_free_auto_stops_at_five_minutes(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.UP, 0.08)
        s.feed(m.DOWN, 0.2)
        s.feed(m.UP, 0.3)
        self.assertEqual(s.feed(m.TICK, 299.0), [])
        self.assertEqual(s.feed(m.TICK, 300.3), [m.FINISH_REC, m.SHOW_BUSY, m.NOTIFY_AUTOSTOP])

    def test_held_session_is_capped_too(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.TICK, 0.3)
        self.assertEqual(s.feed(m.TICK, 301.0), [m.FINISH_REC, m.SHOW_BUSY, m.NOTIFY_AUTOSTOP])
        self.assertEqual(s.feed(m.UP, 302.0), [])

    def test_esc_drops_held_recording_and_release_does_not_restart(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.TICK, 0.3)
        self.assertEqual(s.feed(m.ESC, 1.0), [m.DISCARD_REC, m.SHOW_CANCELLED])
        self.assertEqual(s.feed(m.UP, 1.5), [])
        self.assertEqual(s.state, m.IDLE)

    def test_esc_drops_hands_free(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.UP, 0.08)
        s.feed(m.DOWN, 0.2)
        s.feed(m.UP, 0.3)
        self.assertEqual(s.feed(m.ESC, 5.0), [m.DISCARD_REC, m.SHOW_CANCELLED])
        self.assertEqual(s.state, m.IDLE)

    def test_esc_kills_running_transcription(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.TICK, 0.3)
        s.feed(m.UP, 2.0)
        self.assertEqual(s.feed(m.ESC, 2.5), [m.CANCEL_JOB, m.SHOW_CANCELLED])
        self.assertEqual(s.state, m.IDLE)

    def test_esc_when_idle_does_nothing(self):
        s = machine()
        self.assertEqual(s.feed(m.ESC, 0.0), [])

    def test_shortcut_with_modifier_hotkey_is_not_dictation(self):
        s = machine(guard=True)
        s.feed(m.DOWN, 0.0)
        self.assertEqual(s.feed(m.OTHER, 0.05), [m.DISCARD_REC])
        self.assertEqual(s.feed(m.TICK, 0.5), [])
        self.assertEqual(s.feed(m.UP, 0.6), [])
        self.assertEqual(s.state, m.IDLE)

    def test_slow_shortcut_cancels_after_pill_shows(self):
        s = machine(guard=True)
        s.feed(m.DOWN, 0.0)
        s.feed(m.TICK, 0.3)
        self.assertEqual(s.feed(m.OTHER, 0.5), [m.DISCARD_REC, m.HIDE_PILL])

    def test_late_key_does_not_cancel_dictation(self):
        s = machine(guard=True)
        s.feed(m.DOWN, 0.0)
        s.feed(m.TICK, 0.3)
        self.assertEqual(s.feed(m.OTHER, 3.0), [])
        self.assertEqual(s.state, m.HOLDING)

    def test_non_modifier_hotkey_ignores_other_keys(self):
        s = machine(guard=False)
        s.feed(m.DOWN, 0.0)
        self.assertEqual(s.feed(m.OTHER, 0.05), [])
        self.assertEqual(s.state, m.PRESSED)

    def test_press_during_processing_is_ignored(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.TICK, 0.3)
        s.feed(m.UP, 1.0)
        self.assertEqual(s.feed(m.DOWN, 1.2), [])
        self.assertEqual(s.feed(m.UP, 1.3), [])
        self.assertEqual(s.state, m.PROCESSING)

    def test_typing_between_taps_cancels_double_tap(self):
        s = machine()
        s.feed(m.DOWN, 0.0)
        s.feed(m.UP, 0.08)
        s.feed(m.OTHER, 0.1)
        self.assertEqual(s.feed(m.DOWN, 0.2), [m.START_REC])
        self.assertEqual(s.state, m.PRESSED)


RCTRL, LCTRL, C_KEY, SPACE, F13, CAPS = 0xA3, 0xA2, 0x43, 0x20, 0x7C, 0x14


class MatcherTests(unittest.TestCase):
    def test_modifier_passes_through(self):
        x = Matcher(hotkey.parse("rctrl"))
        self.assertEqual(x.on_key(RCTRL, 0, True), (False, ["down"]))
        self.assertEqual(x.on_key(RCTRL, 0, True), (False, []))  # auto-repeat
        self.assertEqual(x.on_key(C_KEY, 0, True), (False, ["other"]))
        self.assertEqual(x.on_key(C_KEY, 0, False), (False, []))
        self.assertEqual(x.on_key(RCTRL, 0, False), (False, ["up"]))
        self.assertTrue(x.only_modifiers)

    def test_left_ctrl_does_not_trigger_rctrl(self):
        x = Matcher(hotkey.parse("rctrl"))
        self.assertEqual(x.on_key(LCTRL, 0, True), (False, ["other"]))

    def test_non_modifier_is_swallowed_both_ways(self):
        x = Matcher(hotkey.parse("f13"))
        self.assertEqual(x.on_key(F13, 0, True), (True, ["down"]))
        self.assertEqual(x.on_key(F13, 0, True), (True, []))
        self.assertEqual(x.on_key(F13, 0, False), (True, ["up"]))
        self.assertFalse(x.only_modifiers)

    def test_chord_only_swallows_when_complete(self):
        x = Matcher(hotkey.parse("ctrl+space"))
        self.assertEqual(x.on_key(SPACE, 0, True), (False, []))
        self.assertEqual(x.on_key(SPACE, 0, False), (False, []))
        self.assertEqual(x.on_key(RCTRL, 0, True), (False, []))
        self.assertEqual(x.on_key(SPACE, 0, True), (True, ["down"]))
        self.assertEqual(x.on_key(RCTRL, 0, False), (False, ["up"]))
        self.assertEqual(x.on_key(SPACE, 0, False), (True, []))

    def test_esc_is_never_swallowed(self):
        x = Matcher(hotkey.parse("f13"))
        self.assertEqual(x.on_key(0x1B, 1, True), (False, ["esc"]))
        self.assertEqual(x.on_key(0x1B, 1, False), (False, []))

    def test_held_modifiers_reported_only_while_active(self):
        x = Matcher(hotkey.parse("ctrl+shift"))
        x.on_key(RCTRL, 0, True)
        self.assertEqual(x.held_modifiers(), [])
        x.on_key(0xA0, 0, True)
        self.assertEqual(x.held_modifiers(), [0xA0, RCTRL])
        self.assertEqual(Matcher(hotkey.parse("f13")).held_modifiers(), [])

    def test_scan_code_key(self):
        x = Matcher(hotkey.parse("sc:0x63"))
        self.assertEqual(x.on_key(0xFF, 0x63, True), (True, ["down"]))
        self.assertEqual(x.on_key(0xFF, 0x63, False), (True, ["up"]))

    def test_prune_recovers_missed_key_up(self):
        x = Matcher(hotkey.parse("rctrl"))
        x.on_key(RCTRL, 0, True)
        self.assertEqual(x.prune(lambda vk: True), [])
        self.assertEqual(x.prune(lambda vk: False), ["up"])
        self.assertFalse(x.active)
        self.assertEqual(x.on_key(RCTRL, 0, True), (False, ["down"]))

    def test_prune_leaves_swallowed_keys_alone(self):
        x = Matcher(hotkey.parse("f13"))
        x.on_key(F13, 0, True)
        self.assertEqual(x.prune(lambda vk: False), [])
        self.assertTrue(x.active)

    def test_mask_needed_for_win_and_alt(self):
        self.assertTrue(Matcher(hotkey.parse("ctrl+win")).needs_mask)
        self.assertFalse(Matcher(hotkey.parse("rctrl")).needs_mask)

    def test_bad_hotkeys_rejected(self):
        for text in ("", "esc", "bogus", "a", "space", "vk:zz", "vk:0x1b"):
            with self.subTest(text=text), self.assertRaises(hotkey.HotkeyError):
                hotkey.parse(text)
        hotkey.parse("ctrl+a")
        hotkey.parse("capslock")


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        cfg = config.parse_config("", DEFAULT_TEXT)
        self.assertEqual(cfg["transcription"]["backend"], "local")
        self.assertFalse(cfg["insert"]["restore_clipboard"])
        self.assertEqual(cfg["timing"]["max_recording_secs"], 300)
        hotkey.parse(cfg["hotkey"])

    def test_user_values_override_and_nested_defaults_survive(self):
        cfg = config.parse_config('[transcription]\nbackend="groq"\n', DEFAULT_TEXT)
        self.assertEqual(cfg["transcription"]["backend"], "groq")
        self.assertEqual(cfg["transcription"]["language"], "auto")

    def test_invalid_values_rejected(self):
        for text in ('[transcription]\nbackend="x"', '[insert]\nrestore_clipboard="yes"',
                     '[timing]\ndouble_tap_ms=-1', "not toml =", 'hotkey=1'):
            with self.subTest(text=text), self.assertRaises(config.ConfigError):
                config.parse_config(text, DEFAULT_TEXT)

    def test_env_parsing(self):
        env = config.parse_env('# c\nA=1\nexport B="two words"\nC=\'x#y\'\nD=abc # note\nnot a line\n')
        self.assertEqual(env, {"A": "1", "B": "two words", "C": "x#y", "D": "abc"})


class ConfigEditTests(unittest.TestCase):
    SAMPLE = ('# top comment\nhotkey = "rctrl"  # the key\n\n[insert]\n# about restore\n'
              'restore_clipboard = false\nmethod = "auto"\n\n[transcription.local]\nthreads = 0\n')

    def test_edits_value_and_keeps_comments(self):
        out = config.set_toml_value(self.SAMPLE, "insert", "restore_clipboard", True)
        self.assertIn("restore_clipboard = true", out)
        self.assertIn("# about restore", out)
        self.assertIn("# top comment", out)

    def test_top_level_key_keeps_its_trailing_comment(self):
        out = config.set_toml_value(self.SAMPLE, None, "hotkey", "ctrl+win")
        self.assertIn('hotkey = "ctrl+win"  # the key', out)

    def test_same_key_in_another_section_is_untouched(self):
        text = '[a]\nmodel = "x"\n[b]\nmodel = "y"\n'
        self.assertEqual(config.set_toml_value(text, "b", "model", "z"), '[a]\nmodel = "x"\n[b]\nmodel = "z"\n')

    def test_missing_key_and_section_are_added(self):
        out = config.set_toml_value(self.SAMPLE, "insert", "trailing_space", False)
        self.assertEqual(tomllib.loads(out)["insert"]["trailing_space"], False)
        out = config.set_toml_value(self.SAMPLE, "app", "run_as_admin", True)
        self.assertEqual(tomllib.loads(out)["app"]["run_as_admin"], True)
        out = config.set_toml_value('[a]\nb = 1\n', None, "hotkey", "f13")
        self.assertEqual(tomllib.loads(out), {"hotkey": "f13", "a": {"b": 1}})

    def test_string_with_hash_and_quote_round_trips(self):
        out = config.set_toml_value(self.SAMPLE, "insert", "method", 'a"b#c')
        self.assertEqual(tomllib.loads(out)["insert"]["method"], 'a"b#c')
        again = config.set_toml_value(out, "insert", "method", "paste")
        self.assertEqual(tomllib.loads(again)["insert"]["method"], "paste")

    def test_env_edit_keeps_other_lines(self):
        text = "# note\nOPENAI_API_KEY=old\nGROQ_API_KEY=g\n"
        self.assertEqual(config.set_env_value(text, "OPENAI_API_KEY", "new"),
                         "# note\nOPENAI_API_KEY=new\nGROQ_API_KEY=g\n")
        self.assertIn("OPENROUTER_API_KEY=x", config.set_env_value(text, "OPENROUTER_API_KEY", "x"))


class HotkeyCaptureTests(unittest.TestCase):
    def test_keysyms(self):
        from ydikte.settings_ui import combine_keys, keysym_to_name, pretty_hotkey
        self.assertEqual(keysym_to_name("Control_R"), "rctrl")
        self.assertEqual(keysym_to_name("F13"), "f13")
        self.assertEqual(keysym_to_name("a"), "a")
        self.assertIsNone(keysym_to_name("XF86AudioMute"))
        self.assertEqual(combine_keys({"space", "lshift", "lctrl"}), "lctrl+lshift+space")
        self.assertEqual(pretty_hotkey("rctrl"), "Sağ Ctrl")
        self.assertEqual(pretty_hotkey("lctrl+space"), "Sol Ctrl + Boşluk")
        hotkey.parse(combine_keys({"space", "lshift", "lctrl"}))


class TerminalTextTests(unittest.TestCase):
    def test_line_breaks_become_spaces(self):
        from ydikte.insert import type_for_terminal
        self.assertEqual(type_for_terminal("one\ntwo "), "one two ")
        self.assertEqual(type_for_terminal("one\r\ntwo"), "one two")
        self.assertEqual(type_for_terminal("plain text "), "plain text ")


class TextTests(unittest.TestCase):
    def test_tidy(self):
        self.assertEqual(pipeline.tidy_transcript(" hello\n world \n"), "hello world")
        for junk in ("[BLANK_AUDIO]", " (music) ", "Altyazı M.K.", "Thanks for watching!", "[Müzik]", ""):
            with self.subTest(junk=junk):
                self.assertEqual(pipeline.tidy_transcript(junk), "")
        self.assertEqual(pipeline.tidy_transcript("thank you for the report"), "thank you for the report")

    def test_accept_cleanup(self):
        raw = "um what is the capital of france"
        self.assertEqual(pipeline.accept_cleanup(raw, "What is the capital of France?"),
                         "What is the capital of France?")
        self.assertEqual(pipeline.accept_cleanup(raw, '"What is it?"'), "What is it?")
        self.assertEqual(pipeline.accept_cleanup(raw, "<transcript>What?</transcript>"), "What?")
        self.assertIsNone(pipeline.accept_cleanup(raw, ""))
        self.assertIsNone(pipeline.accept_cleanup(raw, "The capital of France is Paris. " * 8))

    def test_speech_energy(self):
        import array
        import math
        silence = bytes(32000)
        tone = array.array("h", (int(4000 * math.sin(i / 8)) for i in range(16000))).tobytes()
        self.assertFalse(pipeline.has_speech_energy(silence))
        self.assertTrue(pipeline.has_speech_energy(silence + tone))

    def test_too_short_and_silent_are_skipped_without_calling_anything(self):
        cfg = config.parse_config("", DEFAULT_TEXT)
        token = net.CancelToken()
        self.assertEqual(pipeline.process(bytes(3200), cfg, {}, token).skipped, "Çok kısa")
        self.assertEqual(pipeline.process(bytes(32000), cfg, {}, token).skipped, "Ses duyulmadı")


class _Mock(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.requests.append((self.path, dict(self.headers), body))
        status, reply = self.server.responder(self.path, body)
        if reply is None:   # hang until the client goes away
            self.server.hanging.set()
            try:
                self.connection.settimeout(10)
                while self.connection.recv(1024):
                    pass
                self.server.client_gone.set()
            except OSError:
                self.server.client_gone.set()
            return
        data = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Mock)
        self.server.requests = []
        self.server.hanging = threading.Event()
        self.server.client_gone = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)   # cleanups run last-added first
        self.pcm = self._speechlike()
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    @staticmethod
    def _speechlike():
        import array
        import math
        return array.array("h", (int(4000 * math.sin(i / 8)) for i in range(32000))).tobytes()

    def cfg(self, extra=""):
        return config.parse_config(
            f'[transcription]\nbackend="groq"\nfallback_to_local=false\n'
            f'[transcription.groq]\nbase_url="{self.base}"\n'
            f'[llm]\nprovider="openrouter"\nbase_url="{self.base}"\ntimeout_secs=2\n' + extra,
            DEFAULT_TEXT)

    def respond(self, whisper=None, chat=None):
        def responder(path, body):
            if path.endswith("/audio/transcriptions"):
                return whisper or (200, {"text": "um hello there"})
            return chat or (200, {"choices": [{"message": {"content": "Hello there."}}]})
        self.server.responder = responder

    def test_full_cloud_pipeline(self):
        self.respond()
        keys = {"groq": "gk-1", "openrouter": "or-1"}
        result = pipeline.process(self.pcm, self.cfg(), keys, net.CancelToken())
        self.assertEqual((result.text, result.backend, result.cleaned), ("Hello there.", "groq", True))
        (path, headers, body), (chat_path, chat_headers, chat_body) = self.server.requests
        self.assertEqual(path, "/v1/audio/transcriptions")
        self.assertEqual(headers["Authorization"], "Bearer gk-1")
        self.assertIn(b'name="model"', body)
        self.assertIn(b"whisper-large-v3-turbo", body)
        self.assertIn(b"RIFF", body)
        self.assertNotIn(b'name="language"', body)
        self.assertEqual(chat_path, "/v1/chat/completions")
        self.assertEqual(chat_headers["Authorization"], "Bearer or-1")
        sent = json.loads(chat_body)
        self.assertEqual(sent["model"], "openai/gpt-4o-mini")
        self.assertIn("<transcript>um hello there</transcript>", sent["messages"][1]["content"])

    def test_turkish_round_trip(self):
        self.respond(whisper=(200, {"text": "şey merhaba dünya"}),
                     chat=(200, {"choices": [{"message": {"content": "Merhaba dünya."}}]}))
        result = pipeline.process(self.pcm, self.cfg(), {"groq": "g", "openrouter": "o"}, net.CancelToken())
        self.assertEqual(result.text, "Merhaba dünya.")
        self.assertIn("şey", json.loads(self.server.requests[1][2])["messages"][1]["content"])

    def test_bad_llm_key_keeps_raw_and_warns(self):
        self.respond(chat=(401, {"error": {"message": "invalid key"}}))
        result = pipeline.process(self.pcm, self.cfg(), {"groq": "g", "openrouter": "o"}, net.CancelToken())
        self.assertEqual((result.text, result.cleaned), ("um hello there", False))
        self.assertIn("invalid key", result.warnings[0])

    def test_llm_offline_keeps_raw_without_warning(self):
        self.respond()
        cfg = self.cfg()
        cfg["llm"]["base_url"] = "http://127.0.0.1:9/v1"
        result = pipeline.process(self.pcm, cfg, {"groq": "g", "openrouter": "o"}, net.CancelToken())
        self.assertEqual((result.text, result.cleaned, result.warnings), ("um hello there", False, []))

    def test_no_llm_key_makes_no_llm_call(self):
        self.respond()
        result = pipeline.process(self.pcm, self.cfg(), {"groq": "g"}, net.CancelToken())
        self.assertEqual(result.text, "um hello there")
        self.assertEqual(len(self.server.requests), 1)

    def test_temperature_rejected_is_retried_without_it(self):
        calls = []

        def responder(path, body):
            if path.endswith("/audio/transcriptions"):
                return 200, {"text": "hello"}
            calls.append(json.loads(body))
            if "temperature" in calls[-1]:
                return 400, {"error": {"message": "Unsupported value: temperature"}}
            return 200, {"choices": [{"message": {"content": "Hello."}}]}
        self.server.responder = responder
        result = pipeline.process(self.pcm, self.cfg(), {"groq": "g", "openrouter": "o"}, net.CancelToken())
        self.assertEqual(result.text, "Hello.")
        self.assertEqual(len(calls), 2)

    def test_language_flag_is_sent(self):
        self.respond()
        cfg = self.cfg()
        cfg["transcription"]["language"] = "tr"
        pipeline.process(self.pcm, cfg, {"groq": "g"}, net.CancelToken())
        self.assertIn(b'name="language"', self.server.requests[0][2])

    def test_cancel_aborts_a_hanging_request_immediately(self):
        self.server.responder = lambda path, body: (200, None)
        token = net.CancelToken()
        outcome = []

        def run():
            try:
                pipeline.process(self.pcm, self.cfg(), {"groq": "g"}, token)
                outcome.append("finished")
            except net.Cancelled:
                outcome.append("cancelled")
        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(self.server.hanging.wait(5))
        start = time.monotonic()
        token.cancel()
        thread.join(3)
        self.assertEqual(outcome, ["cancelled"])
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertTrue(self.server.client_gone.wait(3), "socket was not closed")

    def test_auto_backend_picks_groq_then_openai_then_local(self):
        self.respond()
        cfg = self.cfg()
        cfg["transcription"]["backend"] = "auto"
        cfg["transcription"]["openai"]["base_url"] = self.base
        _, name = pipeline.transcribe(b"x", 1, cfg, {"openai": "k", "groq": "g"}, net.CancelToken(), [])
        self.assertEqual(name, "groq")
        _, name = pipeline.transcribe(b"x", 1, cfg, {"openai": "k"}, net.CancelToken(), [])
        self.assertEqual(name, "openai")
        cfg["transcription"]["local"]["exe"] = "does/not/exist.exe"
        with self.assertRaises(pipeline.TranscribeError):   # local chosen, not installed
            pipeline.transcribe(b"x", 1, cfg, {}, net.CancelToken(), [])


if __name__ == "__main__":
    unittest.main()
