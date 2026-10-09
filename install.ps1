<#
Windows bootstrap. Can run locally or as a downloaded script block.
No repository is published and no account is signed in by this script.
Example after publishing: .\install.ps1 -RepositoryUrl https://github.com/OWNER/REPO -InstallPrerequisites -DownloadBooks -Run
#>
[CmdletBinding()]
param(
    [string]$RepositoryUrl,
    [string]$Destination = (Join-Path $HOME 'repos\DevKnowledgeAI'),
    [string]$Branch,
    [switch]$InstallPrerequisites,
    [switch]$DownloadBooks,
    [string]$BooksDirectory,
    [switch]$Run,
    [switch]$SkipModels,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'

function Invoke-Native {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable exited with code $LASTEXITCODE" }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Find-Python {
    # A missing preferred interpreter writes stderr in Windows PowerShell 5.1.
    # Treat failed probes as unavailable candidates, then try the next one.
    $ErrorActionPreference = 'Continue'
    if ($env:DEVKNOWLEDGEAI_PYTHON) {
        $candidate = & $env:DEVKNOWLEDGEAI_PYTHON -c 'import sys; sys.exit(1) if sys.version_info < (3,12) else None; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath ($candidate | Select-Object -Last 1))) {
            return ($candidate | Select-Object -Last 1)
        }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($selector in @('-3.12', '-3')) {
            $candidate = & $launcher.Source $selector -c 'import sys; sys.exit(1) if sys.version_info < (3,12) else None; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath ($candidate | Select-Object -Last 1))) {
                return ($candidate | Select-Object -Last 1)
            }
        }
    }
    foreach ($name in @('python', 'python3')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $candidate = & $command.Source -c 'import sys; sys.exit(1) if sys.version_info < (3,12) else None; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath ($candidate | Select-Object -Last 1))) {
                return ($candidate | Select-Object -Last 1)
            }
        }
    }
    return $null
}

function Install-Package {
    param([string]$Id)
    $manager = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $manager) { throw 'WinGet is unavailable. Install App Installer from Microsoft, or install Python 3.12+ and Git manually.' }
    Invoke-Native $manager.Source @('install', '--id', $Id, '--exact', '--source', 'winget', '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity')
    Refresh-Path
}

try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'Use bash install.sh on macOS/Linux.'
    }
    if ($RepositoryUrl -and $RepositoryUrl -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$') {
        throw 'RepositoryUrl must be an HTTPS GitHub repository URL, without credentials or query parameters.'
    }
    $pythonPath = Find-Python
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($CheckOnly) {
        Write-Output "Python 3.12+: $pythonPath"
        Write-Output "Git: $($git.Source)"
        if (-not $pythonPath -or -not $git) { throw 'One or more prerequisites are missing.' }
        return
    }
    if (-not $pythonPath) {
        if (-not $InstallPrerequisites) { throw 'Python 3.12+ is missing. Use -InstallPrerequisites or install it manually.' }
        Install-Package 'Python.Python.3.12'
        $pythonPath = Find-Python
        if (-not $pythonPath) { throw 'Python installed but could not be located. Open a new PowerShell window and rerun.' }
    }
    if (-not $git) {
        if (-not $InstallPrerequisites) { throw 'Git is missing. Use -InstallPrerequisites or install it manually.' }
        Install-Package 'Git.Git'
        $git = Get-Command git -ErrorAction SilentlyContinue
        if (-not $git) { throw 'Git installed but could not be located. Open a new PowerShell window and rerun.' }
    }
    if ($RepositoryUrl) {
        $destinationPath = [IO.Path]::GetFullPath($Destination)
        if (Test-Path -LiteralPath $destinationPath) {
            if (-not (Test-Path -LiteralPath (Join-Path $destinationPath '.git'))) { throw 'Destination exists and is not a Git checkout. Choose another -Destination.' }
            $origin = & $git.Source -C $destinationPath remote get-url origin
            if ($LASTEXITCODE -ne 0 -or ($origin.TrimEnd('/') -replace '\.git$', '') -ne ($RepositoryUrl.TrimEnd('/') -replace '\.git$', '')) {
                throw 'Existing checkout has a different origin. Choose another -Destination.'
            }
            Write-Host 'Reusing the existing checkout without pulling or overwriting changes.'
        } else {
            $cloneArguments = @('clone')
            if ($Branch) { $cloneArguments += @('--branch', $Branch) }
            $cloneArguments += @('--', $RepositoryUrl, $destinationPath)
            Invoke-Native $git.Source $cloneArguments
        }
        $projectPath = $destinationPath
    } else {
        if (-not $PSScriptRoot) { throw 'Pass -RepositoryUrl when executing a downloaded script block.' }
        $projectPath = $PSScriptRoot
    }
    $setupPath = Join-Path $projectPath 'setup.py'
    if (-not (Test-Path -LiteralPath $setupPath)) { throw 'The checkout does not contain setup.py. Check the repository and branch.' }
    $setupArguments = @($setupPath)
    if ($InstallPrerequisites) { $setupArguments += '--install-ollama' }
    if ($DownloadBooks) { $setupArguments += '--download-books' }
    if ($BooksDirectory) { $setupArguments += @('--books-dir', $BooksDirectory) }
    if ($Run) { $setupArguments += '--run' }
    if ($SkipModels) { $setupArguments += '--skip-models' }
    Invoke-Native $pythonPath $setupArguments
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
