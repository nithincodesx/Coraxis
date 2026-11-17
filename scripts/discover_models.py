"""Discover live models from an OpenAI-compatible provider.

Run locally with your key in the environment. The key never leaves this machine.

    $env:CORAXIS_DISCOVER_BASE_URL="https://api.inceptionlabs.ai/v1"
    $env:CORAXIS_DISCOVER_API_KEY="sk_..."
    python scripts/discover_models.py
"""

from __future__ import annotations

import asyncio
import os

from coraxis.services.llm.discovery import list_provider_models


async def main() -> None:
    base_url = os.environ.get("CORAXIS_DISCOVER_BASE_URL", "").strip()
    api_key = os.environ.get("CORAXIS_DISCOVER_API_KEY", "").strip()

    if not base_url:
        print("Set CORAXIS_DISCOVER_BASE_URL (e.g. https://api.inceptionlabs.ai/v1)")
        return
    if not api_key:
        print("Set CORAXIS_DISCOVER_API_KEY")
        return

    models, error = await list_provider_models("custom", api_key=api_key, base_url=base_url)

    if error:
        print(f"Discovery failed: {error}")
        return

    print(f"Discovered {len(models)} model(s):")
    for model in models:
        print(f"  - {model}")


if __name__ == "__main__":
    asyncio.run(main())
