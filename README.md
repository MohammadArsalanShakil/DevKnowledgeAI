# DevKnowledgeAI

A local LangChain + Ollama CLI for chatting and asking questions grounded in PDF books.
Default models: `qwen3:1.7b` for chat and `all-minilm` for embeddings.
No cloud account or API key is required. CPU inference is supported; speed depends on hardware.

## Quick start

After cloning or downloading this repository, open a terminal in its folder.

Windows, including missing prerequisites when WinGet is available:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -InstallPrerequisites -DownloadBooks -Run
```

This installs missing Python 3.12+, Git, and Ollama, creates `.venv`, installs the
Python dependencies, downloads both models and the seven books, builds indexes,
and starts the CLI. Existing dependencies and local files are reused.
The execution-policy option applies only to this process; no machine-wide policy is changed.
The initial downloads and indexing can take several minutes.

macOS/Linux:

```bash
bash ./install.sh --install-prerequisites --download-books --run
```

Both bootstraps create the same Python environment, prepare Ollama and the models,
download optional books, build indexes, and launch the same app. `setup.py` is the
shared Windows/Linux/macOS setup implementation. Shell scripts have LF line endings
and are invoked with `bash`, so executable permissions are not required after ZIP extraction.

Automatic prerequisite installation uses WinGet on Windows, an existing Homebrew
installation on macOS, and apt-get or dnf on Linux. Package installation may ask
for administrator access. On macOS, install [Homebrew](https://brew.sh) first if
Python or Git is missing; its prerequisites may include Xcode Command Line Tools.
Older Linux distributions may not offer Python 3.12+. In that case, or on Linux
distributions using other package managers, install Python 3.12+ with venv/ensurepip
and Git manually. The script reports the limitation instead of adding package repositories.
Use operating system and architecture versions supported by Python, PyMuPDF, and
[Ollama](https://ollama.com/download); obsolete systems may not be supported.

If Python is already available, you can invoke the shared setup directly:

```bash
python3 setup.py --install-ollama --download-books --run
```

On Windows use `py setup.py` instead of `python3 setup.py`.

Use your own PDFs instead of downloading the reference books:

```powershell
py setup.py --books-dir "C:\path\to\books" --install-ollama --run
```

Or omit both book options to start with general local chat:

```powershell
py setup.py --install-ollama --run
```

Setup preserves an existing `.env` and creates one from `.env.example` if absent.
It prefers an installed Python 3.12 interpreter and otherwise uses Python 3.12+.
Set `DEVKNOWLEDGEAI_PYTHON` to an interpreter's absolute path to select it explicitly.
If WinGet or another system prerequisite is unavailable, the installer reports it.
It never signs in, creates an API key, or publishes a repository.

## Run after setup

Windows:

```powershell
.\.venv\Scripts\python.exe -m devknowledgeai
```

macOS/Linux:

```bash
./.venv/bin/python -m devknowledgeai
```

Commands:

- `/books`: list available books.
- `/sources`: inspect retrieved excerpts from the latest question.
- `/reset`: clear session history.
- `/exit`: quit.

Example questions: "How do I create a branch in Git?", "What is DbContext in
Entity Framework?", or "What does RETURNING id return after an INSERT in PostgreSQL?"

Focus on a particular book or run one question:

```powershell
.\.venv\Scripts\python.exe -m devknowledgeai --book PostgreSQL
.\.venv\Scripts\python.exe -m devknowledgeai --prompt "What is an interface in C#?"
.\.venv\Scripts\python.exe -m devknowledgeai --chat
```

`--book` matches filename text, case insensitive; repeat it for multiple books.
General questions search all selected books. Questions explicitly naming the
supported book topics use corresponding books; comparisons use the named books
together. `--chat` explicitly uses general knowledge without PDF grounding.
With no books present, the default CLI clearly announces general chat mode.

## PDF library

The optional reference library contains C#, Git, Entity Framework, SQL,
PostgreSQL, MySQL, and Microsoft SQL Server Notes for Professionals.
The repository includes links in `books.json`, not the PDFs themselves.
`--download-books` retrieves them directly from GoalKicker and leaves existing
copies untouched. See [third-party notices](THIRD_PARTY_NOTICES.md) and book credits.

Add more PDFs to `data/documents`, then run:

```powershell
.\.venv\Scripts\python.exe -m devknowledgeai --index
```

New or changed books are indexed automatically. Unchanged indexes are reused,
and interrupted embedding work resumes from saved batches. Removing a book from
the folder removes it from retrieval. Unused indexes may remain on disk.

Other options:

```powershell
.\.venv\Scripts\python.exe -m devknowledgeai --books-dir "C:\path\to\books"
.\.venv\Scripts\python.exe -m devknowledgeai --pdf "C:\path\one.pdf" "C:\path\two.pdf"
.\.venv\Scripts\python.exe -m devknowledgeai --search-only --prompt "Git branches"
.\.venv\Scripts\python.exe -m devknowledgeai --index --rebuild
```

Keep filenames unique. Scanned PDFs require OCR first; this app does not interpret
images or reconstruct complex tables. Relative paths resolve from the project folder.

## Evidence and limits

Citations identify the filename and physical PDF page, for example
`[GitNotesForProfessionals.pdf p.83]`. These are PDF viewer pages, not printed page labels.
The model receives a few relevant excerpts, not whole books. The app validates
evidence quotes and adds citations from exact source IDs, preventing confusion
between identical page numbers in different books. Code snippets must occur in
the retrieved text. PDF typography and whitespace are normalized during validation.
Unsupported or unverified answers are declined. These checks do not prove that
every generated claim is correct; use `/sources` to inspect important answers.
The books can describe older language and database versions.

## Configuration and local data

```text
OLLAMA_MODEL=qwen3:1.7b
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=all-minilm
RAG_PDF_DIR=data/documents
```

Keep Ollama running. PDFs and SQLite indexes remain local, outside Git; `.env`,
`.venv`, logs, and temporary downloads are also ignored. If you change model
names in `.env`, install those models yourself with `ollama pull MODEL_NAME`.

## Development

```powershell
py setup.py --skip-models
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

