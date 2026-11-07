param(
  [string]$Server = "192.168.0.1",
  [string]$User = "linadmin",
  [string]$Key = "$env:USERPROFILE\.ssh\id_ed25519",
  [string]$SudoPassword = "",
  [int]$Port = 9000,
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
if (-not $SudoPassword) { $SudoPassword = $env:ALTROUTER_SUDO_PW }
if (-not $SudoPassword) { throw "Set -SudoPassword or env ALTROUTER_SUDO_PW" }

$Root = Split-Path -Parent $PSScriptRoot
$Remote = "/tmp/altrouter-deploy"
$sshArgs = @("-i", $Key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new")

if (-not $SkipBuild) {
  & npm.cmd run build --prefix (Join-Path $Root "frontend")
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
}
if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
  throw "frontend\dist отсутствует — выполните npm run build --prefix frontend"
}

$tarball = Join-Path $env:TEMP "altrouter-deploy.tar.gz"
tar -czf $tarball -C $Root backend/app backend/requirements.txt backend/pyproject.toml frontend/dist deploy
if ($LASTEXITCODE -ne 0) { throw "tar failed" }

ssh @sshArgs "$User@$Server" "rm -rf $Remote && mkdir -p $Remote"
scp @sshArgs $tarball "${User}@${Server}:${Remote}/deploy.tar.gz"
ssh @sshArgs "$User@$Server" "tar -xzf $Remote/deploy.tar.gz -C $Remote"

$SudoPassword | ssh @sshArgs "$User@$Server" "ALTROUTER_PORT=$Port sudo -S -p '' bash $Remote/deploy/install.sh $Remote"
if ($LASTEXITCODE -ne 0) { throw "install failed" }

curl.exe -sk --max-time 10 "https://${Server}:$Port/api/health"
