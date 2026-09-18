# AniList → Discord Schedule

Automatically displays your **AniList Planning anime schedule** in a Discord channel using a Discord webhook and GitHub Actions.

The workflow updates automatically every **15 minutes**.

## Features

* 🔴 **Aired** — shows Planning anime episodes that aired today
* 🟢 **Upcoming** — shows the next episode for each Planning anime
* ⏱️ Uses Discord's relative timestamps such as:

  * `2 hours ago`
  * `in 3 hours`
  * `in 2 days`
* 🔗 Anime titles link directly to their AniList pages
* 🖼️ Uses AniList cover artwork
* 🌎 Supports configurable timezones
* 🔄 Automatically updates the same Discord message
* 📋 Automatically splits long schedules across multiple Discord embeds
* 🚫 No Discord mentions or notifications are triggered
* 🤖 Runs automatically through GitHub Actions

## How It Works

The project uses:

**AniList GraphQL API → Python → Discord Webhook → GitHub Actions**

Every 15 minutes GitHub Actions:

1. Fetches your AniList **Planning** list.
2. Checks which episodes have aired today.
3. Finds the next upcoming episode for each Planning anime.
4. Sorts aired episodes from newest to oldest.
5. Sorts upcoming episodes from soonest to latest.
6. Builds separate **Aired** and **Upcoming** Discord embeds.
7. Updates the existing Discord message.

If the previous Discord message no longer exists, the script automatically creates a new one.

## Project Structure

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

* A GitHub repository
* An AniList account
* A Discord server/channel
* A Discord webhook
* GitHub Actions enabled

No server or computer needs to stay online. GitHub Actions runs the script for you.

## GitHub Variables

Go to:

**Repository → Settings → Secrets and variables → Actions**

Under **Variables**, create:

### `ANILIST_USERNAME`

Your AniList username.

Example:

```text
your_anilist_username
```

### `DISPLAY_TIMEZONE`

Optional.

This determines which timezone is used to decide whether an episode aired **today**.

Example:

```text
Pacific/Honolulu
```

If this variable isn't created, the script defaults to:

```text
Pacific/Honolulu
```

You can use any valid IANA timezone, such as:

```text
America/Los_Angeles
America/New_York
Europe/London
Asia/Tokyo
Australia/Sydney
```

## GitHub Secrets

Under:

**Settings → Secrets and variables → Actions → Secrets**

create:

### `DISCORD_WEBHOOK_URL`

Paste your Discord webhook URL here.

**Do not put the webhook URL directly into `update.py` or `update.yml`.**

Using a GitHub Secret keeps it hidden from the repository.

## Discord Message ID

The workflow can optionally use:

```text
DISCORD_MESSAGE_ID
```

as a GitHub repository variable.

This is the ID of the Discord message that the script should update.

If the variable is missing, the script creates a new Discord message.

If the saved message ID points to a message that no longer exists, the script automatically creates a new message.

After creating a new message, the Actions log will display:

```text
DISCORD_MESSAGE_ID=123456789012345678
```

You can then save that ID as the repository variable:

**Settings → Secrets and variables →**
