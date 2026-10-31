param(
  [Parameter(Mandatory = $true)][string]$KeyPath,
  [Parameter(Mandatory = $true)][string]$RemoteUser,
  [int]$LocalPort = 8787,
  [string]$SshExe = "ssh.exe",
  [string]$LogPath = ""
)

# Keep a localhost.run SSH tunnel alive and re-connect with the same account key.
# The public hostname is tied to the registered SSH key, so it stays the same
# across reconnects while this account/key remains valid.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $LogPath) { $LogPath = Join-Path $Root "data\public-tunnel.log" }
$LogDir = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$KnownHosts = Join-Path $Root "data\known_hosts_lhr"

function Write-Log([string]$Text) {
  $line = "[" + (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK") + "] " + $Text
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

Write-Log "watchdog start localPort=$LocalPort user=$RemoteUser"
while ($true) {
  $sshArgs = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=$KnownHosts",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "ExitOnForwardFailure=yes",
    "-R", "80:127.0.0.1:$LocalPort",
    $RemoteUser
  )
  Write-Log "connecting"
  try {
    & $SshExe @sshArgs 2>&1 | ForEach-Object { Write-Log ("ssh: " + $_) }
  } catch {
    Write-Log ("ssh error: " + $_.Exception.Message)
  }
  Write-Log "disconnected, retry in 5s"
  Start-Sleep -Seconds 5
}
