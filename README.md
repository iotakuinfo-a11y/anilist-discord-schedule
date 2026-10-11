# AniList → Discord Schedule

Automatically publishes your **AniList Planning anime schedule** to a Discord channel using a Discord webhook and GitHub Actions.

The workflow runs every **15 minutes** and displays episodes in two sections:

- 🔴 **Aired Recently** — episodes from your Planning list that aired today, using your configured timezone.
- 🟢 **Upcoming Episodes** — the next episode for each Planning anime that is scheduled to air in the **next 24 hours**.

## Features

- ⏱️ Discord relative timestamps (for example, “in 3 hours” or “2 hours ago”).
- 🔗 Anime titles link to their AniList pages.
- 🖼️ Anime cover artwork appears in the embeds when available.
- 🌎 Configurable timezone; defaults to `Pacific/Honolulu`.
- 🔄 Edits existing schedule messages when possible rather than posting a new schedule every run.
- 📋 Splits longer schedules across multiple embeds and Discord messages to stay within Discord's embed limits.
- 🧹 Deletes surplus schedule messages when fewer messages are needed.
- 🚫 Disables automatic mentions in webhook messages.
- 🤖 Runs through GitHub Actions, so no personal computer or server needs to stay online.

## How it works

**AniList GraphQL API → Python → Discord Webhook → GitHub Actions**

On each run, the workflow:

1. Fetches the anime in your AniList **Planning** list.
2. Finds episodes that aired today in the configured timezone.
3. Finds each anime's next episode if it airs between now and the next 24 hours.
4. Sorts aired episodes from newest to oldest and upcoming episodes from soonest to latest.
5. Builds the **Aired** and **Upcoming** embeds.
6. Updates existing Discord schedule messages or creates replacements if a saved message no longer exists.
7. Saves the Discord message IDs in `discord_message_ids.json` and uploads the file as a GitHub Actions artifact for the next run.

The workflow restores the latest saved message-ID artifact before running the script. If no previous artifact exists, the script starts without saved IDs and creates the messages it needs.

## Project structure

```text
anilist-discord-schedule/
├── update.py
├── README.md
└── .github/
    └── workflows/
        └── update.yml
```

## Requirements

You need:

- A GitHub repository with GitHub Actions enabled
- An AniList account
- A Discord server and channel
- A Discord webhook for the channel

## GitHub Actions configuration

Open:

**Repository → Settings → Secrets and variables → Actions**

### Repository variable

Create this variable under **Variables**:

#### `ANILIST_USERNAME`

Your AniList username.

Example:

```text
your_anilist_username
```

### Repository secret

Create this secret under **Secrets**:

#### `DISCORD_WEBHOOK_URL`

Paste the Discord webhook URL for the channel where the schedule should appear.

**Never put the webhook URL directly in your code or commit it to the repository.** Keep it in GitHub Secrets.

### Timezone

The workflow currently passes:

```text
DISPLAY_TIMEZONE=Pacific/Honolulu
```

This controls the timezone used to determine which episodes aired **today**. The default in the Python script is also `Pacific/Honolulu`. You can change the workflow's `DISPLAY_TIMEZONE` value to another valid IANA timezone, for example:

```text
America/Los_Angeles
America/New_York
Europe/London
Asia/Tokyo
Australia/Sydney
```

## Discord message ID tracking

The current workflow **does not require a `DISCORD_MESSAGE_ID` repository variable**.

Instead, the script stores the IDs of its schedule messages in:

```text
discord_message_ids.json
```

GitHub Actions uploads that file as an artifact named `discord-message-ids` and restores it on later runs. This lets the script edit the right messages, replace messages that have been deleted, and remove extra schedule messages when they are no longer needed.

The workflow needs these permissions:

- `contents: read`
- `actions: read`

The upload step uses `actions/upload-artifact` to preserve the message-ID file between runs.

## Running the workflow manually

1. Open the repository on GitHub.
2. Select **Actions**.
3. Choose **Update AniList Discord Embed**.
4. Click **Run workflow**.

The workflow also runs automatically every 15 minutes. Scheduled GitHub Actions runs may occasionally be delayed.

## Customizing the embed titles

In `update.py`, look near the bottom of `main()` for the `build_embeds()` calls. The first argument is the embed title. For example:

```python
build_embeds(
    "🔴 Episodes Aired Today",
    aired,
    "No Planning anime aired today.",
)
```

The upcoming section can be titled something like `🟢 Airing in the Next 24 Hours`. The third argument is the text shown when that section has no episodes.

## Discord embed limits

Discord limits the combined text across all embeds in a single message to 6,000 characters and allows up to 10 embeds per message. The script uses a lower safety budget and splits larger schedules into multiple messages to help avoid exceeding those limits.

## Troubleshooting

- **No episodes in Upcoming:** The next scheduled episode for an anime must fall within the next 24 hours.
- **An old message was deleted:** The script should create a replacement when it tries to edit the missing message.
- **Artifact restore fails:** Check the workflow log and confirm the workflow has `actions: read` permission.
- **Discord webhook errors:** Confirm `DISCORD_WEBHOOK_URL` is set correctly in repository Secrets and that the webhook still exists.
- **AniList request errors:** Check the workflow log for the API response and confirm the AniList username is correct.
