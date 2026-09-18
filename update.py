
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


ANILIST_API = "https://graphql.anilist.co"

USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

DISPLAY_TIMEZONE = os.environ.get(
    "DISPLAY_TIMEZONE",
    "Pacific/Honolulu",
)


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

    print(
        f"AniList response status: "
        f"{response.status_code}"
    )

    if response.status_code != 200:
        print(response.text)

    response.raise_for_status()

    data = response.json()

    if "errors" in data:
        print(data["errors"])
        raise RuntimeError(str(data["errors"]))

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

    unique = {}

    for media in anime:
        unique[media["id"]] = media

    return list(unique.values())


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
    return f"<t:{timestamp}:R>"


def is_today(timestamp, tz):
    airing_date = datetime.fromtimestamp(
        timestamp,
        tz,
    ).date()

    today = datetime.now(tz).date()

    return airing_date == today


def get_planning():
    return get_anime("PLANNING")


def get_aired_today(planning, now):
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

            if not airing_at:
                continue

            if not episode_number:
                continue

            if airing_at > now:
                continue

            if not is_today(airing_at, tz):
                continue

            aired_today.append(
                {
                    "media": media,
                    "episode": episode_number,
                    "airing_at": airing_at,
                }
            )

    aired_today.sort(
        key=lambda item: item["airing_at"],
        reverse=True,
    )

    return aired_today


def get_upcoming(planning, now):
    upcoming = []

    for media in planning:
        next_episode = media.get(
            "nextAiringEpisode"
        )

        if not next_episode:
            continue

        airing_at = next_episode.get("airingAt")
        episode_number = next_episode.get("episode")

        if not airing_at:
            continue

        if not episode_number:
            continue

        if airing_at <= now:
            continue

        upcoming.append(
            {
                "media": media,
                "episode": episode_number,
                "airing_at": airing_at,
            }
        )

    upcoming.sort(
        key=lambda item: item["airing_at"]
    )

    return upcoming


def build_aired_embed(aired_today):
    lines = []

    for item in aired_today:
        media = item["media"]

        lines.append(
            f"**{format_title(media)}**\n"
            f"Episode **{item['episode']}** · "
            f"{discord_relative_time(item['airing_at'])}"
        )

    if not lines:
        description = "No Planning anime aired today."
    else:
        description = "\n\n".join(lines)

    embed = {
        "title": "🔴 Aired",
        "description": description,
        "footer": {
            "text": "Automatically updated • AniList"
        },
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    if aired_today:
        image = (
            aired_today[0]["media"]
            .get("coverImage", {})
            .get("medium")
        )

        if image:
            embed["thumbnail"] = {
                "url": image
            }

    return embed


def build_upcoming_embed(upcoming):
    lines = []

    for item in upcoming:
        media = item["media"]

        lines.append(
            f"**{format_title(media)}**\n"
            f"Episode **{item['episode']}** · "
            f"{discord_relative_time(item['airing_at'])}"
        )

    if not lines:
        description = (
            "No upcoming episodes found in Planning."
        )
    else:
        description = "\n\n".join(lines)

    embed = {
        "title": "🟢 Upcoming",
        "description": description,
        "footer": {
            "text": "Automatically updated • AniList"
        },
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    if upcoming:
        image = (
            upcoming[0]["media"]
            .get("coverImage", {})
            .get("medium")
        )

        if image:
            embed["thumbnail"] = {
                "url": image
            }

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
            f"Rate limited. Waiting {retry} seconds..."
        )

        time.sleep(float(retry))

        return send_webhook(payload)

    response.raise_for_status()

    return response.json()


def edit_webhook(message_id, payload):
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
        f"Discord response status: "
        f"{response.status_code}"
    )

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2,
        )

        print(
            f"Rate limited. Waiting {retry} seconds..."
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
    print("=" * 48)
    print("AniList Discord Schedule")
    print("=" * 48)

    print(f"Username: {USERNAME}")
    print(f"Timezone: {DISPLAY_TIMEZONE}")

    planning = get_planning()

    print(
        f"Found {len(planning)} planning anime."
    )

    now = int(time.time())

    aired_today = get_aired_today(
        planning,
        now,
    )

    upcoming = get_upcoming(
        planning,
        now,
    )

    print(
        f"Aired today: {len(aired_today)}"
    )

    print(
        f"Upcoming: {len(upcoming)}"
    )

    aired_embed = build_aired_embed(
        aired_today
    )

    upcoming_embed = build_upcoming_embed(
        upcoming
    )

    payload = {
        "username": "AniList Schedule",

        "embeds": [
            aired_embed,
            upcoming_embed,
        ],

        "allowed_mentions": {
            "parse": []
        },
    }

    message_id = get_existing_message()

    if message_id:
        success = edit_webhook(
            message_id,
            payload,
        )

        if success:
            print(
                "Successfully updated Discord "
                f"message: {message_id}"
            )

            return

        print(
            "Existing message could not "
            "be updated."
        )

        print(
            "Creating a new Discord message..."
        )

    message = send_webhook(payload)

    message_id = message["id"]

    print(
        f"Created message: {message_id}"
    )

    print(
        "DISCORD_MESSAGE_ID="
        f"{message_id}"
    )


if __name__ == "__main__":
    main()

