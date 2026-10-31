# CraftMesh demo guard: keep the local HTTP server and localhost.run watchdog alive.
# Intentionally no non-ASCII characters: Windows PowerShell 5.1 reads .ps1 as ANSI unless BOM.
$ErrorActionPreference = 'Continue'

$Root      = 'C:\Users\xibei\Documents\deepseek-harness\default-workspace\clawhunt\1724-demo'
$PythonExe = 'C:\Users\xibei\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$SshExe    = 'C:\Users\xibei\AppData\Local\GitHubDesktop\app-3.6.7\resources\app\git\usr\bin\ssh.exe'
$KeyPath   = 'C:\Users\xibei\Documents\deepseek-harness\default-workspace\.scratch\lhr_rsa'
$TokenFile = 'C:\Users\xibei\.config\craftmesh\gh_token'
$LogDir    = Join-Path $Root 'data'
$LogFile   = Join-Path $LogDir 'guard.log'
$BaseUrl   = 'http://127.0.0.1:8787'

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }

function Write-GuardLog([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-DemoProcesses([string]$Pattern) {
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and ($_.CommandLine -match $Pattern)
        })
    } catch {
        Write-GuardLog ('process query failed: ' + $_.Exception.Message)
        return @()
    }
}

function Test-LocalHealth {
    try {
        $resp = Invoke-WebRequest -Uri ($BaseUrl + '/api/health') -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$serverProcs = Get-DemoProcesses 'server\.py.*--port\s+8787'
if ($serverProcs.Count -eq 0) {
    Write-GuardLog 'server.py not found; starting it'
    try {
        Start-Process -FilePath $PythonExe -ArgumentList @('server.py','--host','127.0.0.1','--port','8787') -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 500
            if (Test-LocalHealth) { break }
        }
        if (Test-LocalHealth) { Write-GuardLog 'server.py started and healthy' }
        else { Write-GuardLog 'server.py start attempted but health check still failing' }
    } catch {
        Write-GuardLog ('server.py start failed: ' + $_.Exception.Message)
    }
} else {
    Write-GuardLog ('server.py already running pid=' + (($serverProcs | ForEach-Object { $_.ProcessId }) -join ','))
}

$tunnelProcs = Get-DemoProcesses 'keep_public_tunnel\.ps1'
if ($tunnelProcs.Count -eq 0) {
    Write-GuardLog 'tunnel watchdog not found; starting it'
    $args = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', (Join-Path $Root 'scripts\keep_public_tunnel.ps1'),
        '-KeyPath', $KeyPath,
        '-RemoteUser', 'craftmesh5u60w8j6@fldubai.com@localhost.run',
        '-LocalPort', '8787',
        '-SshExe', $SshExe,
        '-PythonExe', $PythonExe,
        '-TokenFile', $TokenFile
    )
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $args -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
        Write-GuardLog 'tunnel watchdog start requested'
    } catch {
        Write-GuardLog ('tunnel watchdog start failed: ' + $_.Exception.Message)
    }
} else {
    Write-GuardLog ('tunnel watchdog already running pid=' + (($tunnelProcs | ForEach-Object { $_.ProcessId }) -join ','))
}

if (Test-LocalHealth) {
    Write-GuardLog 'local health OK'
} else {
    Write-GuardLog 'local health NOT OK'
}
