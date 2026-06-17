<#
.SYNOPSIS
    Organizes client files from Downloads into the correct job folder.

.EXAMPLE
    .\sort_files.ps1 "Jannis Fredrick"                    # Last name first (default)
    .\sort_files.ps1 "Fredrick Jannis" -FirstNameFirst    # First name first
    .\sort_files.ps1 "Jannis Fredrick" -LaFire
    .\sort_files.ps1 "Jannis Fredrick" -Year 2025
    .\sort_files.ps1 "Jannis Fredrick" -JobType "PB"
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$ClientName,
    [switch]$LaFire,
    [switch]$FirstNameFirst,
    [int]$Year = (Get-Date).Year,
    [string]$JobType = "PO PB"
)

$ConfigPath = Join-Path $PSScriptRoot "config.json"
$Config     = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$BasePath   = $Config.audit_base
$Downloads  = "$env:USERPROFILE\Downloads"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Normalize([string]$s) {
    ($s -replace '[^a-zA-Z ]', ' ' -replace '\s+', ' ').Trim().ToLower()
}

function FuzzyMatch([string]$query, [string[]]$candidates) {
    $qWords = (Normalize $query) -split ' '
    $scored = foreach ($c in $candidates) {
        $cWords = (Normalize $c) -split ' '
        $shared = ($qWords | Where-Object { $cWords -contains $_ }).Count
        [PSCustomObject]@{ Name = $c; Score = $shared }
    }
    $scored | Where-Object { $_.Score -gt 0 } | Sort-Object Score -Descending
}

function Get-FileType([System.IO.FileInfo]$File) {
    $name = $File.Name.ToLower()
    $ext  = $File.Extension.ToLower()
    if ($name -match 'drybook|dry book|dry_book') { return 'drybook' }
    if ($ext -eq '.zip')                           { return 'zip' }
    if ($ext -in @('.xlsx','.xlsm','.xls'))        { return 'excel' }
    if ($ext -eq '.pdf') {
        if ($name -match 'photo|inventory')        { return 'photo_inventory' }
        return 'xactimate'
    }
    return 'unknown'
}

function Pick-File([System.IO.FileInfo[]]$fileList, [string]$label) {
    Write-Host ""
    Write-Host "  Multiple $label files found -- which one?" -ForegroundColor Yellow
    for ($i = 0; $i -lt $fileList.Count; $i++) {
        Write-Host "    $($i+1). $($fileList[$i].Name)"
    }
    $choice = Read-Host "  Select number"
    if ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $fileList.Count) {
        return $fileList[[int]$choice - 1]
    }
    Write-Host "  Invalid choice -- skipping $label" -ForegroundColor Yellow
    return $null
}

# ---------------------------------------------------------------------------
# Find year folder
# ---------------------------------------------------------------------------

if (-not (Test-Path $BasePath)) {
    Write-Host ""
    Write-Host "ERROR: Cannot access $BasePath -- is the X: drive connected?" -ForegroundColor Red
    exit 1
}

$yearFolders = Get-ChildItem $BasePath -Directory

if ($LaFire) {
    $yearFolder = $yearFolders | Where-Object {
        $_.Name -match $Year -and $_.Name -match "LA" -and $_.Name -match "FIRE"
    } | Select-Object -First 1
    if (-not $yearFolder) {
        $yearFolder = $yearFolders | Where-Object {
            $_.Name -match "LA" -and $_.Name -match "FIRE"
        } | Select-Object -First 1
    }
} else {
    $yearFolder = $yearFolders | Where-Object {
        $_.Name -match $Year -and -not ($_.Name -match "LA" -and $_.Name -match "FIRE")
    } | Select-Object -First 1
}

if (-not $yearFolder) {
    $tag = if ($LaFire) { "LA Fire " } else { "" }
    Write-Host ""
    Write-Host "ERROR: No ${tag}${Year} folder found in $BasePath" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Find client folder
# ---------------------------------------------------------------------------

$clientFolders = Get-ChildItem $yearFolder.FullName -Directory
$clientNames   = $clientFolders | ForEach-Object { $_.Name }

$normQuery = Normalize $ClientName
$match = $clientNames | Where-Object { (Normalize $_) -eq $normQuery } | Select-Object -First 1

if (-not $match) {
    $parts    = $ClientName.Trim() -split '\s+'
    $reversed = ($parts[-1..0]) -join ' '
    $normRev  = Normalize $reversed
    $match = $clientNames | Where-Object { (Normalize $_) -eq $normRev } | Select-Object -First 1
}

if (-not $match) {
    $hits = FuzzyMatch $ClientName $clientNames
    if ($hits) {
        Write-Host ""
        Write-Host "No exact match for '$ClientName'. Close matches:" -ForegroundColor Yellow
        $top = $hits | Select-Object -First 5
        for ($i = 0; $i -lt $top.Count; $i++) {
            Write-Host "  $($i+1). $($top[$i].Name)"
        }
        $choice = Read-Host "Select number (or 0 to cancel)"
        if ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $top.Count) {
            $match = $top[[int]$choice - 1].Name
        }
    }
}

if (-not $match) {
    Write-Host ""
    Write-Host "ERROR: Client folder not found for '$ClientName'" -ForegroundColor Red
    Write-Host "Please create the folder in $($yearFolder.FullName) first."
    exit 1
}

$clientFolder = Join-Path $yearFolder.FullName $match

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

$sep = "=" * 52
Write-Host ""
Write-Host $sep
Write-Host "  Client : $ClientName"
Write-Host "  Folder : $match"
if ($LaFire) {
    Write-Host "  Year   : $Year  (LA Fire)"
} else {
    Write-Host "  Year   : $Year"
}
Write-Host "  Job    : $JobType"
Write-Host $sep

