import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from src.logger import setup_logger

logger = setup_logger("TestLogger")
logger.info("This is a test log message.")
logger.error("This is a test error message.")

log_file = Path("logs/app.log")
if log_file.exists():
    print(f"Log file created at {log_file}")
    print("Content:")
    print(log_file.read_text(encoding="utf-8"))
else:
    print("Log file not found!")
