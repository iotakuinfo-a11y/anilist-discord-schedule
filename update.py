
import os
import time
from datetime import datetime, timezone

import requests

ANILIST_API = "https://graphql.anilist.co"

USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

MAX_UPCOMING = 15
MAX_PLANNING_AIRED = 15
MAX_PLANNING_UPCOMING = 15

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

          episodes
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
            sort: TIME_DESC
            perPage: 1
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


def get_anime(status):
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

    response.raise_for_status()

    data = response.json()

    if "errors" in data:
        raise RuntimeError(str(data["errors"]))

    lists = data["data"]["MediaListCollection"]["lists"]

    anime = []

    for anime_list in lists:
        for entry in anime_list["entries"]:
            media = entry["media"]

            if media:
                anime.append(media)

    # Remove duplicates
    unique = {}

    for media in anime:
        unique[media["id"]] = media

    return list(unique.values())


def get_all_anime():
    current = get_anime("CURRENT")
    planning = get_anime("PLANNING")

    return current, planning


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


def discord_time(timestamp):
    return f"<t:{timestamp}:R>"


def get_latest_aired_episode(media, now):
    """
    Get the most recently aired episode from AniList's
    airing schedule.

    Returns:
        {
            "episode": episode_number,
            "airing_at": unix_timestamp
        }

    or None if no aired episode is available.
    """

    schedule = media.get("airingSchedule")

    if not schedule:
        return None

    nodes = schedule.get("nodes") or []

    aired = [
        item
        for item in nodes
        if item.get("airingAt", 0) <= now
    ]

    if not aired:
        return None

    latest = max(
        aired,
        key=lambda item: item["airingAt"]
    )

    return {
        "episode": latest["episode"],
        "airing_at": latest["airingAt"],
    }


