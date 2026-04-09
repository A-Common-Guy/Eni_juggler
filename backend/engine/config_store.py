"""
Persistent config store for ENI Juggler settings (Groq API key, model choice).
Reads and writes to .env at the project root. os.environ takes precedence.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"

AVAILABLE_MODELS = [
    {"id": "llama-3.3-70b-versatile",                    "label": "Llama 3.3 70B (best quality, 12K TPM)"},
    {"id": "meta-llama/llama-4-scout-17b-16e-instruct",  "label": "Llama 4 Scout 17B (highest TPM, 30K)"},
    {"id": "llama-3.1-8b-instant",                       "label": "Llama 3.1 8B (fastest, light usage)"},
]

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _read_env_file() -> dict[str, str]:
    """Parse .env into a dict, preserving only KEY=VALUE lines."""
    if not ENV_FILE.exists():
        return {}
    result = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if m:
            result[m.group(1)] = m.group(2).strip('"').strip("'")
    return result


def _write_env_file(updates: dict[str, str]) -> None:
    """Update or add keys in .env without touching unrelated lines."""
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    written = set()
    new_lines: list[str] = []
    for line in lines:
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=', line)
        if m and m.group(1) in updates:
            key = m.group(1)
            new_lines.append(f'{key}="{updates[key]}"')
            written.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in written:
            new_lines.append(f'{key}="{value}"')

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Reflect changes in the current process environment
    for key, value in updates.items():
        os.environ[key] = value


def load_dotenv() -> None:
    """Load .env into os.environ (only sets vars not already present)."""
    for key, value in _read_env_file().items():
        if key not in os.environ:
            os.environ[key] = value


def save_config(data: dict) -> None:
    """Persist settings to .env. Keys: groq_api_key → GROQ_API_KEY, model → ENI_MODEL."""
    mapping = {
        "groq_api_key": "GROQ_API_KEY",
        "model": "ENI_MODEL",
    }
    updates = {mapping[k]: v for k, v in data.items() if k in mapping}
    if updates:
        _write_env_file(updates)


def get_groq_api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY") or None


def get_model() -> str:
    return os.environ.get("ENI_MODEL", DEFAULT_MODEL)
