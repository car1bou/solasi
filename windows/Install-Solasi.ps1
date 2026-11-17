param([switch]$Replace)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$target = Join-Path $env:LOCALAPPDATA 'Solasi\app'
$manifest = Get-Content (Join-Path $source 'bundle-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.platform -ne 'win32-x64') { throw 'Windows x64 bundle required.' }
foreach ($entry in $manifest.files.PSObject.Properties) {
    $name = $entry.Name
    if ($name -match '(^/|\\|:|(^|/)\.\.(/|$))') { throw 'Invalid bundle path.' }
    $file = Join-Path $source $name
    $info = Get-Item -LiteralPath $file
    if (($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $info.Length -ne $entry.Value.bytes -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value.sha256) { throw ('Bundle verification failed: ' + $name) }
}
if (Get-Process Solasi,solasi-worker -ErrorAction SilentlyContinue) { throw 'Save work and quit Solasi before installing.' }
if ((Test-Path $target) -and -not $Replace) { throw 'Existing app preserved. Use -Replace only after saving and quitting it.' }
if ((Test-Path $target) -and -not (Test-Path (Join-Path $target 'bundle-manifest.json'))) { throw 'Target is not a verified Solasi installation.' }
$webviewInstaller = Join-Path $source 'setup\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $webviewInstaller
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(,|$)') { throw 'Invalid Microsoft WebView2 installer signature.' }
$runtimeInstall = Start-Process -FilePath $webviewInstaller -ArgumentList '/silent','/install' -Wait -PassThru
if ($runtimeInstall.ExitCode -ne 0) { throw 'WebView2 Runtime preparation failed; existing app preserved.' }
$parent = Split-Path $target
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$stage = Join-Path $parent ('app-new-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
foreach ($entry in $manifest.files.PSObject.Properties) {
    $destination = Join-Path $stage $entry.Name
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $source $entry.Name) -Destination $destination
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value.sha256) { throw 'Installed copy verification failed; existing app preserved.' }
}
Copy-Item -LiteralPath (Join-Path $source 'bundle-manifest.json') -Destination $stage
$backup = $null
if (Test-Path $target) {
    $backup = Join-Path $parent ('app-backup-' + [guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath $target -Destination $backup
}
try { Move-Item -LiteralPath $stage -Destination $target }
catch {
    if ($backup) { Move-Item -LiteralPath $backup -Destination $target }
    throw
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Solasi.lnk'))
$shortcut.TargetPath = Join-Path $target 'Solasi.exe'
$shortcut.WorkingDirectory = $target
$shortcut.Save()
$protocol = 'HKCU:\Software\Classes\solasi'
$command = '"' + (Join-Path $target 'Solasi.exe') + '" --audio-link "%1"'
$existing = Get-ItemPropertyValue ($protocol + '\shell\open\command') '(default)' -ErrorAction SilentlyContinue
if (-not $existing -or $existing -eq $command) {
    New-Item ($protocol + '\shell\open\command') -Force | Out-Null
    Set-Item $protocol 'URL:Solasi audio'
    New-ItemProperty $protocol -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    Set-Item ($protocol + '\shell\open\command') $command
}
Write-Output ('Installed: ' + $target)
if ($backup) { Write-Output ('Previous app preserved: ' + $backup) }
