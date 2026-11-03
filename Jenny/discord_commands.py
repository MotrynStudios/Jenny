import asyncio
import json
import random
from pathlib import Path
import discord
from discord import app_commands
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional
from database import (
    get_main_channel_id,
    clear_user_conversations,
    get_combined_user_summary,
    get_last_user_message,
    set_main_channel_id,
    get_logs_channel_id,
    set_logs_channel_id,
    get_setting,
    set_setting,
    save_user_history,
    get_user_profile,
    get_user_profile_history,
    get_all_user_profiles,
    get_recent_profile_changes,
    find_user_by_name,
    save_user_profile,
    get_changelog,
    get_token_usage,
    get_service_usage,
    search_chat_messages,
    get_recent_channel_messages,
    get_recent_voice_chat,
    get_server_activity_stats,
)
from utils import sanitize_final_reply

# API configuration
PYTHON_API_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_pack_mods():
    """Load only the locally extracted mod list used by pack-grounded tools."""
    summary_path = PROJECT_ROOT / "data" / "modpack_summary.json"
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        mods = data.get("mods", [])
        return [item for item in mods if isinstance(item, dict) and item.get("display_name")]
    except (OSError, json.JSONDecodeError, TypeError) as error:
        print(f"[PACK] Could not read local mod list at {summary_path}: {error}")
        return []


