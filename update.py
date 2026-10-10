
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

ANILIST_API = "https://graphql.anilist.co"
USERNAME = os.environ["ANILIST_USERNAME"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].rstrip("/")
DISPLAY_TIMEZONE = os.environ.get(
    "DISPLAY_TIMEZONE", "Pacific/Honolulu"
)

# Discord's combined embed-text limit is 6000 per message.
# Use a lower limit to leave room for safety.
MAX_MESSAGE_TEXT = 5400
MAX_DESCRIPTION_LENGTH = 3000
MAX_EMBEDS_PER_MESSAGE = 10
MESSAGE_IDS_FILE = "discord_message_ids.json"

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
          coverImage { medium }
          nextAiringEpisode {
            airingAt
            episode
            timeUntilAiring
          }
          airingSchedule(notYetAired: false, perPage: 25) {
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
        print(f"Invalid timezone {DISPLAY_TIMEZONE!r}; using UTC.")
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
    print(f"AniList response status: {response.status_code}")
    response.raise_for_status()

    data = response.json()
    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    lists = data["data"]["MediaListCollection"]["lists"]
    unique = {}

    for anime_list in lists:
        for entry in anime_list["entries"]:
            media = entry.get("media")
            if media:
                unique[media["id"]] = media

    return list(unique.values())


def anime_title(media):
    title = media.get("title") or {}
    return (
        title.get("userPreferred")
        or title.get("english")
        or title.get("romaji")
        or "Unknown Anime"
    )


def format_title(media):
    title = anime_title(media)
    url = media.get("siteUrl")
    return f"[{title}]({url})" if url else title


def is_today(timestamp, tz):
    return (
        datetime.fromtimestamp(timestamp, tz).date()
        == datetime.now(tz).date()
    )


def get_aired_today(planning, now):
    tz = get_timezone()
    results = []

    for media in planning:
        schedule = media.get("airingSchedule") or {}
        for episode in schedule.get("nodes") or []:
            aired_at = episode.get("airingAt")
            number = episode.get("episode")

            if (
                aired_at
                and number
                and aired_at <= now
                and is_today(aired_at, tz)
            ):
                results.append({
                    "media": media,
                    "episode": number,
                    "airing_at": aired_at,
                })

    return sorted(
        results,
        key=lambda item: item["airing_at"],
        reverse=True,
    )


def get_upcoming(planning, now):
    results = []
    next_24_hours = now + (24 * 60 * 60)

    for media in planning:
        episode = media.get("nextAiringEpisode")
        if not episode:
            continue

        aired_at = episode.get("airingAt")
        number = episode.get("episode")

        if (
            aired_at
            and number
            and now < aired_at <= next_24_hours
        ):
            results.append({
                "media": media,
                "episode": number,
                "airing_at": aired_at,
            })

    return sorted(results, key=lambda item: item["airing_at"])

def make_entry(item):
    return (
        f"**{format_title(item['media'])}**\n"
        f"Episode **{item['episode']}** · "
        f"<t:{item['airing_at']}:R>"
    )


def split_entries(entries):
    groups = []
    current = []
    length = 0

    for entry in entries:
        extra = len(entry) + (2 if current else 0)

        if current and length + extra > MAX_DESCRIPTION_LENGTH:
            groups.append(current)
            current = []
            length = 0
            extra = len(entry)

        if len(entry) > MAX_DESCRIPTION_LENGTH:
            entry = entry[:MAX_DESCRIPTION_LENGTH - 1] + "…"
            extra = len(entry) + (2 if current else 0)

        current.append(entry)
        length += extra

    if current:
        groups.append(current)

    return groups


def build_embeds(title, items, empty_text):
    entries = [make_entry(item) for item in items]
    if not entries:
        entries = [empty_text]

    groups = split_entries(entries)
    embeds = []
    item_index = 0
    timestamp = datetime.now(timezone.utc).isoformat()

    for index, group in enumerate(groups, start=1):
        embed_title = (
            title if len(groups) == 1
            else f"{title} — Part {index}"
        )

        embed = {
            "title": embed_title,
            "description": "\n\n".join(group),
            "footer": {"text": "Automatically updated • AniList"},
            "timestamp": timestamp,
        }

        if items and item_index < len(items):
            media = items[item_index]["media"]
            image = (media.get("coverImage") or {}).get("medium")
            if image:
                embed["thumbnail"] = {"url": image}

        embeds.append(embed)
        item_index += len(group)

    return embeds


def embed_text_size(embed):
    size = len(embed.get("title", ""))
    size += len(embed.get("description", ""))
    size += len((embed.get("footer") or {}).get("text", ""))
    size += len((embed.get("author") or {}).get("name", ""))

    for field in embed.get("fields") or []:
        size += len(field.get("name", ""))
        size += len(field.get("value", ""))

    return size


def pack_messages(embeds):
    messages = []
    current = []
    current_size = 0

    for embed in embeds:
        size = embed_text_size(embed)

        if size > MAX_MESSAGE_TEXT:
            raise ValueError(
                f"Single embed exceeds safe limit: {size} characters"
            )

        if current and (
            current_size + size > MAX_MESSAGE_TEXT
            or len(current) >= MAX_EMBEDS_PER_MESSAGE
        ):
            messages.append(make_payload(current))
            current = []
            current_size = 0

        current.append(embed)
        current_size += size

    if current:
        messages.append(make_payload(current))

    return messages


def make_payload(embeds):
    return {
        "username": "AniList Schedule",
        "embeds": embeds,
        "allowed_mentions": {"parse": []},
    }


def request_discord(method, url, **kwargs):
    for attempt in range(6):
        response = requests.request(
            method, url, timeout=30, **kwargs
        )

        if response.status_code != 429:
            return response

        try:
            delay = float(response.json().get("retry_after", 2))
        except (ValueError, TypeError):
            delay = 2

        print(f"Discord rate limited; waiting {delay} seconds.")
        time.sleep(min(max(delay, 1), 60))

    raise RuntimeError("Discord rate-limit retries exhausted.")


def load_message_ids():
    try:
        with open(MESSAGE_IDS_FILE, encoding="utf-8") as file:
            return json.load(file).get("message_ids", [])
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not read message IDs: {error}")
        return []


def save_message_ids(message_ids):
    temporary = MESSAGE_IDS_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump({"message_ids": message_ids}, file, indent=2)
    os.replace(temporary, MESSAGE_IDS_FILE)


def send_message(payload):
    separator = "&" if "?" in WEBHOOK_URL else "?"
    url = WEBHOOK_URL + separator + "wait=true"

    response = request_discord("POST", url, json=payload)
    if not response.ok:
        print("Discord error:", response.text)
    response.raise_for_status()
    return response.json()["id"]


def edit_message(message_id, payload):
    url = f"{WEBHOOK_URL}/messages/{message_id}"
    response = request_discord("PATCH", url, json=payload)

    if response.status_code == 404:
        return False

    if not response.ok:
        print("Discord error:", response.text)
    response.raise_for_status()
    return True


def delete_message(message_id):
    url = f"{WEBHOOK_URL}/messages/{message_id}"
    response = request_discord("DELETE", url)

    if response.status_code in (200, 204, 404):
        return

    if not response.ok:
        print("Could not delete old message:", response.text)
    response.raise_for_status()


def publish_messages(payloads):
    old_ids = load_message_ids()
    new_ids = []

    for index, payload in enumerate(payloads):
        if index < len(old_ids):
            message_id = str(old_ids[index])
            print(f"Updating message {index + 1}: {message_id}")

            if edit_message(message_id, payload):
                new_ids.append(message_id)
                continue

            print("Old message not found; creating replacement.")

        message_id = str(send_message(payload))
        print(f"Created message {index + 1}: {message_id}")
        new_ids.append(message_id)

    # Remove old schedule messages no longer needed.
    for message_id in old_ids[len(payloads):]:
        print(f"Deleting surplus schedule message: {message_id}")
        delete_message(str(message_id))

    save_message_ids(new_ids)
    print(f"Saved {len(new_ids)} message IDs.")


def main():
    print("=" * 48)
    print("AniList Discord Schedule")
    print("=" * 48)
    print(f"Username: {USERNAME}")
    print(f"Timezone: {DISPLAY_TIMEZONE}")

    planning = get_anime("PLANNING")
    now = int(time.time())

    aired = get_aired_today(planning, now)
    upcoming = get_upcoming(planning, now)

    print(f"Found {len(planning)} planning anime.")
    print(f"Aired today: {len(aired)}")
    print(f"Upcoming: {len(upcoming)}")

    embeds = (
        build_embeds(
            "🔴 Aired Recently",
            aired,
            "No episodes aired today.",
        )
        + build_embeds(
            "🟢 Upcoming Episodes",
            upcoming,
            "No episodes airing in the next 24 hours.",
        )
    )

    payloads = pack_messages(embeds)
    print(f"Built {len(embeds)} embeds across {len(payloads)} messages.")

    for index, payload in enumerate(payloads, start=1):
        size = sum(embed_text_size(e) for e in payload["embeds"])
        print(
            f"Message {index}: {len(payload['embeds'])} embeds, "
            f"{size}/{MAX_MESSAGE_TEXT} characters"
        )

    publish_messages(payloads)
    print("Schedule updated successfully.")


if __name__ == "__main__":
    main()
