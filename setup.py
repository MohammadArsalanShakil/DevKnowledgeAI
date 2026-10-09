#!/usr/bin/env python3
"""Prepare an existing checkout. Python 3.12+ is required; no extra bootstrap packages.

Windows: py setup.py --install-ollama --download-books --run
macOS/Linux: python3 setup.py --install-ollama --download-books --run
Use --books-dir to copy your own PDF collection instead of downloading books.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE_URL = "http://localhost:11434"
DEFAULT_ENV = """OLLAMA_MODEL=qwen3:1.7b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=all-minilm
RAG_PDF_DIR=data/documents
"""


def ensure_environment():
    env_path = ROOT / ".env"
    if env_path.exists() and env_path.stat().st_size:
        return
    template = ROOT / ".env.example"
    content = template.read_text(encoding="utf-8-sig") if template.is_file() else DEFAULT_ENV
    # Read the template before opening the destination. An earlier failed setup
    # may have left an empty .env; repair only that case, preserving user settings.
    with env_path.open("w" if env_path.exists() else "x", encoding="utf-8") as handle:
        handle.write(content)


def run(command, **kwargs):
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def choose_python():
    candidates = []
    if os.environ.get("DEVKNOWLEDGEAI_PYTHON"):
        candidates.append([os.environ["DEVKNOWLEDGEAI_PYTHON"]])
    if os.name == "nt" and shutil.which("py"):
        candidates.append([shutil.which("py"), "-3.12"])
    if shutil.which("python3.12"):
        candidates.append([shutil.which("python3.12")])
    candidates.append([sys.executable])
    for candidate in candidates:
        try:
            result = subprocess.run(candidate + ["-c", "import sys; print(sys.executable); print(sys.version_info >= (3,12))"],
                                    capture_output=True, text=True, check=True, timeout=15)
            lines = result.stdout.strip().splitlines()
            if len(lines) >= 2 and lines[-1] == "True":
                return lines[-2]
        except (OSError, subprocess.SubprocessError):
            pass
    raise RuntimeError("Install Python 3.12 or newer, then rerun setup.")


def find_ollama():
    found = shutil.which("ollama")
    if found:
        return found
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        paths = [Path(base) / "Programs/Ollama/ollama.exe"] if base else []
    elif sys.platform == "darwin":
        paths = [Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama")]
    else:
        paths = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return next((str(path) for path in paths if path.is_file()), None)


def install_ollama(platform=None):
    platform = platform or sys.platform
    print("Installing Ollama from its official installer...", flush=True)
    if platform == "win32":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            raise RuntimeError("PowerShell is unavailable. Install Ollama from https://ollama.com/download")
        run([shell, "-NoProfile", "-Command", "irm https://ollama.com/install.ps1 | iex"])
    elif platform in {"linux", "darwin"}:
        with urllib.request.urlopen("https://ollama.com/install.sh", timeout=60) as response:
            script = response.read()
        run(["sh"], input=script)
    else:
        raise RuntimeError("Automatic Ollama installation supports Windows, macOS, and Linux.")


def api_ready():
    try:
        with urllib.request.urlopen(BASE_URL + "/api/version", timeout=2) as response:
            return bool(json.load(response).get("version"))
    except (OSError, ValueError):
        return False


def ensure_server(ollama):
    if api_ready():
        return
    print("Starting local Ollama...", flush=True)
    env = os.environ.copy()
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    options = dict(env=env, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    with (ROOT / "ollama-server.log").open("ab") as logfile:
        process = subprocess.Popen([ollama, "serve"], stdout=logfile, stderr=logfile, **options)
    for _ in range(60):
        if api_ready():
            return
        if process.poll() is not None:
            if api_ready():
                return
            raise RuntimeError("Ollama did not start. Check ollama-server.log.")
        time.sleep(1)
    raise RuntimeError("Ollama startup timed out. Check ollama-server.log and rerun.")


def download_pdf(url, destination):
    if destination.exists():
        print(f"Keeping existing {destination.name}")
        return
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "goalkicker.com":
        raise ValueError("Book URLs must use the original https://goalkicker.com host.")
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"Downloading {destination.name}...", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "DevKnowledgeAI-Setup/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            if urllib.parse.urlparse(response.url).hostname != "goalkicker.com":
                raise ValueError("Book download redirected away from the original host.")
            size = 0
            first = True
            while block := response.read(1024 * 1024):
                if first and not block.startswith(b"%PDF-"):
                    raise ValueError(f"The source did not return a PDF for {destination.name}.")
                first = False
                size += len(block)
                if size > 100 * 1024 * 1024:
                    raise ValueError("Book exceeds the 100 MB download limit.")
                output.write(block)
            if not size:
                raise ValueError("Empty book download.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_books(source_directory=None, download=False):
    target = ROOT / "data/documents"
    target.mkdir(parents=True, exist_ok=True)
    if source_directory:
        source = Path(source_directory).expanduser().resolve()
        if not source.is_dir():
            raise ValueError(f"Books folder does not exist: {source}")
        for path in source.iterdir():
            if path.is_file() and path.suffix.lower() == ".pdf":
                destination = target / path.name
                if not destination.exists():
                    shutil.copy2(path, destination)
    if download:
        for book in json.loads((ROOT / "books.json").read_text(encoding="utf-8-sig")):
            filename = book["filename"]
            if Path(filename).name != filename or not filename.lower().endswith(".pdf"):
                raise ValueError("Invalid book filename in books.json.")
            download_pdf(book["url"], target / filename)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--install-ollama", action="store_true", help="Install Ollama only if missing")
    parser.add_argument("--download-books", action="store_true", help="Download seven books from their original sites")
    parser.add_argument("--books-dir", type=Path, help="Copy your own PDFs into the local library")
    parser.add_argument("--skip-models", action="store_true", help="Only prepare Python dependencies and local files")
    parser.add_argument("--run", action="store_true", help="Launch the interactive app when setup finishes")
    args = parser.parse_args()
    if args.skip_models and args.run:
        parser.error("--skip-models cannot be combined with --run")
    python = choose_python()
    run([python, "--version"])
    venv = ROOT / ".venv"
    interpreter = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv.exists():
        run([python, "-m", "venv", venv])
    if not interpreter.is_file():
        raise RuntimeError("The existing .venv is unusable. Use a fresh checkout or rename it before retrying.")
    run([interpreter, "-c", "import sys; assert sys.version_info >= (3,12), 'Existing venv needs Python 3.12+'"])
    run([interpreter, "-m", "pip", "install", "-r", ROOT / "requirements.lock.txt"])
    run([interpreter, "-m", "pip", "check"])
    ensure_environment()
    prepare_books(args.books_dir, args.download_books)
    if not args.skip_models:
        ollama = find_ollama()
        if not ollama and args.install_ollama:
            install_ollama()
            ollama = find_ollama()
        if not ollama:
            raise RuntimeError("Ollama is missing. Rerun with --install-ollama, or install from https://ollama.com/download.")
        run([ollama, "--version"])
        ensure_server(ollama)
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "127.0.0.1:11434"
        for model in ("qwen3:1.7b", "all-minilm"):
            run([ollama, "pull", model], env=env)
        # Load .env using the installed parser so existing custom library paths work.
        config = subprocess.run([str(interpreter), "-c", "import json; from dotenv import dotenv_values; print(json.dumps(dict(dotenv_values('.env'))))"],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        settings = json.loads(config.stdout)
        library = Path(os.environ.get("RAG_PDF_DIR") or settings.get("RAG_PDF_DIR") or "data/documents").expanduser()
        if not library.is_absolute():
            library = ROOT / library
        if any(p.is_file() and p.suffix.lower() == ".pdf" for p in library.glob("*")):
            run([interpreter, "-m", "devknowledgeai", "--index"], cwd=ROOT)
        else:
            print("No books present. The app will start in general chat mode.")
    print("\nSetup complete. Run from the project folder:")
    print(r".\.venv\Scripts\python.exe -m devknowledgeai" if os.name == "nt" else "./.venv/bin/python -m devknowledgeai")
    if args.run:
        run([interpreter, "-m", "devknowledgeai"], cwd=ROOT)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun setup to resume.", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"\nSetup failed: {exc}", file=sys.stderr)
        sys.exit(1)