class ChangelogPageView(discord.ui.View):
    """Three-button history pager; the center button opens a page jump modal."""
    def __init__(self, entries, owner_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.entries = entries
        self.owner_id = owner_id
        self.page = page
        self.message = None
        self.previous.label = "Back"
        self.page_button.label = f"{page + 1}/{len(entries)}"
        self.next.label = "Next"
        self.previous.disabled = page <= 0
        self.next.disabled = page >= len(entries) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Run /changelog to open your own history pager.", ephemeral=True)
            return False
        return True

    def make_embed(self):
        entry = self.entries[self.page]
        embed = discord.Embed(title=f"Jenny changelog · v{entry['version']}",
                              description=entry.get("description") or "Release notes",
                              color=discord.Color.blurple())
        for title, key in (("Jenny can", "features"), ("Changes", "changes")):
            values = entry.get(key, [])
            if isinstance(values, str):
                values = [values]
            lines, batch, batch_size = [], [], 0
            for value in values:
                line = f"• {value}"
                if batch and batch_size + len(line) + 1 > 1000:
                    lines.append("\n".join(batch))
                    batch, batch_size = [], 0
                batch.append(line[:1000])
                batch_size += len(line) + 1
            if batch:
                lines.append("\n".join(batch))
            for index, text in enumerate(lines or ["No entries."]):
                embed.add_field(name=title if index == 0 else f"{title} (continued)", value=text[:1024], inline=False)
        embed.set_footer(text=f"{entry.get('type', 'release').title()} · {entry.get('date', 'date unavailable')}")
        return embed

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangelogJumpModal(self))

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(len(self.entries) - 1, self.page + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    def _refresh(self):
        self.previous.disabled = self.page <= 0
        self.page_button.label = f"{self.page + 1}/{len(self.entries)}"
        self.next.disabled = self.page >= len(self.entries) - 1


class ChangelogJumpModal(discord.ui.Modal, title="Go to changelog page"):
    page_number = discord.ui.TextInput(label="Page number", placeholder="1", max_length=6)

    def __init__(self, view: ChangelogPageView):
        super().__init__()
        self.pager = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            requested = int(str(self.page_number.value).strip())
        except ValueError:
            await interaction.response.send_message("Enter a whole page number.", ephemeral=True)
            return
        if requested < 1 or requested > len(self.pager.entries):
            await interaction.response.send_message(f"Choose a page from 1 to {len(self.pager.entries)}.", ephemeral=True)
            return
        self.pager.page = requested - 1
        self.pager._refresh()
        await interaction.response.defer()
        if self.pager.message is not None:
            await self.pager.message.edit(embed=self.pager.make_embed(), view=self.pager)


class TriviaView(discord.ui.View):
    """A locally grounded mod-description quiz with four selectable answers."""
    def __init__(self, question: str, answer: str, options: list[str], owner_id: int):
        super().__init__(timeout=90)
        self.answer = answer
        self.owner_id = owner_id
        self.message = None
        self.select = discord.ui.Select(placeholder="Pick the mod", options=[
            discord.SelectOption(label=name[:100], value=name) for name in options
        ])
        self.select.callback = self._picked
        self.add_item(self.select)
        self.question = question

    async def _picked(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This quiz belongs to the person who started it.", ephemeral=True)
            return
        chosen = self.select.values[0]
        correct = chosen == self.answer
        embed = discord.Embed(title="Modpack trivia", description=self.question,
                              color=discord.Color.green() if correct else discord.Color.orange())
        embed.add_field(name="Result", value=(f"Yep, it’s **{self.answer}**." if correct else
                                               f"Not quite. The answer is **{self.answer}**."), inline=False)
        embed.set_footer(text="Question generated from this server's local modpack summary")
        self.select.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


def make_pack_trivia(owner_id: int):
    """Build one quiz using exact local descriptions; never ask an LLM to invent facts."""
    mods = [m for m in _read_pack_mods() if len(str(m.get("description", "")).strip()) >= 35]
    if len(mods) < 4:
        return None
    chosen = random.choice(mods)
    answer = str(chosen["display_name"])
    distractors = [str(m["display_name"]) for m in random.sample([m for m in mods if m is not chosen], 3)]
    options = distractors + [answer]
    random.shuffle(options)
    question = f"Which installed mod is described this way?\n\n> {str(chosen['description']).strip()[:700]}"
    return question, TriviaView(question, answer, options, owner_id)


def setup_commands(bot):
    """Register all of Jenny's slash commands (the ones that show up when you type '/')."""
    tree = bot.tree

    @tree.command(name="setmainchannel", description="Set this channel as Jenny's main chat channel")
    @app_commands.default_permissions(administrator=True)
    async def setmainchannel(interaction: discord.Interaction):
        if interaction.channel is None:
            embed = discord.Embed(
                title="❌ Error",
                description="Cannot set main channel in this context.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        if not interaction.guild:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return
        set_main_channel_id(interaction.channel.id, str(interaction.guild.id))
        
        # Handle different channel types - only TextChannel and similar have mention attribute
        channel_mention = getattr(interaction.channel, 'mention', f"#{interaction.channel.id}")
        
        embed = discord.Embed(
            title="✅ Main Channel Set",
            description=f"Jenny will now be active in {channel_mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Channel ID", value=str(interaction.channel.id))
        embed.set_footer(text="Use /getmainchannel to verify")
        
        await interaction.response.send_message(embed=embed)

    @tree.command(name="getmainchannel", description="Show which channel Jenny is currently active in")
    async def getmainchannel(interaction: discord.Interaction):
        main_channel_id = get_main_channel_id(str(interaction.guild.id) if interaction.guild else None)
        if main_channel_id:
            channel = bot.get_channel(int(main_channel_id))
            if channel:
                channel_mention = getattr(channel, 'mention', f"#{channel.id}")
                embed = discord.Embed(
                    title="📍 Main Channel",
                    description=f"Jenny is active in {channel_mention}",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Channel ID", value=str(main_channel_id))
                embed.add_field(name="Channel Name", value=channel.name)
                await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(
                    title="⚠️ Main Channel Not Found",
                    description=f"Jenny is configured for channel ID {main_channel_id}, but it doesn't exist or she can't access it.",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ No Main Channel Set",
                description="No main channel has been configured. Use /setmainchannel to set one.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

    @tree.command(name="setlogschannel", description="Set this channel for message and profile logs")
    @app_commands.default_permissions(administrator=True)
    async def setlogschannel(interaction: discord.Interaction):
        # Check permissions manually
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need Administrator permissions to use this command.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        if interaction.channel is None:
            embed = discord.Embed(
                title="❌ Error",
                description="Cannot set logs channel in this context.",
                color=discord.Color.red()
            )
   tr], owner_id: int):
            super().__init__(timeout=300)
            self.guild_id = guild_id
            self.user_id = user_id
            self.owner_id = owner_id

        async def show_period(self, interaction: discord.Interaction, days: int, label: str):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("Only the person who opened this report can change its range.", ephemeral=True)
                return
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            selected_custom_id = f"usage:{label.lower()}"
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.style = (discord.ButtonStyle.primary if child.custom_id == selected_custom_id
                                   else discord.ButtonStyle.secondary)
            token_rows = get_token_usage(self.guild_id, self.user_id, since=since, limit=1000)
            service_rows = get_service_usage(self.guild_id, self.user_id, since=since)
            total = sum(int(row.get("total_tokens") or 0) for row in token_rows)
            prompt = sum(int(row.get("prompt_tokens") or 0) for row in token_rows)
            completion = sum(int(row.get("completion_tokens") or 0) for row in token_rows)
            requests = sum(int(row.get("requests") or 0) for row in token_rows)
            heading = f"Usage for <@{self.user_id}>" if self.user_id else "Usage by member"
            embed = discord.Embed(title=f"{heading} · {label}", color=discord.Color.blurple())
            embed.description = f"Activity since {since[:10]} UTC. Each range is queried from stored event timestamps."
            embed.add_field(name="Tokens", value=f"{total:,} total\n{prompt:,} input + {completion:,} output\n{requests:,} requests", inline=False)
            if token_rows and not self.user_id:
                lines = [f"<@{row['user_id']}> · {int(row['total_tokens'] or 0):,} tokens · {row['requests']} requests" for row in token_rows[:15]]
                embed.add_field(name="Members", value="\n".join(lines)[:1024] or "No usage", inline=False)
            usage = {str(row["service"]): row for row in service_rows}
            stt_ms = int(usage.get("stt", {}).get("duration_ms") or 0)
            tts_ms = int(usage.get("tts", {}).get("duration_ms") or 0)
            stt_count = int(usage.get("stt", {}).get("requests") or 0)
            tts_count = int(usage.get("tts", {}).get("requests") or 0)
            embed.add_field(name="Speech", value=f"STT: {stt_ms / 60000:.1f} min across {stt_count} uses\nTTS: {tts_ms / 60000:.1f} min across {tts_count} uses", inline=False)
            if not token_rows and not service_rows:
                embed.description = "No recorded usage in this period."
            if interaction.message is not None:
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

        @discord.ui.button(label="Daily", style=discord.ButtonStyle.secondary, custom_id="usage:daily")
        async def daily(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.show_period(interaction, 1, "Daily")

        @discord.ui.button(label="Weekly", style=discord.ButtonStyle.secondary, custom_id="usage:weekly")
        async def weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.show_period(interaction, 7, "Weekly")

        @discord.ui.button(label="Monthly", style=discord.ButtonStyle.secondary, custom_id="usage:monthly")
        async def monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.show_period(interaction, 30, "Monthly")

    @tree.command(name="tokenusage", description="Show token and speech usage for this server")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="Optional member to filter by")
    async def tokenusage(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not interaction.guild:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=discord.Embed(title="Permission denied", description="Only a server administrator can view everyone's usage.", color=discord.Color.red()),
                ephemeral=True,
            )
            return
        view = UsagePeriodView(str(interaction.guild.id), str(user.id) if user else None, interaction.user.id)
        await view.show_period(interaction, 7, "Weekly")

    @tree.command(name="myusage", description="Show your token and speech usage")
    async def myusage(interaction: discord.Interaction):
        view = UsagePeriodView(None, str(interaction.user.id), interaction.user.id)
        await view.show_period(interaction, 7, "Weekly")

    @tree.command(name="refreshprofiles", description="Refresh all user profiles in the server")
    @app_commands.default_permissions(administrator=True)
    async def refreshprofiles(interaction: discord.Interaction):
        # Check permissions manually
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                title="❌ Permission Denied",
                description="You need Administrator permissions to use this command.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        await interaction.response.defer()
        
        if not interaction.guild:
            await interaction.edit_original_response(content="This command can only be used in a server")
            return
        
        saved_count = 0
        for member in interaction.guild.members:
            try:
                # Get roles as list of role names
                roles = [role.name for role in member.roles if not role.is_default()]
                
                # Use database function directly
                save_user_profile(
                    user_id=str(member.id),
                    username=member.name,
                    display_name=member.display_name,
                    discriminator=str(member.discriminator) if hasattr(member, 'discriminator') else None,
                    avatar_url=member.avatar.url if member.avatar else None,
                    description=None,
                    pronunciation=None,
                    joined_discord=member.created_at.isoformat() if member.created_at else None,
                    joined_server=member.joined_at.isoformat() if member.joined_at else None,
                    guild_id=str(interaction.guild.id),
                    roles=roles
                )
                saved_count += 1
                if saved_count % 50 == 0:
                    await interaction.edit_original_response(content=f"⏳ Refreshing profiles... {saved_count}/{interaction.guild.member_count}")
            except Exception as e:
                print(f"Error saving profile for {member.display_name}: {e}")
        
        embed = discord.Embed(
            title="✅ Profiles Refreshed",
            description=f"Successfully refreshed {saved_count} user profiles",
            color=discord.Color.green()
        )
        embed.add_field(name="Total Members", value=str(interaction.guild.member_count))
        embed.add_field(name="Profiles Saved", value=str(saved_count))
        embed.set_footer(text="Profile system is now up to date")
        
        await interaction.edit_original_response(embed=embed)

    @tree.command(name="changelog", description="View Jenny's version history and changes")
    async def changelog(interaction: discord.Interaction):
        changelog_entries = get_changelog()
        
        if not changelog_entries:
            embed = discord.Embed(
                title="📜 Changelog",
                description="No changelog entries found.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        # Each release gets its own embed so the complete history remains readable.
        changelog_entries = sorted(changelog_entries, key=lambda entry: tuple(int(part) if part.isdigit() else 0 for part in entry["version"].split(".")), reverse=True)
        view = ChangelogPageView(changelog_entries, interaction.user.id)
        await interaction.response.send_message(embed=view.make_embed(), view=view)
        view.message = await interaction.original_response()

    @tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        cause = getattr(error, "original", error)
        print(f"[COMMAND] /{interaction.command.name if interaction.command else 'unknown'} failed: {cause}")
        if interaction.guild:
            logs_id = get_logs_channel_id(str(interaction.guild.id))
            log_channel = interaction.guild.get_channel(int(logs_id)) if logs_id else None
            if isinstance(log_channel, (discord.TextChannel, discord.Thread)):
                error_log = discord.Embed(
                    title=f"Slash command failed: /{interaction.command.name if interaction.command else 'unknown'}",
                    description=f"{type(cause).__name__}: {cause}"[:3500],
                    color=discord.Color.red(), timestamp=discord.utils.utcnow())
                error_log.add_field(name="Requested by", value=f"{interaction.user} ({interaction.user.id})", inline=False)
                try:
                    await log_channel.send(embed=error_log, allowed_mentions=discord.AllowedMentions.none())
                except (discord.Forbidden, discord.HTTPException) as log_error:
                    print(f"[LOGS] Could not post slash command failure to {log_channel.id}: {log_error}")
        embed = discord.Embed(title="Command failed", description=str(cause)[:1000], color=discord.Color.red())
        if isinstance(cause, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            embed.description = "A required Jenny service is offline or timed out. Start the voice/API service and try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException as response_error:
            print(f"[COMMAND] Could not report command failure: {response_error}")