`requirements.txt` pins direct dependencies; `requirements.lock.txt` records the
tested full dependency set used by setup. CI tests Windows, Linux, and macOS with
Python 3.12 and 3.14. Each job runs the appropriate bootstrap with models skipped,
installs locked dependencies into a fresh virtual environment, and runs offline
unit tests without Ollama or books. Linux/macOS also test argument forwarding
and paths with spaces in the Bash bootstrap. Native macOS/Linux bootstrap smoke
tests run after upload; they have not been executed on those operating systems
during this Windows session.

Check prerequisites without changing the machine:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -CheckOnly
```

```bash
bash ./install.sh --check-only
```

## GitHub upload and remote installation

Upload this folder's **contents** at the repository root, including `.github`,
`.gitignore`, `.gitattributes`, and `.env.example`. Do not upload your local
`.env`, `.venv`, PDFs, or indexes. GitHub web uploads do not apply `.gitignore`
to a selected file: use the prepared source-only folder.

Once the repository is public, the bootstraps can clone it and call setup:

```powershell
.\install.ps1 -RepositoryUrl https://github.com/OWNER/REPO -InstallPrerequisites -DownloadBooks -Run
```

```bash
bash ./install.sh --repository-url https://github.com/OWNER/REPO --install-prerequisites --download-books --run
```

These URLs are placeholders. The repository URL and default branch
are needed to form the final remote one-command installer. No URL is hardcoded here.
An existing checkout is reused only if its origin matches; local changes are not pulled over.

No project license has been selected yet. Dependencies have separate licenses;
see [third-party notices](THIRD_PARTY_NOTICES.md).
