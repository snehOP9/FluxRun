param([ValidateSet('api','worker','migrate','seed','test')][string]$Service='api')
$ErrorActionPreference='Stop'
. "$PSScriptRoot/local_env.ps1"
Push-Location "$taskRoot/apps/api"
try {
    switch ($Service) {
        'api' { & .venv/Scripts/python.exe -m uvicorn fluxrun_api.main:app --host 127.0.0.1 --port 8000 --reload }
        'worker' { & .venv/Scripts/python.exe -m celery -A fluxrun_worker.tasks:celery worker --pool=solo --loglevel=INFO }
        'migrate' { & .venv/Scripts/alembic.exe upgrade head; if ($LASTEXITCODE -eq 0) { & .venv/Scripts/python.exe -m fluxrun_api.bootstrap } }
        'seed' { & .venv/Scripts/python.exe ../../scripts/seed_demo.py }
        'test' { & .venv/Scripts/python.exe -m pytest -q }
    }
} finally { Pop-Location }
