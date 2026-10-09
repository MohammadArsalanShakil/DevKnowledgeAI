#!/usr/bin/env bash
# macOS/Linux bootstrap; works with macOS's Bash 3.2 and newer Bash.
set -euo pipefail
fail() { printf 'Setup failed: %s\n' "$*" >&2; exit 1; }
repository='' destination="${HOME}/repos/DevKnowledgeAI" branch=''
install_prerequisites=0 check_only=0 skip_models=0
setup_args=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --repository-url|--destination|--branch|--books-dir)
            [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1"
            case "$1" in
                --repository-url) repository=$2 ;;
                --destination) destination=$2 ;;
                --branch) branch=$2 ;;
                --books-dir) setup_args+=(--books-dir "$2") ;;
            esac
            shift 2 ;;
        --install-prerequisites) install_prerequisites=1; shift ;;
        --download-books|--run) setup_args+=("$1"); shift ;;
        --skip-models) skip_models=1; setup_args+=("$1"); shift ;;
        --check-only) check_only=1; shift ;;
        --help|-h)
            printf '%s\n' 'Usage: bash install.sh [--repository-url https://github.com/OWNER/REPO] [--destination DIR] [--branch NAME] [--install-prerequisites] [--download-books | --books-dir DIR] [--run] [--skip-models] [--check-only]'
            exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done
system=$(uname -s)
case "$system" in Darwin|Linux) ;; *) fail 'Use install.ps1 on Windows.' ;; esac
if [ -n "$repository" ]; then
    [[ "$repository" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$ ]] || fail 'Repository URL must be HTTPS GitHub without credentials or query parameters.'
fi
# Homebrew Python is not necessarily on PATH, especially in the current shell.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
find_python() {
    local candidate resolved
    for candidate in "${DEVKNOWLEDGEAI_PYTHON:-}" python3.12 python3 python /opt/homebrew/opt/python@3.12/bin/python3.12 /usr/local/opt/python@3.12/bin/python3.12; do
        [ -n "$candidate" ] || continue
        if resolved=$("$candidate" -c 'import sys; sys.exit(1) if sys.version_info < (3,12) else None; print(sys.executable)' 2>/dev/null); then
            [ -n "$resolved" ] && { printf '%s\n' "$resolved"; return 0; }
        fi
    done
    return 1
}
python_path=$(find_python) || python_path=''
git_ready=0
# macOS can have a Git stub which requires Xcode Command Line Tools.
if command -v git >/dev/null 2>&1; then
    if [ "$system" != Darwin ] || xcode-select -p >/dev/null 2>&1 || [ "$(command -v git)" != /usr/bin/git ]; then
        git --version >/dev/null 2>&1 && git_ready=1
    fi
fi
venv_ready=0
if [ -n "$python_path" ] && "$python_path" -c 'import venv, ensurepip' >/dev/null 2>&1; then venv_ready=1; fi
if [ "$check_only" -eq 1 ]; then
    printf 'Python 3.12+: %s\nGit available: %s\nvenv/ensurepip available: %s\n' "$python_path" "$git_ready" "$venv_ready"
    [ -n "$python_path" ] && [ "$git_ready" -eq 1 ] && [ "$venv_ready" -eq 1 ] || fail 'Missing prerequisites.'
    exit 0
fi
as_admin() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else fail 'Administrator access is needed; sudo is unavailable.'; fi
}
if [ -z "$python_path" ] || [ "$git_ready" -eq 0 ] || [ "$venv_ready" -eq 0 ]; then
    [ "$install_prerequisites" -eq 1 ] || fail 'Install Python 3.12+ (with venv/ensurepip) and Git, or use --install-prerequisites.'
    if [ "$system" = Darwin ]; then
        command -v brew >/dev/null 2>&1 || fail 'Homebrew is missing. Install it from https://brew.sh, or install Python 3.12+ and Git manually.'
        [ -n "$python_path" ] && [ "$venv_ready" -eq 1 ] || brew install python@3.12
        [ "$git_ready" -eq 1 ] || brew install git
    elif command -v apt-get >/dev/null 2>&1; then
        packages=()
        if [ -z "$python_path" ]; then packages+=(python3 python3-venv)
        elif [ "$venv_ready" -eq 0 ]; then
            version=$("$python_path" -c 'import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))')
            packages+=("python${version}-venv")
        fi
        [ "$git_ready" -eq 1 ] || packages+=(git)
        as_admin apt-get update
        as_admin apt-get install -y "${packages[@]}"
    elif command -v dnf >/dev/null 2>&1; then
        packages=()
        [ -n "$python_path" ] && [ "$venv_ready" -eq 1 ] || packages+=(python3 python3-pip)
        [ "$git_ready" -eq 1 ] || packages+=(git)
        as_admin dnf install -y "${packages[@]}"
    else
        fail 'Automatic prerequisite installation supports Homebrew, apt-get, or dnf. Install Python 3.12+ and Git manually on this system.'
    fi
    hash -r
    python_path=$(find_python) || fail 'The system repository does not provide Python 3.12+. Install a supported Python manually; no third-party package repository was added.'
    "$python_path" -c 'import venv, ensurepip' || fail 'Python venv/ensurepip is unavailable. Install the matching venv package manually.'
    git --version >/dev/null || fail 'Git installation is unavailable.'
fi
if [ -n "$repository" ]; then
    # Resolve the destination without shell eval, including paths with spaces.
    destination=$("$python_path" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$destination")
    if [ -e "$destination" ]; then
        [ -e "$destination/.git" ] || fail 'Destination exists and is not a Git checkout. Choose another --destination.'
        origin=$(git -C "$destination" remote get-url origin) || fail 'Existing checkout has no origin.'
        origin=${origin%/}; origin=${origin%.git}
        expected=${repository%/}; expected=${expected%.git}
        [ "$origin" = "$expected" ] || fail 'Existing checkout has a different origin. Choose another --destination.'
        printf '%s\n' 'Reusing existing checkout without pulling or overwriting changes.'
    else
        clone_args=(clone)
        [ -z "$branch" ] || clone_args+=(--branch "$branch")
        git "${clone_args[@]}" -- "$repository" "$destination"
    fi
    project=$destination
else
    [ -f "${BASH_SOURCE[0]}" ] || fail 'Pass --repository-url when running a downloaded script.'
    project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fi
[ -f "$project/setup.py" ] || fail 'Project does not contain setup.py. Check the repository and branch.'
if [ "$install_prerequisites" -eq 1 ] && [ "$skip_models" -eq 0 ]; then setup_args+=(--install-ollama); fi
# Empty array expansion with nounset fails in Bash 3.2: use its compatible idiom.
"$python_path" "$project/setup.py" ${setup_args[@]+"${setup_args[@]}"}
