import json
import os
import sys
import time
from datetime import datetime, timezone

import requests


ANILIST_API = "https://graphql.anilist.co"

USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# How many anime to show in each section.
MAX_AIRED = int(os.getenv("MAX_AIRED", "15"))
MAX_UPCOMING = int(os.getenv("MAX_UPCOMING", "15"))

# Number of days an aired episode remains visible.
AIRED_DAYS = int(os.getenv("AIRED_DAYS", "2"))


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
          status
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


def anilist_query():
    response = requests.post(
        ANILIST_API,
        json={
            "query": QUERY,
            "variables": {
                "userName": USERNAME,
                "status": "CURRENT",
            },
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if "errors" in data:
        raise RuntimeError(json.dumps(data["errors"], indent=2))

    return data["data"]["MediaListCollection"]["lists"]


def discord_request(method, url, payload=None):
    response = requests.request(
        method,
        url,
        json=payload,
        timeout=30,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AniList-Discord-Schedule/1.0",
        },
    )

    # Discord may return 204 for successful PATCH/DELETE requests.
    if response.status_code == 429:
        retry_after = response.json().get("retry_after", 1)
        print(f"Discord rate limited us; waiting {retry_after}s")
        time.sleep(float(retry_after))
        return discord_request(method, url, payload)

    response.raise_for_status()

    if not response.content:
        return None

    return response.json()


def get_entries():
    lists = anilist_query()

    entries = []

    for anime_list in lists:
        for entry in anime_list["entries"]:
            media = entry["media"]

            # Ignore malformed entries.
            if not media:
                continue

            entries.append(media)

    # Remove duplicate media IDs.
    unique = {}
    for media in entries:
        unique[media["id"]] = media

    return list(unique.values())


def discord_timestamp(unix_time):
    return f"<t:{unix_time}:R>"


def title(media):
    return (
        media["title"].get("userPreferred")
        or media["title"].get("english")
        or media["title"].get("romaji")
        or "Unknown Anime"
    )


def build_embed(media):
    now = int(time.time())

    next_ep = media.get("nextAiringEpisode")

    if next_ep:
        next_airing = next_ep["airingAt"]
        next_episode = next_ep["episode"]

        # The episode immediately before the next one is the most
        # recently aired episode according to AniList's airing schedule.
        last_episode = next_episode - 1 if next_episode > 1 else None

        # If the next episode is already technically in the past,
        # don't treat it as upcoming.
        if next_airing <= now:
            next_ep = None
        else:
            return {
                "name": title(media),
                "value": (
                    f"Episode **{next_episode}** · "
                    f"{discord_timestamp(next_airing)}\n"
                    f"[AniList]({media['siteUrl']})"
                ),
                "inline": False,
                "_next": next_airing,
                "_last_episode": last_episode,
                "_last_airing": next_airing,
            }

    return {
        "name": title(media),
        "value": f"[AniList]({media['siteUrl']})",
        "inline": False,
        "_next": None,
        "_last_episode": media.get("episodes"),
        "_last_airing": None,
    }


def build_embed_fields(media_list):
    now = int(time.time())

    upcoming = []
    aired = []

    for media in media_list:
        next_ep = media.get("nextAiringEpisode")

        if next_ep and next_ep["airingAt"] > now:
            upcoming.append(
                {
                    "media": media,
                    "episode": next_ep["episode"],
                    "airingAt": next_ep["airingAt"],
                }
            )

            # Since we know the next episode, the previous episode
            # is the most recently aired episode.
            if next_ep["episode"] > 1:
                aired.append(
                    {
                        "media": media,
                        "episode": next_ep["episode"] - 1,
                        "airingAt": next_ep["airingAt"],
                    }
                )

    # Soonest first.
    upcoming.sort(key=lambda x: x["airingAt"])

    # Most recently advanced shows first.
    aired.sort(
        key=lambda x: (
            x["episode"],
            x["media"]["id"],
        ),
        reverse=True,
    )

    fields = []

    if aired:
        aired_text = []

        for item in aired[:MAX_AIRED]:
            media = item["media"]
            aired_text.append(
                f"**{title(media)}**\n"
                f"Episode **{item['episode']}** · "
                f"next episode {discord_timestamp(item['airingAt'])}"
            )

        fields.append(
            {
                "name": "🔴 Aired / Last Watched",
                "value": "\n\n".join(aired_text)[:1024],
                "inline": False,
            }
        )

    if upcoming:
        upcoming_text = []

        for item in upcoming[:MAX_UPCOMING]:
            media = item["media"]

            upcoming_text.append(
                f"**{title(media)}**\n"
                f"Episode **{item['episode']}** · "
                f"{discord_timestamp(item['airingAt'])}"
            )

        fields.append(
            {
                "name": "🟢 Upcoming",
                "value": "\n\n".join(upcoming_text)[:1024],
                "inline": False,
            }
        )

    if not fields:
        fields.append(
            {
                "name": "📺 Schedule",
                "value": "No upcoming episodes found.",
                "inline": False,
            }
        )

    return fields


def build_payload(media_list):
    now = int(time.time())

    fields = build_embed_fields(media_list)

    embed = {
        "title": f"📺 {USERNAME}'s Anime Schedule",
        "description": (
            "Episodes from my **AniList → Currently Watching** list."
        ),
        "fields": fields,
        "footer": {
            "text": "AniList • Automatically updated"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Use the first anime with a cover image as the thumbnail.
    for media in media_list:
        image = media.get("coverImage", {}).get("medium")
        if image:
            embed["thumbnail"] = {"url": image}
            break

    return {
        "username": "AniList Schedule",
        "embeds": [embed],
        "allowed_mentions": {
            "parse": []
        },
    }


def create_message(payload):
    # ?wait=true makes Discord return the created message object,
    # allowing us to save its ID for future PATCH requests.
    url = WEBHOOK_URL + ("&" if "?" in WEBHOOK_URL else "?") + "wait=true"

    message = discord_request("POST", url, payload)

    if not message or "id" not in message:
        raise RuntimeError("Discord did not return a message ID.")

    return message["id"]


def update_message(message_id, payload):
    url = WEBHOOK_URL + f"/messages/{message_id}"
    discord_request("PATCH", url, payload)


def main():
    print(f"Updating AniList schedule for {USERNAME}")

    media = get_entries()

    print(f"Found {len(media)} anime in CURRENT list.")

    payload = build_payload(media)

    message_id = os.getenv("DISCORD_MESSAGE_ID", "").strip()

    if message_id:
        print(f"Updating Discord message {message_id}")
        update_message(message_id, payload)
        return message_id

    print("No Discord message ID found. Creating initial message...")
    message_id = create_message(payload)

    print(f"Created Discord message: {message_id}")

    return message_id


if __name__ == "__main__":
    try:
        message_id = main()
        print(f"DISCORD_MESSAGE_ID={message_id}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)