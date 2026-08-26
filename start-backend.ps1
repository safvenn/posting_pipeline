# start-backend.ps1 — activate venv and launch FastAPI (Windows)
Set-Location $PSScriptRoot
$env:PYTHONPATH = $PSScriptRoot
& "$PSScriptRoot\venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
