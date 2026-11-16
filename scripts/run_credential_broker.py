"""Start the local Keychain-backed credential broker in the foreground."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from environment.credential_broker import serve
from environment.experiment_config import cli

if __name__ == "__main__":
    cli("credential_broker", serve)
