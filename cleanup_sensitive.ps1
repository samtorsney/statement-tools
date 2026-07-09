<#
    cleanup_sensitive.ps1
    Removes INTERMEDIATE sensitive artifacts created during redaction:
      - *_unlocked.pdf   (decrypted copies that still hold full unredacted data)
      - secrets.txt / *terms*.txt   (redaction term lists)

    It deliberately does NOT touch:
      - original statements (boi_statement_*.pdf without _unlocked)
      - your finished *_redacted.pdf outputs
      - any .csv / .xlsx / source code

    Usage (from the project folder):
        .\cleanup_sensitive.ps1            # lists what it will remove, then asks
        .\cleanup_sensitive.ps1 -Force     # remove without the confirmation prompt
#>
param([switch]$Force)

$patterns = @('*_unlocked.pdf', 'secrets.txt', '*terms*.txt')

$targets = Get-ChildItem -File -Path $patterns -ErrorAction SilentlyContinue |
           Sort-Object FullName -Unique

if (-not $targets) {
    Write-Host "Nothing to clean up. No intermediate sensitive files found." -ForegroundColor Green
    return
}

Write-Host "The following intermediate sensitive files will be deleted:" -ForegroundColor Yellow
$targets | ForEach-Object { Write-Host "  $($_.Name)  ($([math]::Round($_.Length/1KB)) KB)" }

if (-not $Force) {
    $answer = Read-Host "`nDelete these permanently? (y/N)"
    if ($answer -ne 'y') { Write-Host "Aborted. Nothing deleted."; return }
}

foreach ($t in $targets) {
    Remove-Item -LiteralPath $t.FullName -Force
    Write-Host "deleted $($t.Name)" -ForegroundColor DarkGray
}
Write-Host "Done." -ForegroundColor Green
Write-Host "Note: standard deletion only unlinks the file; for defense against" -ForegroundColor DarkGray
Write-Host "forensic recovery, run 'cipher /w:.' in this folder afterwards." -ForegroundColor DarkGray
