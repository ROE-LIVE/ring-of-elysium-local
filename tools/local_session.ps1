function Enter-RoeSessionLock {
    param([Parameter(Mandatory=$true)][string]$Repository)
    $directory = Join-Path $Repository '.tools'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    try {
        return [IO.File]::Open((Join-Path $directory 'session.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    } catch {
        throw 'Закройте игру и launcher перед сбросом / Close the game and launcher; this repository is busy.'
    }
}

function Assert-RoePlainPath {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$Path)
    $base = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $target = [IO.Path]::GetFullPath($Path)
    if (-not $target.StartsWith($base + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside owned root: $target"
    }
    $cursor = $target
    while ($cursor.Length -ge $base.Length) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Link/junction is not removable: $cursor" }
        }
        if ($cursor -eq $base) { break }
        $cursor = Split-Path -Parent $cursor
    }
}

function Remove-RoeGeneratedPath {
    param([Parameter(Mandatory=$true)][string]$Repository, [Parameter(Mandatory=$true)][string]$Relative)
    $path = Join-Path $Repository $Relative
    Assert-RoePlainPath -Root $Repository -Path $path
    if (-not (Test-Path -LiteralPath $path)) { return }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $path -Recurse -Force) {
            if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Link/junction inside generated directory: $path" }
        }
    }
    Remove-Item -LiteralPath $path -Recurse -Force
    Write-Host ('Removed generated files / Удалено: ' + $Relative)
}

function Remove-RoeClientDebugFiles {
    param([Parameter(Mandatory=$true)][string]$Repository, [Parameter(Mandatory=$true)][string]$Client)
    $runs = Join-Path $Repository 'runs'
    if (-not (Test-Path -LiteralPath $runs -PathType Container)) { return }
    $clientRoot = [IO.Path]::GetFullPath($Client)
    foreach ($run in Get-ChildItem -LiteralPath $runs -Directory) {
        if ($run.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        $receiptPath = Join-Path $run.FullName 'client-debug-files.json'
        if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { continue }
        Assert-RoePlainPath -Root $Repository -Path $receiptPath
        if ((Get-Item -LiteralPath $receiptPath).Length -gt 16384) { throw 'Invalid debug receipt size' }
        $receipt = [IO.File]::ReadAllText($receiptPath) | ConvertFrom-Json
        if ($receipt.version -ne 1 -or $receipt.client -ne $clientRoot) { continue }
        if ($receipt.script -notmatch '^ROE_Probe_state_([0-9a-f]{12})\.lua$') { throw 'Invalid script name in receipt' }
        $token = $Matches[1]
        if ($receipt.output -ne "ROE_Probe_state_$token.tsv" -or $receipt.script_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid debug receipt' }
        $ownedScript = $receipt.script_owned -eq $true
        $scriptPath = Join-Path $clientRoot $receipt.script
        $outputPath = Join-Path $clientRoot $receipt.output
        $marker = Join-Path $clientRoot 'FileDriven\_GM_CONTROL_'
        foreach ($path in @($scriptPath,$outputPath,$marker)) { Assert-RoePlainPath -Root $clientRoot -Path $path }
        if ($ownedScript -and (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
            if ((Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $receipt.script_sha256) {
                Remove-Item -LiteralPath $scriptPath
                $receipt.script_owned = $false
            } else { Write-Warning ('Preserving modified file / Сохранён изменённый файл: ' + $scriptPath) }
        }
        if ($ownedScript -and (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            $output = Get-Item -LiteralPath $outputPath
            if ($output.Length -le 8MB) {
                $text = [IO.File]::ReadAllText($outputPath)
                if ($text -match '\A(?:[A-Za-z_][A-Za-z0-9_]*\t(?:unavailable|-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\r?\n)*\z') {
                    $report = Join-Path $run.FullName 'client-state-recovered.tsv'
                    # При повторном сбросе существующий отчёт не перезаписывается.
                    $index = 1
                    while (Test-Path -LiteralPath $report) { $report = Join-Path $run.FullName ('client-state-recovered-' + $index + '.tsv'); $index++ }
                    [IO.File]::WriteAllText($report,$text,[Text.UTF8Encoding]::new($false))
                    Remove-Item -LiteralPath $outputPath
                } else { Write-Warning ('Preserving unrecognized output / Сохранён неизвестный файл: ' + $outputPath) }
            }
        }
        if ($receipt.marker_owned -eq $true -and (Test-Path -LiteralPath $marker -PathType Leaf) -and (Get-Item -LiteralPath $marker).Length -eq 0 -and $receipt.marker_write_ticks -eq (Get-Item -LiteralPath $marker).LastWriteTimeUtc.Ticks) {
            Remove-Item -LiteralPath $marker
            $receipt.marker_owned = $false
        }
        $markerDirectory = Split-Path -Parent $marker
        if ($receipt.marker_directory_owned -eq $true -and (Test-Path -LiteralPath $markerDirectory -PathType Container)) {
            if (@(Get-ChildItem -LiteralPath $markerDirectory -Force).Count -eq 0) { Remove-Item -LiteralPath $markerDirectory; $receipt.marker_directory_owned = $false }
        }
        $pending = Join-Path $run.FullName 'client-debug-files.tmp'
        Assert-RoePlainPath -Root $Repository -Path $pending
        [IO.File]::WriteAllText($pending,($receipt | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $pending -Destination $receiptPath -Force
    }
}
