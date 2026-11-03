"""Keep Jenny's visible Discord game activity in sync with process uptime.

Discord bot accounts do not have the same full Rich Presence capabilities as
desktop game integrations. This module uses the supported Playing activity and
updates its title once a minute to show an elapsed session time. The clock is
intentionally process-local, so it resets after a restart.
"""

import asyncio
import time
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord.ext.commands import Bot


PRESENCE_UPDATE_INTERVAL_SECONDS = 15
_PROCESS_STARTED_MONOTONIC = time.monotonic()


def _format_elapsed(seconds: float) -> str:
    """Format process uptime as a compact, stable activity-title suffix."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


async def run_minecraft_presence(bot: "Bot") -> None:
    """Set and periodically refresh Jenny's Minecraft singleplayer activity."""
    # Wait for the gateway to settle after READY. discord.py cautions against
    # changing presence immediately during on_ready because it can reconnect.
    await asyncio.sleep(5)
    while not bot.is_closed():
        elapsed = time.monotonic() - _PROCESS_STARTED_MONOTONIC
        elapsed_text = _format_elapsed(elapsed)
        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name="Minecraft",
            state=f"Singleplayer · Version 26.3 · {elapsed_text}",
        )
        try:
            await bot.change_presence(activity=activity)
            print(f"[PRESENCE] Playing Minecraft | Singleplayer · Version 26.3 · {elapsed_text}")
        except (discord.HTTPException, discord.DiscordException) as error:
            # Presence is cosmetic; a transient gateway/API failure should not
            # take down message handling or the rest of the bot.
            print(f"[PRESENCE] Could not update game activity: {error}")

        await asyncio.sleep(PRESENCE_UPDATE_INTERVAL_SECONDS)
