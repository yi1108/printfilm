# Start Postgres + Redis only
$Root = Resolve-Path (Join-Path $PSScriptRoot "../..")
$EnvFile = Join-Path $Root "deploy/.env.prod"
if (-not (Test-Path $EnvFile)) {
    Write-Error "Copy deploy/.env.prod.example → deploy/.env.prod first"
    exit 1
}
docker compose -f (Join-Path $Root "deploy/docker-compose.yml") --env-file $EnvFile up -d
docker compose -f (Join-Path $Root "deploy/docker-compose.yml") --env-file $EnvFile ps
