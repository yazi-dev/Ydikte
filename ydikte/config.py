"""Settings (config.toml) and API keys (.env), all kept next to ydikte.pyw."""

import os
import re
import tomllib
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
CONFIG_PATH = HOME / "config.toml"
DEFAULT_CONFIG_PATH = HOME / "config.default.toml"
ENV_PATH = HOME / ".env"
ENV_EXAMPLE_PATH = HOME / ".env.example"
LOG_PATH = HOME / "ydikte.log"
ASSETS = HOME / "assets"

KEY_NAMES = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
}
_ENUMS = {
    ("transcription", "backend"): ("local", "groq", "openai", "auto"),
    ("llm", "provider"): ("auto", "openrouter", "openai", "groq", "custom", "none"),
    ("insert", "method"): ("auto", "paste", "type"),
}


class ConfigError(ValueError):
    pass


def _merge(base, override):
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _check_types(defaults, values, where=""):
    for key, default in defaults.items():
        value = values[key]
        name = f"{where}{key}"
        if isinstance(default, dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{name} must be a section")
            _check_types(default, value, name + ".")
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"{name} must be true or false")
        elif isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ConfigError(f"{name} must be a non-negative number")
        elif not isinstance(value, type(default)):
            raise ConfigError(f"{name} must be a string")


def parse_config(user_text, default_text):
    """Merge the user's TOML over the defaults and validate. Raises ConfigError."""
    defaults = tomllib.loads(default_text)
    try:
        user = tomllib.loads(user_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config.toml: {exc}") from None
    cfg = _merge(defaults, user)
    _check_types(defaults, cfg)
    for (section, key), allowed in _ENUMS.items():
        if cfg[section][key] not in allowed:
            raise ConfigError(f"{section}.{key} must be one of: {', '.join(allowed)}")
    return cfg


def load_config():
    default_text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(default_text, encoding="utf-8")
    return parse_config(CONFIG_PATH.read_text(encoding="utf-8"), default_text)


def parse_env(text):
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        env[key] = value
    return env


def load_keys():
    """API keys from .env, falling back to real environment variables."""
    env = {}
    if ENV_PATH.exists():
        env = parse_env(ENV_PATH.read_text(encoding="utf-8-sig"))
    return {
        name: env.get(var) or os.environ.get(var, "")
        for name, var in KEY_NAMES.items()
    }


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_toml_value(text, section, key, value):
    """Change one setting in TOML text, keeping every comment and all other lines.

    `section` is a name such as "insert", or None for a top-level key.
    """
    line = f"{key} = {_toml_value(value)}"
    lines = text.splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(\"(?:[^\"\\]|\\.)*\"|[^#]*?)\s*(#.*)?$")
    current = None
    first_header = None
    insert_at = None
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            if first_header is None:
                first_header = index
            current = stripped.strip("[]").strip()
            if current == section:
                insert_at = index + 1
            continue
        if current == section:
            match = pattern.match(raw)
            if match:
                comment = match.group(2)
                lines[index] = f"{line}  {comment}" if comment else line
                return "\n".join(lines) + "\n"
    if section is None:
        lines.insert(first_header if first_header is not None else len(lines), line)
    elif insert_at is not None:
        lines.insert(insert_at, line)
    else:
        lines += ["", f"[{section}]", line]
    return "\n".join(lines) + "\n"


def _write_atomic(path, text):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    temp.replace(path)


def update_config(section, key, value):
    """Save one setting. Refuses to write anything the app could not load."""
    text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() \
        else DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    updated = set_toml_value(text, section, key, value)
    parse_config(updated, DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    _write_atomic(CONFIG_PATH, updated)


def set_env_value(text, name, value):
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        if re.match(rf"^\s*(export\s+)?{re.escape(name)}\s*=", raw):
            lines[index] = f"{name}={value}"
            return "\n".join(lines) + "\n"
    lines.append(f"{name}={value}")
    return "\n".join(lines) + "\n"


def update_env(name, value):
    if ENV_PATH.exists():
        text = ENV_PATH.read_text(encoding="utf-8-sig")
    elif ENV_EXAMPLE_PATH.exists():
        text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    else:
        text = ""
    _write_atomic(ENV_PATH, set_env_value(text, name, value))


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else HOME / path


def stamp():
    """Changes when config.toml or .env changes."""
    parts = []
    for path in (CONFIG_PATH, ENV_PATH):
        try:
            parts.append(path.stat().st_mtime_ns)
        except OSError:
            parts.append(0)
    return tuple(parts)
