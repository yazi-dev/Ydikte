"""Set up YDikte: download whisper.cpp and a model, create config files and a shortcut.

  python install.py                  CPU build, small model
  python install.py --gpu            NVIDIA CUDA build (about 685 MB download, 2 GB on disk)
  python install.py --model medium   more accurate, slower, 1.5 GB
  python install.py --no-shortcut    do not create a Desktop shortcut
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HOME = Path(__file__).resolve().parent
WHISPER = HOME / "whisper"
BIN = WHISPER / "bin"
MODELS = WHISPER / "models"
_RELEASES = "https://github.com/ggml-org/whisper.cpp/releases/download"

BUILDS = {
    "cpu": (f"{_RELEASES}/v1.9.2/whisper-bin-x64.zip",
            "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a"),
    "gpu": (f"{_RELEASES}/b5454/whisper-bin-win-cuda-12.4.0-x64.zip",
            "afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a"),
}
MODEL_FILES = {
    "small": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    "medium": "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208",
}
_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{}.bin"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, dest, expected):
    if dest.exists() and sha256(dest) == expected:
        print(f"  already downloaded: {dest.name}")
        return
    print(f"  downloading {url}")
    partial = dest.with_name(dest.name + ".part")
    last = [-1]

    def progress(blocks, block_size, total):
        if total > 0:
            percent = min(100, blocks * block_size * 100 // total)
            if percent >= last[0] + 10:
                last[0] = percent
                print(f"    {percent}%", flush=True)

    urllib.request.urlretrieve(url, partial, progress)
    actual = sha256(partial)
    if actual != expected:
        partial.unlink()
        sys.exit(f"Checksum mismatch for {url}\n  expected {expected}\n  got      {actual}")
    partial.replace(dest)


def install_whisper(kind):
    url, expected = BUILDS[kind]
    marker = BIN / ".build"
    if marker.exists() and marker.read_text() == expected and (BIN / "whisper-cli.exe").exists():
        print(f"  whisper.cpp ({kind}) already installed")
        return
    with tempfile.TemporaryDirectory(prefix="yd-install-") as tmp:
        archive = Path(tmp) / "whisper.zip"
        download(url, archive, expected)
        print("  unpacking")
        if BIN.exists():
            shutil.rmtree(BIN)
        BIN.mkdir(parents=True)
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                base = name.rsplit("/", 1)[-1]
                # Only whisper-cli and its DLLs. The archive's other tools are not needed.
                if base == "whisper-cli.exe" or base.lower().endswith(".dll"):
                    with zf.open(name) as src, open(BIN / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    marker.write_text(expected)


def check_runs():
    """Smart App Control can refuse an executable, so find out now."""
    print("  checking that Windows allows whisper-cli to run (first GPU run can take minutes)")
    try:
        done = subprocess.run([str(BIN / "whisper-cli.exe"), "--help"], cwd=BIN, capture_output=True,
                              timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 4551:
            print("\n  Smart App Control blocked whisper-cli.exe. Local transcription will not work.\n"
                  "  Set backend = \"groq\" or \"openai\" in config.toml instead, or see the README.")
            return False
        raise
    if done.returncode != 0:
        print(f"  whisper-cli exited with {done.returncode}: {done.stderr[-300:]!r}")
        return False
    return True


def write_config(model):
    default = HOME / "config.default.toml"
    config = HOME / "config.toml"
    if not config.exists():
        text = default.read_text(encoding="utf-8")
        config.write_text(text.replace("ggml-small.bin", f"ggml-{model}.bin"), encoding="utf-8")
        print("  created config.toml")
    else:
        text = config.read_text(encoding="utf-8")
        if f"ggml-{model}.bin" not in text:
            for other in MODEL_FILES:
                text = text.replace(f"ggml-{other}.bin", f"ggml-{model}.bin")
            config.write_text(text, encoding="utf-8")
            print(f"  config.toml now uses the {model} model")
    env = HOME / ".env"
    if not env.exists():
        shutil.copy(HOME / ".env.example", env)
        print("  created .env (add your API keys there)")


def create_shortcut():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    # The copy in the project folder is how YDikte drops back to normal rights.
    script = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        f"foreach($p in \"$d\\YDikte.lnk\",'{HOME / 'YDikte.lnk'}'){{"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
        f"$s.TargetPath='{pythonw}';"
        f"$s.Arguments='\"{HOME / 'ydikte.pyw'}\"';"
        f"$s.WorkingDirectory='{HOME}';"
        f"$s.IconLocation='{HOME / 'assets' / 'logo.ico'}';"
        "$s.Description='YDikte';"
        "$s.Save()}"
    )
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    print("  created Desktop shortcut YDikte" if done.returncode == 0
          else f"  could not create the shortcut: {done.stderr.strip()[:200]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--gpu", action="store_true", help="install the NVIDIA CUDA build")
    parser.add_argument("--model", choices=MODEL_FILES, default="small")
    parser.add_argument("--no-shortcut", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11 or newer is required.")

    MODELS.mkdir(parents=True, exist_ok=True)
    print("whisper.cpp:")
    install_whisper("gpu" if args.gpu else "cpu")
    print("model:")
    download(_MODEL_URL.format(args.model), MODELS / f"ggml-{args.model}.bin", MODEL_FILES[args.model])
    print("settings:")
    write_config(args.model)
    ok = check_runs()
    if not args.no_shortcut:
        create_shortcut()
    print("\nDone." if ok else "\nInstalled with a problem, see above.")
    print("Start it from the YDikte shortcut, or: pythonw ydikte.pyw")


if __name__ == "__main__":
    main()
