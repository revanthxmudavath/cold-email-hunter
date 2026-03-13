@echo off
echo Creating virtual environment...
python -m venv .venv
echo Installing dependencies...
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
echo.
echo Setup complete!
echo Next: fill in your API keys in data\config.json
pause
