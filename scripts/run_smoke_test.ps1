$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot\..
python -m unittest ./tests/test_contracts_smoke.py
