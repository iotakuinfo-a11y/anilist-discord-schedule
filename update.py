
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

# Discord embed descriptions have a 4096-character limit.
# Stay safely below it.
MAX_DESCRIPTION_LENGTH = 3800


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


def make_entry(item):
    media = item["media"]

    return (
        f"**{format_title(media)}**\n"
        f"Episode **{item['episode']}** · "
        f"{discord_relative_time(item['airing_at'])}"
    )


def split_entries(entries):
    """
    Split entries into groups that fit inside
    Discord's embed description limit.
    """

    groups = []

    current = []
    current_length = 0

    for entry in entries:
        separator_length = 2 if current else 0

        new_length = (
            current_length
            + separator_length
            + len(entry)
        )

        if (
            current
            and new_length > MAX_DESCRIPTION_LENGTH
        ):
            groups.append(current)

            current = []
            current_length = 0

            separator_length = 0

        current.append(entry)

        current_length += (
            separator_length
            + len(entry)
        )

    if current:
        groups.append(current)

    return groups


def build_embeds(
    title,
    description,
    items,
    empty_description,
):
    entries = [
        make_entry(item)
        for item in items
    ]

    # --------------------------------------------------------
    # No entries
    # --------------------------------------------------------

    if not entries:
        return [
            {
                "title": title,
                "description": empty_description,
                "footer": {
                    "text": "Automatically updated • AniList"
                },
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        ]

    # --------------------------------------------------------
    # Split into multiple embeds if necessary
    # --------------------------------------------------------

    groups = split_entries(entries)

    embeds = []

    for index, group in enumerate(groups, start=1):
        if len(groups) == 1:
            embed_title = title
        else:
            embed_title = (
                f"{title} — Part {index}"
            )

        embed = {
            "title": embed_title,
            "description": "\n\n".join(group),
            "footer": {
                "text": "Automatically updated • AniList"
            },
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        # Cover image for the first anime in
        # this particular embed.
        media = items[
            sum(len(group) for group in groups[:index - 1])
        ]["media"]

        image = (
            media
            .get("coverImage", {})
            .get("medium")
        )

        if image:
            embed["thumbnail"] = {
                "url": image
            }

        embeds.append(embed)

    return embeds


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

    aired_embeds = build_embeds(
        "🔴 Aired",
        "Episodes that aired today",
        aired_today,
        "No Planning anime aired today.",
    )

    upcoming_embeds = build_embeds(
        "🟢 Upcoming",
        "Next episodes from Planning",
        upcoming,
        "No upcoming episodes found in Planning.",
    )

    embeds = (
        aired_embeds
        + upcoming_embeds
    )

    payload = {
        "username": "AniList Schedule",
        "embeds": embeds,
        "allowed_mentions": {
            "parse": []
        },
    }

    print(
        f"Sending {len(embeds)} Discord embeds."
    )

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

