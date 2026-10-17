"""Deploy the app to a Hugging Face Space (Docker SDK).

    hf auth login                                   # once, with a write token
    python scripts/deploy_hf.py --space <user>/wbg-scorecard-explorer

Creates the Space if needed, stores the LLM API key as a Space *secret* (read from the
environment or .env; never printed), sets non-secret variables, and uploads the project.
Hugging Face then builds the Dockerfile and serves the app at https://<user>-<name>.hf.space
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
IGNORE = [
    ".venv/*", ".env", "**/__pycache__/*", ".pytest_cache/*", "frontend/node_modules/*",
    "data/scorecard.duckdb", "data/clean/*", "*.building", "**/.DS_Store", "docs/screenshots/*",
]
# Non-secret runtime settings shown in the Space settings page.
VARIABLES = {"LLM_MODEL_NAME": "claude-sonnet-5-5", "LLM_EFFORT": "medium", "RATE_LIMIT_PER_HOUR": "30", "DAILY_BUDGET_USD": "10"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--space", required=True, help="<user>/<space-name>")
    ap.add_argument("--private", action="store_true", help="create the Space as private")
    ap.add_argument("--skip-secret", action="store_true", help="don't (re)set the API key secret")
    args = ap.parse_args()

    api = HfApi()
    print(f"Logged in as {api.whoami()['name']}")
    api.create_repo(args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)

    if not args.skip_secret:
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        key = env.get("LLM_API_KEY") or env.get("ANTHROPIC_API_KEY")
        if not key:
            print("No LLM_API_KEY / ANTHROPIC_API_KEY found in the environment or .env", file=sys.stderr)
            return 1
        api.add_space_secret(args.space, "ANTHROPIC_API_KEY", key, description="Anthropic API key for the chat agent")
        print("Set secret ANTHROPIC_API_KEY (value not shown)")
    for k, v in VARIABLES.items():
        api.add_space_variable(args.space, k, v)

    commit = api.upload_folder(repo_id=args.space, repo_type="space", folder_path=ROOT, ignore_patterns=IGNORE,
                               commit_message="Deploy WBG Scorecard Explorer")
    print(f"Uploaded: {commit.commit_url}")
    host = args.space.replace("/", "-").replace("_", "-").lower()
    print(f"Space page: https://huggingface.co/spaces/{args.space}\nApp URL:    https://{host}.hf.space\nMCP URL:    https://{host}.hf.space/mcp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
