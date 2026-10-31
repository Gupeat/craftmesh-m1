param(
  [Parameter(Mandatory = $true)][string]$KeyPath,
  [Parameter(Mandatory = $true)][string]$RemoteUser,
  [int]$LocalPort = 8787,
  [string]$SshExe = "ssh.exe",
  [string]$PythonExe = "python",
  [string]$Repo = "Gupeat/craftmesh-m1",
  [string]$TokenFile = "",
  [string]$LogPath = ""
)

# Keep a localhost.run SSH tunnel alive and publish its current public URL to
# GitHub Pages (docs/live.json), so the stable entry always links to the live demo.
# The free tunnel hostname can change on reconnect; the Pages entry never changes.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $LogPath) { $LogPath = Join-Path $Root "data\public-tunnel.log" }
$LogDir = Split-Path -Parent $LogPath
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$KnownHosts = Join-Path $Root "data\known_hosts_lhr"
$Publisher = Join-Path $Root "scripts\publish_demo_url.py"
if (-not $TokenFile) { $TokenFile = Join-Path $env:USERPROFILE ".config\craftmesh\gh_token" }
$LivePath = Join-Path $Root "docs\live.json"

function Write-Log([string]$Text) {
  $line = "[" + (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK") + "] " + $Text
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

function Get-Live {
  if (-not (Test-Path $LivePath)) { return $null }
  try { return (Get-Content -Raw -Path $LivePath | ConvertFrom-Json) } catch { return $null }
}

function Publish-Url([string]$Url, [string]$Status) {
  if (-not (Test-Path $Publisher)) { Write-Log "publisher missing: $Publisher"; return }
  if (-not $env:GITHUB_TOKEN -and (Test-Path $TokenFile)) {
    try { $env:GITHUB_TOKEN = (Get-Content -Raw -Path $TokenFile).Trim() } catch { }
  }
  $arguments = @($Publisher, "--url", $Url, "--status", $Status, "--repo", $Repo)
  Write-Log "publish $Status $Url"
  try {
    & $PythonExe @arguments 2>&1 | ForEach-Object { Write-Log ("publish: " + $_) }
  } catch {
    Write-Log ("publish error: " + $_.Exception.Message)
  }
}

Write-Log "watchdog start localPort=$LocalPort user=$RemoteUser"
$lastUrl = ""
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
    & $SshExe @sshArgs 2>&1 | ForEach-Object {
      $text = [string]$_
      $match = [regex]::Match($text, "https://[A-Za-z0-9.-]+\.lhr\.life")
      if ($match.Success) {
        $url = $match.Value
        if ($url -ne $lastUrl) {
          $lastUrl = $url
          Write-Log ("tunnel url: " + $url)
          $live = Get-Live
          if (-not $live -or $live.url -ne $url -or $live.status -ne "online") {
            Publish-Url $url "online"
          }
        }
      } elseif ($text -notmatch "^\s*$" -and $text -notmatch "[\u2580-\u259F]") {
        Write-Log ("ssh: " + $text)
      }
    }
  } catch {
    Write-Log ("ssh error: " + $_.Exception.Message)
  }
  if ($lastUrl) {
    $live = Get-Live
    if ($live -and $live.status -ne "offline") { Publish-Url $lastUrl "offline" }
  }
  Write-Log "disconnected, retry in 5s"
  Start-Sleep -Seconds 5
}