# ---------------------------------------------------------------------------
# Ensure subfolders
# ---------------------------------------------------------------------------

$sfContentsDocs = Join-Path $clientFolder "CONTENTS\DOCS"
$sfContentsPics = Join-Path $clientFolder "CONTENTS\PICS"
$sfEmsDocs      = Join-Path $clientFolder "EMS\DOCS"

Write-Host ""
Write-Host "Checking subfolders..."
foreach ($path in @($sfContentsDocs, $sfContentsPics, $sfEmsDocs)) {
    if (-not (Test-Path $path)) {
        $rel = $path.Replace($clientFolder + "\", "")
        Write-Host "  Creating: $rel" -ForegroundColor Cyan
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

$nameParts = $ClientName.Trim() -split '\s+'
if ($FirstNameFirst) {
    $LastName = $nameParts[-1].ToUpper()
} else {
    $LastName = $nameParts[0].ToUpper()
}
Write-Host "Last name    : $LastName"

# ---------------------------------------------------------------------------
# Scan Downloads
# ---------------------------------------------------------------------------

$validExts = @('.pdf','.xlsx','.xlsm','.xls','.zip')
$files = Get-ChildItem $Downloads -File | Where-Object { $_.Extension.ToLower() -in $validExts }

if (-not $files) {
    Write-Host ""
    Write-Host "No matching files found in Downloads (.pdf / .xlsx / .xlsm / .zip)" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Files in Downloads ($($files.Count)):"
foreach ($f in $files) {
    $t = Get-FileType $f
    Write-Host "  - $($f.Name)  [$t]"
}

$confirm = Read-Host "`nProcess all of these? (y/n)"
if (-not $confirm -or $confirm.ToLower() -ne 'y') {
    Write-Host "Cancelled."
    exit 0
}

# ---------------------------------------------------------------------------
# Pre-select when multiple of same type exist
# ---------------------------------------------------------------------------

$xactFiles  = @($files | Where-Object { (Get-FileType $_) -eq 'xactimate' })
$excelFiles = @($files | Where-Object { (Get-FileType $_) -eq 'excel' })

$chosenXact  = $null
$chosenExcel = $null

if ($xactFiles.Count -eq 1)  { $chosenXact  = $xactFiles[0] }
elseif ($xactFiles.Count -gt 1) { $chosenXact  = Pick-File $xactFiles  "Xactimate PDF" }

if ($excelFiles.Count -eq 1) { $chosenExcel = $excelFiles[0] }
elseif ($excelFiles.Count -gt 1) { $chosenExcel = Pick-File $excelFiles "Excel" }

# ---------------------------------------------------------------------------
# Process files
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Processing..."
$doneCount = 0

foreach ($f in $files) {
    $ftype = Get-FileType $f
    $label = $ftype.Replace('_',' ').ToUpper()
    Write-Host ""
    Write-Host "  [$label]  $($f.Name)"

    if ($ftype -eq 'photo_inventory') {
        $dest = Join-Path $sfContentsDocs "Photo Inventory Report.pdf"
        Copy-Item $f.FullName -Destination $dest -Force
        Remove-Item $f.FullName -Force
        Write-Host "    -> CONTENTS\DOCS\Photo Inventory Report.pdf" -ForegroundColor Green
        $doneCount++
    }
    elseif ($ftype -eq 'xactimate') {
        if ($null -eq $chosenXact -or $f.FullName -ne $chosenXact.FullName) {
            Write-Host "    (skipped -- not selected)" -ForegroundColor DarkGray
        } else {
            $destName = "${LastName} ${JobType} Estimate.pdf"
            $dest = Join-Path $sfContentsDocs $destName
            Copy-Item $f.FullName -Destination $dest -Force
            Remove-Item $f.FullName -Force
            Write-Host "    -> CONTENTS\DOCS\$destName" -ForegroundColor Green
            $doneCount++
        }
    }
    elseif ($ftype -eq 'excel') {
        if ($null -eq $chosenExcel -or $f.FullName -ne $chosenExcel.FullName) {
            Write-Host "    (skipped -- not selected)" -ForegroundColor DarkGray
        } else {
            foreach ($ext in @('.xlsx', '.xlsm')) {
                $destName = "${LastName}FinalCalculation${ext}"
                $dest = Join-Path $sfContentsDocs $destName
                Copy-Item $f.FullName -Destination $dest -Force
                Write-Host "    -> CONTENTS\DOCS\$destName" -ForegroundColor Green
            }
            Remove-Item $f.FullName -Force
            $doneCount++
        }
    }
    elseif ($ftype -eq 'zip') {
        Write-Host "    Extracting into CONTENTS\PICS..."
        Expand-Archive -Path $f.FullName -DestinationPath $sfContentsPics -Force
        Remove-Item $f.FullName -Force
        Write-Host "    -> Extracted to CONTENTS\PICS" -ForegroundColor Green
        $doneCount++
    }
    elseif ($ftype -eq 'drybook') {
        $dest = Join-Path $sfEmsDocs $f.Name
        Move-Item $f.FullName -Destination $dest -Force
        Write-Host "    -> EMS\DOCS\$($f.Name)" -ForegroundColor Green
        $doneCount++
    }
    else {
        Write-Host "    [!] Unrecognized file type -- skipping" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host $sep
Write-Host "  Done -- $doneCount file(s) moved to: $match"
Write-Host $sep
Write-Host ""
