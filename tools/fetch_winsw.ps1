param(
    [string]$Version = "3.0.2",
    [string]$Sha256 = "f23f4d2f130c8bb944e4f3f8fe32f4b5a1911790402fab912e3da6afdd1fb26a",
    [string]$Destination = "windows_service/StudentMentorService.exe"
)

$ErrorActionPreference = "Stop"

function Invoke-WinSWDownload {
    param (
        [string]$Version,
        [string]$Sha256,
        [string]$Destination
    )

    $uri = "https://github.com/winsw/winsw/releases/download/v$Version/WinSW-x64.exe"
    $outFile = [System.IO.Path]::GetFullPath($Destination)
    $destDir = [System.IO.Path]::GetDirectoryName($outFile)
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir | Out-Null
    }

    Write-Host "Downloading WinSW $Version from $uri ..."
    Invoke-WebRequest -Uri $uri -OutFile $outFile -UseBasicParsing

    $hash = (Get-FileHash -Path $outFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $Sha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $outFile -Force
        throw "Checksum mismatch: expected $Sha256 but found $hash"
    }

    Write-Host "WinSW downloaded to $outFile (sha256=$hash)"
}

Invoke-WinSWDownload -Version $Version -Sha256 $Sha256 -Destination $Destination
