
import os
import time
from datetime import datetime, timezone

import requests

ANILIST_API = "https://graphql.anilist.co"

USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

MAX_UPCOMING = 15
MAX_PLANNING_Aired = 15
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


def discord_time(timestamp):
    return f"<t:{timestamp}:R>"


def format_title(media):
    title = anime_title(media)

    if media.get("siteUrl"):
        return f"[{title}]({media['siteUrl']})"

    return title


def build_embed(current, planning):
    now = int(time.time())

    current_upcoming = []
    planning_upcoming = []
    planning_aired = []

    # ---------------------------------------------------------
    # CURRENTLY WATCHING
    # Only show future episodes.
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # PLANNING
    #
    # Upcoming:
    # Show the next future episode.
    #
    # Aired:
    # Show the episode immediately before the next airing episode.
    # ---------------------------------------------------------

    for media in planning:
        next_episode = media.get("nextAiringEpisode")

        if not next_episode:
            continue

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

            # If the next episode is episode 2 or later,
            # the previous episode has already aired.
            if episode > 1:
                planning_aired.append(
                    {
                        "media": media,
                        "episode": episode - 1,
                        "next_airing_at": airing_at,
                    }
                )

    # Sort current watching by next airing time
    current_upcoming.sort(
        key=lambda x: x["airing_at"]
    )

    # Most recently aired planning episodes first
    planning_aired.sort(
        key=lambda x: x["next_airing_at"],
        reverse=True,
    )

    # Soonest planning episodes first
    planning_upcoming.sort(
        key=lambda x: x["airing_at"]
    )

    fields = []

    # ---------------------------------------------------------
    # PLANNING — AIRED
    # ---------------------------------------------------------

    if planning_aired:
        text = []

        for item in planning_aired[:MAX_PLANNING_Aired]:
            media = item["media"]
            title = format_title(media)

            text.append(
                f"**{title}**\n"
                f"Episode **{item['episode']}** · "
                f"Next episode {discord_time(item['next_airing_at'])}"
            )

        fields.append(
            {
                "name": "🔴 Planning — Aired",
                "value": "\n\n".join(text)[:1024],
                "inline": False,
            }
        )

    # ---------------------------------------------------------
    # CURRENTLY WATCHING — UPCOMING
    # ---------------------------------------------------------

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
                "name": "🟢 Upcoming",
                "value": "\n\n".join(text)[:1024],
                "inline": False,
            }
        )

    # ---------------------------------------------------------
    # PLANNING — UPCOMING
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # NOTHING FOUND
    # ---------------------------------------------------------

    if not fields:
        fields.append(
            {
                "name": "📺 Schedule",
                "value": "No aired or upcoming episodes found.",
                "inline": False,
            }
        )

    # ---------------------------------------------------------
    # EMBED
    # ---------------------------------------------------------

    embed = {
        "title": f"📺 {USERNAME}'s Anime Schedule",
        "description": "AniList → Currently Watching + Planning",
        "fields": fields,
        "footer": {
            "text": "Automatically updated • AniList"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Add a thumbnail from the first available anime
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

    print(f"Discord response status: {response.status_code}")

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

    # ---------------------------------------------------------
    # UPDATE EXISTING MESSAGE
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # CREATE NEW MESSAGE
    # ---------------------------------------------------------

    message = send_webhook(payload)

    message_id = message["id"]

    print(
        f"Created message: {message_id}"
    )

    print(
        f"DISCORD_MESSAGE_ID={message_id}"
    )


# IMPORTANT:
# This starts the script when GitHub Actions runs:
# python update.py
if __name__ == "__main__":
    main()

