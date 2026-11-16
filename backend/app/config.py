import os
from pathlib import Path

APP_NAME = "核证匣"
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_FILENAME = "app.db"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
API_PORT = 10500
