"""Submit explicitly authorized Discord reports to a configured GitHub issue tracker."""

import asyncio
from collections import deque
import os
import re
import time

import discord
import requests


DEFAULT_REPOSITORY = "MotrynStudios/Jenny-AI-Discord-Bot"
_attempts = deque()


def report_repository():
    repository = os.getenv("GITHUB_REPORT_REPO", "").strip() or DEFAULT_REPOSITORY
    if repository.casefold() == "motrynstudios/jenny":
        return DEFAULT_REPOSITORY
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository):
        return None
    return repository


def create_issue(repository, token, title, details):
    response = requests.post(
        f"https://api.github.com/repos/{repository}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": f"{details}\n\nSubmitted through Jenny's Discord report form."},
        timeout=10, allow_redirects=False,
    )
    if response.status_code != 201:
        raise RuntimeError(f"GitHub returned HTTP {response.status_code}")
    return response.json()["number"]


class ReportIssueModal(discord.ui.Modal, title="Post a public GitHub issue"):
    summary = discord.ui.TextInput(label="Issue title", max_length=120)
    details = discord.ui.TextInput(
        label="Public details only",
        placeholder="What happened? How can we reproduce it? Leave out keys, private chats and personal data.",
        style=discord.TextStyle.paragraph, min_length=20, max_length=3000,
    )

    def __init__(self, repository, token):
        super().__init__()
        self.repository, self.token = repository, token

    async def on_submit(self, interaction):
        title, details = self.summary.value.strip(), self.details.value.strip()
        if not title or len(details) < 20:
            await interaction.response.send_message("Include a title and at least 20 characters of public details.", ephemeral=True)
            return
        now = time.monotonic()
        while _attempts and now - _attempts[0][0] >= 3600:
            _attempts.popleft()
        if len(_attempts) >= 10 or any(uid == interaction.user.id and now - ts < 600 for ts, uid in _attempts):
            await interaction.response.send_message("Reporting is rate limited. Try later or use GitHub directly.", ephemeral=True)
            return
        _attempts.append((now, interaction.user.id))
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            number = await asyncio.to_thread(create_issue, self.repository, self.token, title, details)
        except (requests.RequestException, ValueError, RuntimeError, KeyError) as error:
            print(f"[REPORT] Could not confirm issue creation: {type(error).__name__}")
            await interaction.followup.send(
                f"I couldn't confirm the report. Check [existing issues](https://github.com/{self.repository}/issues) before resubmitting.",
                ephemeral=True,
            )
            return
        print(f"[REPORT] Created issue #{number} in {self.repository}")
        await interaction.followup.send(f"Posted [issue #{number}](https://github.com/{self.repository}/issues/{number}).", ephemeral=True)
