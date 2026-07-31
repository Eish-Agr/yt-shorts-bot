"""
upload/youtube.py — YouTube Data API v3 uploader
Handles OAuth2 auth, video upload, thumbnail set, and metadata.

SETUP (one-time, ~5 minutes):
1. Go to https://console.cloud.google.com
2. Create project → Enable "YouTube Data API v3"
3. Create credentials → OAuth 2.0 Client ID → Desktop app
4. Download JSON → save as ./config/client_secrets.json
5. Run: python -m src.upload.youtube --auth
   → Opens browser, sign in, approve, token saved automatically.

Free quota: 10,000 units/day
  - Upload:    1,600 units
  - Thumbnail: 50 units
  - You can upload ~6 videos/day on free quota
"""
import os, json, time, pickle
from pathlib import Path
from typing import Optional, Dict, List
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

CLIENT_SECRETS = os.getenv("YOUTUBE_CLIENT_SECRETS", "./config/client_secrets.json")
TOKEN_FILE     = os.getenv("YOUTUBE_TOKEN_FILE",     "./config/youtube_token.json")
CATEGORY_ID    = os.getenv("YT_CATEGORY_ID", "28")     # 28 = Science & Technology
PRIVACY        = os.getenv("YT_PRIVACY", "public")
MADE_FOR_KIDS  = os.getenv("YT_MADE_FOR_KIDS", "false").lower() == "true"
DEFAULT_TAGS   = os.getenv("YT_DEFAULT_TAGS",
                            "shorts,trending,viral,facts").split(",")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

CHUNK_SIZE = 1024 * 1024  # 1 MB upload chunks


# ──────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────

