"""Capture README screenshots of the running app (uses the locally installed Google Chrome).

    python scripts/screenshots.py --base http://127.0.0.1:8000 --out docs/screenshots
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright


async def shoot(base: str, out: Path, theme: str, question: str | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme=theme)
        page = await ctx.new_page()
        page.set_default_timeout(180_000)

        await page.goto(f"{base}/#/overview")
        await page.wait_for_selector("text=Headline results")
        await page.wait_for_timeout(800)
        await page.screenshot(path=out / f"overview-{theme}.png")

        await page.goto(f"{base}/#/explore?ind=CSC_RES_ELC_ACCS")
        await page.wait_for_selector("text=Where results are reported")
        await page.wait_for_timeout(2500)
        await page.screenshot(path=out / f"explore-{theme}.png", full_page=False)

        if question:
            await page.goto(f"{base}/#/explore?ind=CSC_RES_BRO_INTE&ask={quote(question)}")
            # Wait for the answer to finish: the footer with timing appears when streaming ends.
            await page.wait_for_selector("text=/tool calls$/", timeout=180_000)
            await page.wait_for_timeout(1000)
            steps = page.get_by_role("button", name="How this was answered")
            if await steps.count():
                await steps.first.click()
                await page.wait_for_timeout(300)
            await page.screenshot(path=out / f"chat-{theme}.png")
        await browser.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--question", default="Which regions made the most progress in digital access in recent years?")
    ap.add_argument("--no-chat", action="store_true")
    a = ap.parse_args()
    asyncio.run(shoot(a.base, Path(a.out), a.theme, None if a.no_chat else a.question))


if __name__ == "__main__":
    main()
