
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


# ============================================================
# CONFIGURATION
# ============================================================

ANILIST_API = "https://graphql.anilist.co"

USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# Used to determine what counts as "today".
# You can override this with a GitHub Actions variable
# called DISPLAY_TIMEZONE.
DISPLAY_TIMEZONE = os.environ.get(
    "DISPLAY_TIMEZONE",
    "Pacific/Honolulu",
)

# Discord embed fields have a 1024-character limit.
# We stay safely below that limit.
MAX_FIELD_LENGTH = 1000

# Maximum number of anime shown in each section.
MAX_AIRED = 50
MAX_UPCOMING = 50


# ============================================================
# ANILIST QUERY
# ============================================================

QUERY = """
query ($userName: String, $status: MediaListStatus) {
  MediaListCollection(
    userName: $userName
    type: ANIME
    status: $status
    perChunk: 500
  ) {
    lists {
      entries {
        media {
          id

          title {
            userPreferred
            romaji
            english
          }

          siteUrl

          coverImage {
            medium
          }

          nextAiringEpisode {
            airingAt
            episode
            timeUntilAiring
          }

          airingSchedule(
            notYetAired: false
            perPage: 25
          ) {
            nodes {
              airingAt
              episode
            }
          }
        }
      }
    }
  }
}
"""


# ============================================================
# TIMEZONE
# ============================================================

def get_timezone():
    try:
        return ZoneInfo(DISPLAY_TIMEZONE)

    except Exception:
        print(
            f"Invalid timezone '{DISPLAY_TIMEZONE}'. "
            "Falling back to UTC."
        )

        return timezone.utc


# ============================================================
# ANILIST
# ============================================================

def get_anime(status):
    print(
        f"Fetching AniList {status} list..."
    )

    response = requests.post(
        ANILIST_API,
        json={
            "query": QUERY,
            "variables": {
                "userName": USERNAME,
                "status": status,
            },
        },
        timeout=30,
    )

    if response.status_code != 200:
        print(
            "AniList returned an error:"
        )

        print(response.text)

    response.raise_for_status()

    data = response.json()

    if "errors" in data:
        print(
            "AniList GraphQL errors:"
        )

        print(data["errors"])

        raise RuntimeError(
            str(data["errors"])
        )

    lists = (
        data["data"]
        ["MediaListCollection"]
        ["lists"]
    )

    anime = []

    for anime_list in lists:
        for entry in anime_list["entries"]:
            media = entry["media"]

            if media:
                anime.append(media)

    # Remove duplicates.
    unique = {}

    for media in anime:
        unique[media["id"]] = media

    return list(unique.values())


def get_planning():
    return get_anime("PLANNING")


# ============================================================
# ANIME HELPERS
# ============================================================

def anime_title(media):
    title = media["title"]

    return (
        title.get("userPreferred")
        or title.get("english")
        or title.get("romaji")
        or "Unknown Anime"
    )


def format_title(media):
    title = anime_title(media)

    if media.get("siteUrl"):
        return (
            f"[{title}]"
            f"({media['siteUrl']})"
        )

    return title


# ============================================================
# DISCORD TIMESTAMPS
# ============================================================

def discord_relative_time(timestamp):
    """
    Discord will display this as something like:

        2 hours ago
        5 minutes ago
        in 3 hours
        in 2 days
    """

    return f"<t:{timestamp}:R>"


# ============================================================
# DATE HELPERS
# ============================================================

def is_today(timestamp, tz):
    """
    Returns True if the airing timestamp occurred
    on today's date in the configured timezone.
    """

    airing_date = datetime.fromtimestamp(
        timestamp,
        tz,
    ).date()

    today = datetime.now(tz).date()

    return airing_date == today


# ============================================================
# AIRED TODAY
# ============================================================

def get_aired_today(planning, now):
    """
    Find Planning anime episodes that actually aired today.
    """

    tz = get_timezone()

    aired_today = []

    for media in planning:
        schedule = media.get(
            "airingSchedule"
        )

        if not schedule:
            continue

        nodes = schedule.get(
            "nodes"
        ) or []

        for episode in nodes:
            airing_at = episode.get(
                "airingAt"
            )

            episode_number = episode.get(
                "episode"
            )

            if not airing_at:
                continue

            if not episode_number:
                continue

            # Must already have aired.
            if airing_at > now:
                continue

            # Must have aired today.
            if not is_today(
                airing_at,
                tz,
            ):
                continue

            aired_today.append(
                {
                    "media": media,
                    "episode": episode_number,
                    "airing_at": airing_at,
                }
            )

    # Most recently aired first.
    aired_today.sort(
        key=lambda item: item["airing_at"],
        reverse=True,
    )

    return aired_today


# ============================================================
# UPCOMING
# ============================================================

def get_upcoming(planning, now):
    """
    Find the next upcoming episode for each
    Planning anime.
    """

    upcoming = []

    for media in planning:
        next_episode = media.get(
            "nextAiringEpisode"
        )

        if not next_episode:
            continue

        airing_at = next_episode.get(
            "airingAt"
        )

        episode_number = next_episode.get(
            "episode"
        )

        if not airing_at:
            continue

        if not episode_number:
            continue

        # Must be in the future.
        if airing_at <= now:
            continue

        upcoming.append(
            {
                "media": media,
                "episode": episode_number,
                "airing_at": airing_at,
            }
        )

    # Soonest first.
    upcoming.sort(
        key=lambda item: item["airing_at"]
    )

    return upcoming


# ============================================================
# SPLIT LONG LISTS
# ============================================================