def get_authenticated_service():
    """
    Build and return authenticated YouTube API service.
    Loads saved token if available; otherwise runs browser auth flow.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_path = Path(TOKEN_FILE)

    # Load existing token
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning(f"[youtube_auth] Token load error: {e}")

    # Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("[youtube_auth] Token refreshed")
            except Exception as e:
                logger.warning(f"[youtube_auth] Refresh failed: {e}, re-authenticating")
                creds = None

        if not creds:
            if not Path(CLIENT_SECRETS).exists():
                raise FileNotFoundError(
                    f"client_secrets.json not found at {CLIENT_SECRETS}\n"
                    "Download from: console.cloud.google.com → APIs → Credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS, SCOPES
            )
            # Run local server for OAuth callback
            creds = flow.run_local_server(port=8080, open_browser=True)
            logger.info("[youtube_auth] New token obtained")

        # Save token
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        logger.info(f"[youtube_auth] Token saved to {token_path}")

    return build("youtube", "v3", credentials=creds)


# ──────────────────────────────────────────────
# METADATA BUILDER
# ──────────────────────────────────────────────

def build_video_metadata(
    title: str,
    description: str,
    tags: List[str],
    category_id: str = CATEGORY_ID,
    privacy: str = PRIVACY,
) -> Dict:
    """Build the YouTube API request body for video insert."""
    # YouTube Shorts: title must contain #Shorts OR be ≤60 chars vertical video
    if "#shorts" not in title.lower() and "#Shorts" not in title:
        title = title[:95] + " #Shorts" if len(title) > 95 else title + " #Shorts"

    # Limit title to 100 chars
    title = title[:100]

    # Tags: max 500 chars total, each tag max 30 chars
    clean_tags = []
    total_len = 0
    for tag in (DEFAULT_TAGS + tags):
        tag = tag.strip().lstrip("#")[:30]
        if tag and (total_len + len(tag)) < 490:
            clean_tags.append(tag)
            total_len += len(tag) + 1

    return {
        "snippet": {
            "title": title,
            "description": description[:4900],   # YouTube limit: 5000 chars
            "tags": clean_tags,
            "categoryId": category_id,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": MADE_FOR_KIDS,
            "madeForKids": MADE_FOR_KIDS,
        },
    }


# ──────────────────────────────────────────────
# UPLOADER
# ──────────────────────────────────────────────

class YouTubeUploader:
    def __init__(self):
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = get_authenticated_service()
        return self._service

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str],
        thumbnail_path: Optional[str] = None,
        category_id: str = CATEGORY_ID,
        privacy: str = PRIVACY,
        notify_subscribers: bool = True,
    ) -> Optional[str]:
        """
        Upload a video to YouTube.
        Returns YouTube video ID on success, None on failure.
        """
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        if not os.path.exists(video_path):
            logger.error(f"[youtube] Video not found: {video_path}")
            return None

        metadata = build_video_metadata(title, description, tags,
                                         category_id, privacy)

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            chunksize=CHUNK_SIZE,
            resumable=True,
        )

        logger.info(f"[youtube] Uploading: {title[:60]}")
        logger.info(f"[youtube] File: {video_path} "
                    f"({os.path.getsize(video_path)/1_048_576:.1f} MB)")

        request = self.service.videos().insert(
            part=",".join(metadata.keys()),
            body=metadata,
            media_body=media,
        )

        video_id = None
        retry = 0
        max_retries = 5

        while True:
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    if pct % 20 == 0:
                        logger.info(f"[youtube] Upload progress: {pct}%")
                if response is not None:
                    video_id = response.get("id")
                    logger.info(f"[youtube] ✅ Upload complete! Video ID: {video_id}")
                    logger.info(f"[youtube] URL: https://youtu.be/{video_id}")
                    break

            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504] and retry < max_retries:
                    retry += 1
                    wait = 2 ** retry
                    logger.warning(f"[youtube] HTTP {e.resp.status} — retry {retry}/{max_retries} in {wait}s")
                    time.sleep(wait)
                elif e.resp.status == 403:
                    logger.error("[youtube] 403 Forbidden — quota exceeded or auth issue")
                    return None
                else:
                    logger.error(f"[youtube] Upload failed: {e}")
                    return None
            except Exception as e:
                logger.error(f"[youtube] Unexpected error: {e}")
                return None

        # Set thumbnail
        if video_id and thumbnail_path and os.path.exists(thumbnail_path):
            self.set_thumbnail(video_id, thumbnail_path)

        return video_id

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Set a custom thumbnail for an uploaded video."""
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        try:
            media = MediaFileUpload(
                thumbnail_path,
                mimetype="image/jpeg",
            )
            self.service.thumbnails().set(
                videoId=video_id,
                media_body=media,
            ).execute()
            logger.info(f"[youtube] Thumbnail set for {video_id}")
            return True
        except HttpError as e:
            logger.warning(f"[youtube] Thumbnail set failed: {e}")
            return False

    def get_video_stats(self, video_id: str) -> Optional[Dict]:
        """Fetch view/like/comment stats for an uploaded video."""
        from googleapiclient.errors import HttpError
        try:
            resp = self.service.videos().list(
                part="statistics,snippet",
                id=video_id,
            ).execute()
            items = resp.get("items", [])
            if not items:
                return None
            item = items[0]
            stats = item.get("statistics", {})
            return {
                "video_id": video_id,
                "title": item["snippet"]["title"],
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except HttpError as e:
            logger.error(f"[youtube] Stats fetch failed: {e}")
            return None

    def list_recent_uploads(self, max_results: int = 10) -> List[Dict]:
        """List recent uploads from the channel."""
        from googleapiclient.errors import HttpError
        try:
            channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
            resp = self.service.search().list(
                part="snippet",
                forMine=True,
                type="video",
                order="date",
                maxResults=max_results,
            ).execute()
            return [
                {
                    "video_id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "published": item["snippet"]["publishedAt"],
                }
                for item in resp.get("items", [])
            ]
        except HttpError as e:
            logger.error(f"[youtube] List failed: {e}")
            return []


# ──────────────────────────────────────────────
# CLI: run --auth to authenticate
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if "--auth" in sys.argv:
        print("Starting OAuth2 authentication...")
        svc = get_authenticated_service()
        print("✅ Authentication successful! Token saved.")
        # Test: list channel info
        try:
            resp = svc.channels().list(part="snippet", mine=True).execute()
            items = resp.get("items", [])
            if items:
                print(f"Channel: {items[0]['snippet']['title']}")
        except Exception as e:
            print(f"Auth OK but channel fetch failed: {e}")
    else:
        print("Usage: python -m src.upload.youtube --auth")
