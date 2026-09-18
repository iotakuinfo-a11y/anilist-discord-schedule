
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

ANILIST_API = "https://graphql.anilist.co"

USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# Timezone used to determine what counts as "today".
DISPLAY_TIMEZONE = os.environ.get(
    "DISPLAY_TIMEZONE",
    "Pacific/Honolulu",
)

# Discord allows up to 1024 characters per embed field.
# We stay safely below that limit.
MAX_FIELD_LENGTH = 1000

MAX_AIRED = 50
MAX_UPCOMING = 50

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


def get_timezone():
    try:
        return ZoneInfo(DISPLAY_TIMEZONE)
    except Exception:
        print(
            f"Invalid timezone '{DISPLAY_TIMEZONE}'. "
            "Falling back to UTC."
        )
        return timezone.utc


def get_anime(status):
    print(f"Fetching AniList {status} list...")

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
        print("AniList returned an error:")
        print(response.text)

    response.raise_for_status()

    data = response.json()

    if "errors" in data:
        print("AniList GraphQL errors:")
        print(data["errors"])
        raise RuntimeError(str(data["errors"]))

    lists = data["data"]["MediaListCollection"]["lists"]

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
        return f"[{title}]({media['siteUrl']})"

    return title


def discord_relative_time(timestamp):
    """
    Discord automatically displays:
      2 hours ago
      5 minutes ago
      in 3 hours
      in 2 days
    """
    return f"<t:{timestamp}:R>"


def is_today(timestamp, tz):
    """
    Check whether an episode aired today
    in the configured timezone.
    """

    airing_date = datetime.fromtimestamp(
        timestamp,
        tz,
    ).date()

    today = datetime.now(tz).date()

    return airing_date == today


def get_aired_today(planning, now):
    """
    Find Planning episodes that actually aired today.
    """

    tz = get_timezone()

    aired_today = []

    for media in planning:
        schedule = media.get("airingSchedule")

        if not schedule:
            continue

        nodes = schedule.get("nodes") or []

        for episode in nodes:
            airing_at = episode.get("airingAt")
            episode_number = episode.get("episode")

            if not airing_at or not episode_number:
                continue

            # Episode must already have aired.
            if airing_at > now:
                continue

            # Episode must have aired today.
            if not is_today(airing_at, tz):
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


def get_upcoming(planning, now):
    """
    Find the next upcoming episode for each Planning anime.
    """

    upcoming = []

    for media in planning:
        next_episode = media.get("nextAiringEpisode")

        if not next_episode:
            continue

        airing_at = next_episode.get("airingAt")
        episode_number = next_episode.get("episode")

        if not airing_at or not episode_number:
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


def split_into_fields(entries, field_name):
    """
    Split a list of formatted anime entries into multiple
    Discord embed fields so nothing gets cut off.

    Each field stays below Discord's 1024-character limit.
    """

    fields = []

    current_entries = []
    current_length = 0

    for entry in entries:
        entry_length = len(entry)

        # Account for the \n\n separator.
        separator_length = 2 if current_entries else 0

        # If adding this entry would exceed our limit,
        # start a new field.
        if (
            current_entries
            and current_length
            + separator_length
            + entry_length
            > MAX_FIELD_LENGTH
        ):
            fields.append(
                {
                    "name": field_name,
                    "value": "\n\n".join(current_entries),
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

    # Add the final field.
    if current_entries:
        fields.append(
            {
                "name": field_name,
                "value": "\n\n".join(current_entries),
                "inline": False,
            }
        )

    return fields


def build_embed(planning):
    now = int(time.time())

    aired_today = get_aired_today(
        planning,
        now,
    )

    upcoming = get_upcoming(
        planning,
        now,
    )

    fields = []

    # =========================================================
    # AIRED TODAY
    # =========================================================

    if aired_today:
        aired_entries = []

        for item in aired_today[:MAX_AIRED]:
            media = item["media"]
            title = format_title(media)

            aired_entries.append(
                f"**{title}**\n"
                f"Episode **{item['episode']}** · "
                f"{discord_relative_time(item['airing_at'])}"
            )

        fields.extend(
            split_into_fields(
                aired_entries,
                "🔴 Aired",
            )
        )

    # =========================================================
    # UPCOMING
    # =========================================================

    if upcoming:
        upcoming_entries = []

        for item in upcoming[:MAX_UPCOMING]:
            media = item["media"]
            title = format_title(media)

            upcoming_entries.append(
                f"**{title}**\n"
                f"Episode **{item['episode']}** · "
                f"{discord_relative_time(item['airing_at'])}"
            )

        fields.extend(
            split_into_fields(
                upcoming_entries,
                "🟢 Upcoming",
            )
        )

    # =========================================================
    # NOTHING FOUND
    # =========================================================

    if not fields:
        fields.append(
            {
                "name": "📺 Schedule",
                "value": (
                    "Nothing aired today and "
                    "no upcoming episodes found."
                ),
                "inline": False,
            }
        )

    # =========================================================
    # EMBED
    # =========================================================

    embed = {
        "title": "📅 Release Schedule",
        "description": "AniList → Planning",
        "fields": fields,
        "footer": {
            "text": "Automatically updated • AniList",
        },
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    # Use an AniList cover as the thumbnail.
    for media in planning:
        image = (
            media.get("coverImage", {})
            .get("medium")
        )

        if image:
            embed["thumbnail"] = {
                "url": image,
            }
            break

    return embed


def get_existing_message():
    return os.environ.get(
        "DISCORD_MESSAGE_ID",
        "",
    ).strip()


def send_webhook(payload):
    print("Sending new message to Discord...")

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
        f"Discord response status: "
        f"{response.status_code}"
    )

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2,
        )

        print(
            f"Rate limited. Waiting "
            f"{retry} seconds..."
        )

        time.sleep(float(retry))

        return send_webhook(payload)

    response.raise_for_status()

    return response.json()


def edit_webhook(message_id, payload):
    print(
        f"Updating existing Discord message: "
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
        f"Discord response status: "
        f"{response.status_code}"
    )

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2,
        )

        print(
            f"Rate limited. Waiting "
            f"{retry} seconds..."
        )

        time.sleep(float(retry))

        return edit_webhook(
            message_id,
            payload,
        )

    if response.status_code == 404:
        print(
            "Existing Discord message "
            "was not found."
        )

        return False

    response.raise_for_status()

    return True


def main():
    print(
        f"Getting AniList Planning list "
        f"for: {USERNAME}"
    )

    print(
        f"Using timezone: "
        f"{DISPLAY_TIMEZONE}"
    )

    planning = get_planning()

    print(
        f"Found {len(planning)} planning anime."
    )

    embed = build_embed(planning)

    payload = {
        "username": "AniList Schedule",
        "embeds": [embed],
        "allowed_mentions": {
            "parse": [],
        },
    }

    message_id = get_existing_message()

    # =========================================================
    # UPDATE EXISTING MESSAGE
    # =========================================================

    if message_id:
        success = edit_webhook(
            message_id,
            payload,
        )

        if success:
            print(
                f"Updated Discord message: "
                f"{message_id}"
            )

            print(
                f"DISCORD_MESSAGE_ID="
                f"{message_id}"
            )

            return

        print(
            "Existing message could not "
            "be updated."
        )

        print(
            "Creating a new Discord message..."
        )

    # =========================================================
    # CREATE NEW MESSAGE
    # =========================================================

    message = send_webhook(payload)

    message_id = message["id"]

    print(
        f"Created message: {message_id}"
    )

    print(
        f"DISCORD_MESSAGE_ID={message_id}"
    )


if __name__ == "__main__":
    main()