def split_into_fields(
    entries,
    field_name,
):
    """
    Discord embed fields can contain a maximum of
    1024 characters.

    This function splits long anime lists into
    multiple fields without cutting an anime entry
    in half.
    """

    fields = []

    current_entries = []
    current_length = 0

    for entry in entries:
        entry_length = len(entry)

        separator_length = (
            2
            if current_entries
            else 0
        )

        # If adding this entry would exceed
        # our safe limit, create the current field.
        if (
            current_entries
            and
            current_length
            + separator_length
            + entry_length
            > MAX_FIELD_LENGTH
        ):
            fields.append(
                {
                    "name": field_name,
                    "value": "\n\n".join(
                        current_entries
                    ),
                    "inline": False,
                }
            )

            current_entries = []
            current_length = 0

            separator_length = 0

        current_entries.append(entry)

        current_length += (
            separator_length
            + entry_length
        )

    # Add final field.
    if current_entries:
        fields.append(
            {
                "name": field_name,
                "value": "\n\n".join(
                    current_entries
                ),
                "inline": False,
            }
        )

    return fields


# ============================================================
# BUILD AIRED EMBED
# ============================================================

def build_aired_embed(
    aired_today,
):
    entries = []

    for item in aired_today[:MAX_AIRED]:
        media = item["media"]

        title = format_title(
            media
        )

        entries.append(
            f"**{title}**\n"
            f"Episode **{item['episode']}** · "
            f"{discord_relative_time(item['airing_at'])}"
        )

    # --------------------------------------------------------
    # No episodes aired today
    # --------------------------------------------------------

    if not entries:
        return {
            "title": "🔴 Aired",
            "description": (
                "No Planning anime "
                "aired today."
            ),
            "footer": {
                "text": (
                    "Automatically updated • AniList"
                ),
            },
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    # --------------------------------------------------------
    # Create fields
    # --------------------------------------------------------

    fields = split_into_fields(
        entries,
        "🔴 Aired",
    )

    embed = {
        "title": "🔴 Aired",
        "description": (
            "Episodes that aired today"
        ),
        "fields": fields,
        "footer": {
            "text": (
                "Automatically updated • AniList"
            ),
        },
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    # Use the most recently aired anime's
    # AniList cover as the thumbnail.
    first_media = aired_today[0]["media"]

    image = (
        first_media
        .get("coverImage", {})
        .get("medium")
    )

    if image:
        embed["thumbnail"] = {
            "url": image
        }

    return embed


# ============================================================
# BUILD UPCOMING EMBED
# ============================================================

def build_upcoming_embed(
    upcoming,
):
    entries = []

    for item in upcoming[:MAX_UPCOMING]:
        media = item["media"]

        title = format_title(
            media
        )

        entries.append(
            f"**{title}**\n"
            f"Episode **{item['episode']}** · "
            f"{discord_relative_time(item['airing_at'])}"
        )

    # --------------------------------------------------------
    # No upcoming episodes
    # --------------------------------------------------------

    if not entries:
        return {
            "title": "🟢 Upcoming",
            "description": (
                "No upcoming episodes "
                "found in Planning."
            ),
            "footer": {
                "text": (
                    "Automatically updated • AniList"
                ),
            },
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    # --------------------------------------------------------
    # Create fields
    # --------------------------------------------------------

    fields = split_into_fields(
        entries,
        "🟢 Upcoming",
    )

    embed = {
        "title": "🟢 Upcoming",
        "description": (
            "Next episodes from Planning"
        ),
        "fields": fields,
        "footer": {
            "text": (
                "Automatically updated • AniList"
            ),
        },
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    # Use the next upcoming anime's
    # AniList cover as the thumbnail.
    first_media = upcoming[0]["media"]

    image = (
        first_media
        .get("coverImage", {})
        .get("medium")
    )

    if image:
        embed["thumbnail"] = {
            "url": image
        }

    return embed


# ============================================================
# DISCORD MESSAGE
# ============================================================

def get_existing_message():
    return os.environ.get(
        "DISCORD_MESSAGE_ID",
        "",
    ).strip()


def send_webhook(payload):
    print(
        "Sending new message to Discord..."
    )

    url = WEBHOOK_URL

    if "?" in url:
        url += "&wait=true"
    else:
        url += "?wait=true"

    response = requests.post(
        url,
        json=payload,
        timeout=30,
    )

    print(
        "Discord response status: "
        f"{response.status_code}"
    )

    # --------------------------------------------------------
    # Rate limit
    # --------------------------------------------------------

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2,
        )

        print(
            "Rate limited. Waiting "
            f"{retry} seconds..."
        )

        time.sleep(
            float(retry)
        )

        return send_webhook(
            payload
        )

    response.raise_for_status()

    return response.json()


def edit_webhook(
    message_id,
    payload,
):
    print(
        "Updating existing Discord message: "
        f"{message_id}"
    )

    url = (
        f"{WEBHOOK_URL}"
        f"/messages/{message_id}"
    )

    response = requests.patch(
        url,
        json=payload,
        timeout=30,
    )

    print(
        "Discord response status: "
        f"{response.status_code}"
    )

    # --------------------------------------------------------
    # Rate limit
    # --------------------------------------------------------

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2,
        )

        print(
            "Rate limited. Waiting "
            f"{retry} seconds..."
        )

        time.sleep(
            float(retry)
        )

        return edit_webhook(
            message_id,
            payload,
        )

    # --------------------------------------------------------
    # Message doesn't exist
    # --------------------------------------------------------

    if response.status_code == 404:
        print(
            "Existing Discord message "
            "was not found."
        )

        return False

    response.raise_for_status()

    return True


# ============================================================
# MAIN
# =========================================

