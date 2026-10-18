"""Shared settings for FullFill.

Change values here instead of hard-coding them in other files.
Secrets (API keys, phone numbers) go in .env, never in this file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# --- Camera -------------------------------------------------------------
# iPhone over a wired Continuity Camera connection. The number can change
# after unplugging the phone or restarting the Mac. If the feed shows the
# laptop camera instead of the mat, change this first.
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# Area of the frame covered by the mat, as (x, y, width, height) in pixels.
# None means use the whole frame. Set this once the mount is fixed, and
# don't move the mount afterwards.
MAT_ROI = None

# --- Stillness trigger --------------------------------------------------
MOTION_THRESHOLD = 12.0    # mean pixel change inside the mat that counts as motion
STILL_SECONDS = 0.5        # how long the mat must stay still before a check fires
MIN_SECONDS_BETWEEN_CHECKS = 1.0  # at most 1 Perceptron call per second

# --- Image sent to Perceptron -------------------------------------------
UPLOAD_MAX_SIDE = 1024     # longest side in pixels after downscaling
JPEG_QUALITY = 85

# --- Perceptron ---------------------------------------------------------
PERCEPTRON_API_KEY = os.getenv("PERCEPTRON_API_KEY", "")
# Copy the exact model name from the playground's Export button.
PERCEPTRON_MODEL = os.getenv("PERCEPTRON_MODEL", "")
REQUEST_TIMEOUT_SECONDS = 30
MAX_OUTPUT_TOKENS = 300    # keep answers short: output length drives latency
USE_REASONING = False      # off by default; turning it on adds latency

# Spending guards, so a misfiring trigger can't burn the credits.
MAX_CALLS_PER_MINUTE = 30
MAX_CALLS_PER_SESSION = 500

# --- Order checking -----------------------------------------------------
ITEM_STATUSES = ("present", "missing", "unsure")
# Ask for points on flagged items in a second, background call.
HIGHLIGHT_FLAGGED_ITEMS = True

# --- Files --------------------------------------------------------------
DATA_DIR = ROOT / "data"
REFERENCE_DIR = DATA_DIR / "references"   # photos taken through the station camera
MENU_FILE = DATA_DIR / "menu.json"
ORDERS_FILE = DATA_DIR / "orders.json"
LOG_DIR = ROOT / "logs"                   # every check, for evaluation
SNAPSHOT_DIR = LOG_DIR / "snapshots"

# --- Backend ------------------------------------------------------------
HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "8000"))

# --- Photon (optional) --------------------------------------------------
PHOTON_ENABLED = os.getenv("PHOTON_ENABLED", "false").lower() == "true"
MANAGER_PHONE = os.getenv("MANAGER_PHONE", "")


def check():
    """Create folders and report missing settings. Call once at startup."""
    for folder in (REFERENCE_DIR, SNAPSHOT_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    problems = []
    if not PERCEPTRON_API_KEY:
        problems.append("PERCEPTRON_API_KEY is missing from .env")
    if not PERCEPTRON_MODEL:
        problems.append("PERCEPTRON_MODEL is missing from .env")
    if PHOTON_ENABLED and not MANAGER_PHONE:
        problems.append("PHOTON_ENABLED is true but MANAGER_PHONE is empty")
    return problems


if __name__ == "__main__":
    issues = check()
    print("Config OK" if not issues else "\n".join(issues))
