# Script de Geracao de Pacote de Producao Instantaneo (.zip)
$ErrorActionPreference = "Stop"

$workspaceDir = "c:\Users\luciano\OneDrive\Documentos\nova pasta\index.html\Condominio"
$desktopPaths = @(
    [Environment]::GetFolderPath("Desktop"),
    "C:\Users\luciano\OneDrive\Desktop",
    "C:\Users\luciano\Desktop"
) | Select-Object -Unique | Where-Object { Test-Path $_ }

Write-Host "Iniciando criacao do pacote de producao limpo..." -ForegroundColor Cyan

$tempZipDir = Join-Path $env:TEMP "ConciliaZap_Deploy_$(Get-Random)"
New-Item -ItemType Directory -Path $tempZipDir -Force | Out-Null

# Copia arquivos relevantes excluindo desnecessarios
Get-ChildItem -Path $workspaceDir -Recurse | Where-Object {
    $_.FullName -notmatch "(__pycache__|\.venv|venv|\.git|\.system_generated|scratch|\.pytest_cache|\.vscode)"
} | ForEach-Object {
    $relative = $_.FullName.Substring($workspaceDir.Length).TrimStart("\")
    $destination = Join-Path $tempZipDir $relative
    if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
    } else {
        $parent = Split-Path $destination
        if (!(Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item $_.FullName -Destination $destination -Force
    }
}

foreach ($desk in $desktopPaths) {
    $targetZip = Join-Path $desk "ConciliaZap-Deploy-Nuvem.zip"
    if (Test-Path $targetZip) { Remove-Item $targetZip -Force }
    Compress-Archive -Path "$tempZipDir\*" -DestinationPath $targetZip -CompressionLevel Optimal
    Write-Host " [SUCESSO] Pacote gerado com sucesso em: $targetZip" -ForegroundColor Green
}

Remove-Item $tempZipDir -Recurse -Force
Write-Host "Processo de empacotamento concluido com conformidade total!" -ForegroundColor Cyan