def build_embed(current, planning):
    now = int(time.time())

    current_upcoming = []
    planning_upcoming = []
    planning_aired = []

    # =========================================================
    # CURRENTLY WATCHING
    #
    # Only show future episodes.
    # Soonest episode first.
    # =========================================================

    for media in current:
        next_episode = media.get("nextAiringEpisode")

        if not next_episode:
            continue

        airing_at = next_episode["airingAt"]
        episode = next_episode["episode"]

        if airing_at > now:
            current_upcoming.append(
                {
                    "media": media,
                    "episode": episode,
                    "airing_at": airing_at,
                }
            )

    # =========================================================
    # PLANNING
    # =========================================================

    for media in planning:

        # -----------------------------------------------------
        # NEXT UPCOMING EPISODE
        # -----------------------------------------------------

        next_episode = media.get("nextAiringEpisode")

        if next_episode:
            airing_at = next_episode["airingAt"]
            episode = next_episode["episode"]

            if airing_at > now:
                planning_upcoming.append(
                    {
                        "media": media,
                        "episode": episode,
                        "airing_at": airing_at,
                    }
                )

        # -----------------------------------------------------
        # LATEST AIRED EPISODE
        #
        # Uses the actual AniList airingSchedule timestamp.
        # -----------------------------------------------------

        latest_aired = get_latest_aired_episode(
            media,
            now
        )

        if latest_aired:
            planning_aired.append(
                {
                    "media": media,
                    "episode": latest_aired["episode"],
                    "airing_at": latest_aired["airing_at"],
                }
            )

    # =========================================================
    # SORTING
    # =========================================================

    # Currently Watching:
    # Soonest upcoming episode first.
    current_upcoming.sort(
        key=lambda x: x["airing_at"]
    )

    # Planning Upcoming:
    # Soonest upcoming episode first.
    planning_upcoming.sort(
        key=lambda x: x["airing_at"]
    )

    # Planning Aired:
    # Most recently aired episode first.
    planning_aired.sort(
        key=lambda x: x["airing_at"],
        reverse=True
    )

    fields = []

    # =========================================================
    # PLANNING — AIRED
    # =========================================================

    if planning_aired:
        text = []

        for item in planning_aired[:MAX_PLANNING_AIRED]:
            media = item["media"]
            title = format_title(media)

            text.append(
                f"**{title}**\n"
                f"Episode **{item['episode']}** · "
                f"Aired {discord_time(item['airing_at'])}"
            )

        fields.append(
            {
                "name": "🔴 Planning — Aired",
                "value": "\n\n".join(text)[:1024],
                "inline": False,
            }
        )

    # =========================================================
    # CURRENTLY WATCHING — UPCOMING
    # =========================================================

    if current_upcoming:
        text = []

        for item in current_upcoming[:MAX_UPCOMING]:
            media = item["media"]
            title = format_title(media)

            text.append(
                f"**{title}**\n"
                f"Episode **{item['episode']}** · "
                f"{discord_time(item['airing_at'])}"
            )

        fields.append(
            {
                "name": "🟢 Currently Watching",
                "value": "\n\n".join(text)[:1024],
                "inline": False,
            }
        )

    # =========================================================
    # PLANNING — UPCOMING
    # =========================================================

    if planning_upcoming:
        text = []

        for item in planning_upcoming[:MAX_PLANNING_UPCOMING]:
            media = item["media"]
            title = format_title(media)

            text.append(
                f"**{title}**\n"
                f"Episode **{item['episode']}** · "
                f"{discord_time(item['airing_at'])}"
            )

        fields.append(
            {
                "name": "📋 Planning — Upcoming",
                "value": "\n\n".join(text)[:1024],
                "inline": False,
            }
        )

    # =========================================================
    # NOTHING FOUND
    # =========================================================

    if not fields:
        fields.append(
            {
                "name": "📺 Schedule",
                "value": "No aired or upcoming episodes found.",
                "inline": False,
            }
        )

    # =========================================================
    # EMBED
    # =========================================================

    embed = {
        "title": "📺 Eldriane's Anime Schedule",
        "description": "AniList → Currently Watching + Planning",
        "fields": fields,
        "footer": {
            "text": "Automatically updated • AniList"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Thumbnail
    for media in current + planning:
        image = media.get("coverImage", {}).get("medium")

        if image:
            embed["thumbnail"] = {
                "url": image
            }
            break

    return embed


def get_existing_message():
    return os.environ.get(
        "DISCORD_MESSAGE_ID",
        ""
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
        f"Discord response status: {response.status_code}"
    )

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2
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
        f"Updating existing Discord message: {message_id}"
    )

    url = f"{WEBHOOK_URL}/messages/{message_id}"

    response = requests.patch(
        url,
        json=payload,
        timeout=30,
    )

    print(
        f"Discord response status: {response.status_code}"
    )

    if response.status_code == 429:
        retry = response.json().get(
            "retry_after",
            2
        )

        print(
            f"Rate limited. Waiting {retry} seconds..."
        )

        time.sleep(float(retry))

        return edit_webhook(
            message_id,
            payload
        )

    if response.status_code == 404:
        print(
            "Existing Discord message was not found."
        )

        return False

    response.raise_for_status()

    return True


def main():
    print(
        f"Getting AniList lists for: {USERNAME}"
    )

    current, planning = get_all_anime()

    print(
        f"Found {len(current)} currently watching anime."
    )

    print(
        f"Found {len(planning)} planning anime."
    )

    embed = build_embed(
        current,
        planning
    )

    payload = {
        "username": "AniList Schedule",
        "embeds": [embed],
        "allowed_mentions": {
            "parse": []
        },
    }

    message_id = get_existing_message()

    # =========================================================
    # UPDATE EXISTING MESSAGE
    # =========================================================

    if message_id:
        success = edit_webhook(
            message_id,
            payload
        )

        if success:
            print(
                f"Updated Discord message: {message_id}"
            )

            print(
                f"DISCORD_MESSAGE_ID={message_id}"
            )

            return

        print(
            "Existing message could not be updated."
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

