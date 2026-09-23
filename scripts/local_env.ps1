# Load generated local secrets without printing them; use loopback infrastructure.
$taskRoot = Split-Path $PSScriptRoot -Parent
foreach ($line in Get-Content -LiteralPath (Join-Path $taskRoot '.env')) {
    if ($line -match '^([A-Z_]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }
}
$env:DATABASE_URL = "postgresql+psycopg://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@127.0.0.1:55432/$($env:POSTGRES_DB)"
$env:REDIS_URL = 'redis://127.0.0.1:56379/0'
$env:S3_ENDPOINT = 'http://127.0.0.1:59000'
$env:S3_ACCESS_KEY = $env:MINIO_ROOT_USER
$env:S3_SECRET_KEY = $env:MINIO_ROOT_PASSWORD
