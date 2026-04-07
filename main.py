import subprocess
import traceback
from datetime import datetime
from pathlib import Path

from upload_to_sharepoint import process_uploads

scrapers = ["attempt2.py", "scraper.py", "impact_funding_scraper.py", "dev_aid_wo_playwright.py", "eu_comm_wo_playwright.py", "fundsforngos_webscraper.py", "sam_fast_wo_playwright.py"]  # change to test later

_ROOT = Path(__file__).resolve().parent
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_error_log_path = _LOG_DIR / f"scraper_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def _log_error(section: str) -> None:
    with open(_error_log_path, "a", encoding="utf-8") as log:
        log.write(section)
        if not section.endswith("\n"):
            log.write("\n")
        log.write("\n")


with open(_error_log_path, "w", encoding="utf-8") as log:
    log.write(f"Run started: {datetime.now().isoformat()}\n")
    log.write("=" * 60 + "\n\n")

try:
    for scraper in scrapers:
        try:
            result = subprocess.run(
                ["python", scraper],
                cwd=_ROOT,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"{scraper} success")
            else:
                _log_error(
                    f"[{scraper}] FAILED exit code {result.returncode}\n"
                    f"--- STDOUT ---\n{result.stdout}\n"
                    f"--- STDERR ---\n{result.stderr}\n"
                )
                print(f"{scraper} failed — details written to {_error_log_path}")
        except Exception as e:
            _log_error(f"[{scraper}] CRASHED: {e!r}\n{traceback.format_exc()}")
            print(f"{scraper} crashed — details written to {_error_log_path}")
    # call upload to sharepoint here
    process_uploads()
    print("Uploaded to Sharepoint Successfully")
except Exception as e:
    _log_error(f"SharePoint upload error: {e!r}\n{traceback.format_exc()}")
    print(f"Error uploading to sharepoint — details written to {_error_log_path}")
