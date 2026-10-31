param(
    [Parameter(Mandatory = $true)][string]$JobFile
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$utf8 = New-Object System.Text.UTF8Encoding($false)
$job = [System.IO.File]::ReadAllText($JobFile, $utf8) | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice([string]$job.voice)
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    22050,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

foreach ($item in $job.items) {
    $out = [string]$item.out
    $dir = Split-Path -Parent $out
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $synth.Rate = [int]$item.rate
    $synth.SetOutputToWaveFile($out, $format)
    $synth.Speak([string]$item.text)
    $synth.SetOutputToNull()
}
$synth.Dispose()
Write-Output ("voice_ok=" + [string]$job.voice + "; files=" + $job.items.Count)
