"""Minimal YouTube client over plain HTTPS: OAuth for one channel, uploads and analytics.

The credentials are the channel owner's own: an OAuth client created in Google Cloud
(data/youtube_client_secret.json) and the token obtained by signing in once
(data/youtube_token.json). Both stay on this machine.
"""
import asyncio
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
PLAYLISTS_URL = "https://www.googleapis.com/youtube/v3/playlists"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
# Creating playlists and adding videos to them needs the full channel scope.
MANAGE_SCOPE = "https://www.googleapis.com/auth/youtube"
SCOPES = (
    MANAGE_SCOPE,
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)
SECRET_FILE = "youtube_client_secret.json"
TOKEN_FILE = "youtube_token.json"
GAMING_CATEGORY = "20"
PRIVACY_VALUES = ("private", "unlisted", "public")
# Analytics has no data before the channel existed; any early date works as "since always".
ANALYTICS_START = "2020-01-01"
# engagedViews: views that stayed to watch instead of swiping away.
STATS_METRICS = ("views,engagedViews,likes,comments,shares,subscribersGained,averageViewDuration,"
                 "averageViewPercentage")


class YouTubeError(Exception):
    """status: the HTTP status of the failed call; reason: the API's own reason code
    ("quotaExceeded", "playlistNotFound", "videoNotFound"...). Both None when there was no response."""

    def __init__(self, message: str = "", status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status, self.reason = status, reason


class YouTubeNotConnected(YouTubeError):
    """No client secret or no signed-in channel yet."""


class YouTubeClient:
    def __init__(self, data_dir: Path, http_client_factory=httpx.AsyncClient):
        self._data_dir = Path(data_dir)
        self._http = http_client_factory

    # ---- credentials -------------------------------------------------------------------------

    @property
    def secret_path(self) -> Path:
        return self._data_dir / SECRET_FILE

    @property
    def token_path(self) -> Path:
        return self._data_dir / TOKEN_FILE

    def _client_config(self) -> dict:
        try:
            raw = json.loads(self.secret_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise YouTubeNotConnected(f"falta {SECRET_FILE} en la carpeta de datos") from e
        cfg = raw.get("installed") or raw.get("web") or {}
        if not cfg.get("client_id") or not cfg.get("client_secret"):
            raise YouTubeNotConnected(f"{SECRET_FILE} no es un cliente OAuth válido")
        return cfg

    def _token(self) -> dict:
        try:
            return json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise YouTubeNotConnected("el canal de YouTube no está conectado") from e

    def _save_token(self, token: dict) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(token), encoding="utf-8")
        tmp.replace(self.token_path)

    def is_configured(self) -> bool:
        try:
            self._client_config()
            return True
        except YouTubeNotConnected:
            return False

    def is_connected(self) -> bool:
        try:
            return self.is_configured() and bool(self._token().get("refresh_token"))
        except YouTubeNotConnected:
            return False

    def can_manage_playlists(self) -> bool:
        """Whether the owner granted the scope playlists need (connections made before playlists
        existed did not ask for it: the channel has to be connected again)."""
        try:
            return MANAGE_SCOPE in str(self._token().get("scope") or "").split()
        except YouTubeNotConnected:
            return False

    def disconnect(self) -> None:
        self.token_path.unlink(missing_ok=True)

    # ---- OAuth -------------------------------------------------------------------------------

    def auth_url(self, redirect_uri: str, state: str) -> str:
        cfg = self._client_config()
        return AUTH_URL + "?" + urlencode({
            "client_id": cfg["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
            "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": state,
        })

    async def exchange_code(self, code: str, redirect_uri: str) -> None:
        cfg = self._client_config()
        async with self._http() as client:
            resp = await client.post(TOKEN_URL, data={
                "code": code, "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                "redirect_uri": redirect_uri, "grant_type": "authorization_code",
            }, timeout=30)
        data = self._json(resp, "no se pudo completar el inicio de sesión")
        if not data.get("refresh_token"):
            raise YouTubeError("Google no devolvió un refresh token; vuelve a conectar el canal")
        data["expires_at"] = time.time() + float(data.get("expires_in", 0))
        self._save_token(data)

    async def _access_token(self) -> str:
        token = self._token()
        if token.get("access_token") and token.get("expires_at", 0) - 60 > time.time():
            return token["access_token"]
        if not token.get("refresh_token"):
            raise YouTubeNotConnected("el canal de YouTube no está conectado")
        cfg = self._client_config()
        async with self._http() as client:
            resp = await client.post(TOKEN_URL, data={
                "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                "refresh_token": token["refresh_token"], "grant_type": "refresh_token",
            }, timeout=30)
        if resp.status_code in (400, 401):
            # The owner revoked access or the token expired for good: a new sign-in is needed.
            raise YouTubeNotConnected("la conexión con YouTube caducó; vuelve a conectar el canal")
        data = self._json(resp, "no se pudo renovar la sesión de YouTube")
        token.update(access_token=data["access_token"], expires_at=time.time() + float(data.get("expires_in", 0)))
        self._save_token(token)
        return token["access_token"]

    @staticmethod
    def _json(resp: httpx.Response, what: str) -> dict:
        if resp.status_code >= 400:
            reason = None
            try:
                detail = resp.json().get("error")
                if isinstance(detail, dict):
                    errors = detail.get("errors")
                    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                        reason = errors[0].get("reason")
                    detail = detail.get("message")
            except (ValueError, AttributeError):
                detail = resp.text[:200]
            raise YouTubeError(f"{what}: {detail or resp.status_code}", status=resp.status_code, reason=reason)
        return resp.json()

    async def _get(self, url: str, params: dict, what: str) -> dict:
        token = await self._access_token()
        async with self._http() as client:
            resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        return self._json(resp, what)

    async def _post(self, url: str, params: dict, body: dict, what: str) -> dict:
        token = await self._access_token()
        async with self._http() as client:
            resp = await client.post(url, params=params, json=body,
                                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
        return self._json(resp, what)

    # ---- API ---------------------------------------------------------------------------------

    async def channel(self) -> dict:
        data = await self._get(CHANNELS_URL, {"part": "snippet", "mine": "true"}, "no se pudo leer el canal")
        items = data.get("items") or []
        if not items:
            raise YouTubeError("la cuenta conectada no tiene canal de YouTube")
        return {"id": items[0]["id"], "title": items[0]["snippet"]["title"]}

    async def upload_video(self, path: Path, title: str, description: str, tags: list[str],
                           privacy: str = "private", publish_at: datetime | None = None,
                           category_id: str = GAMING_CATEGORY) -> str:
        """Upload a video and return its YouTube id. With publish_at the video stays private until then."""
        if privacy not in PRIVACY_VALUES:
            raise YouTubeError(f"privacidad no válida: {privacy}")
        status: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
        if publish_at is not None:
            status["privacyStatus"] = "private"
            status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {
            "snippet": {"title": title[:100], "description": description[:5000], "tags": tags,
                        "categoryId": category_id, "defaultLanguage": "es", "defaultAudioLanguage": "es"},
            "status": status,
        }
        video = Path(path).read_bytes()
        token = await self._access_token()
        auth = {"Authorization": f"Bearer {token}"}
        async with self._http() as client:
            start = await client.post(
                UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
                headers={**auth, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(video))},
                timeout=60,
            )
            if start.status_code >= 400 or "location" not in start.headers:
                self._json(start, "YouTube rechazó la subida")
                raise YouTubeError("YouTube no devolvió la dirección de subida")
            done = await client.put(start.headers["location"], content=video,
                                    headers={**auth, "Content-Type": "video/mp4"}, timeout=900)
        data = self._json(done, "falló la subida del video")
        if not data.get("id"):
            raise YouTubeError("YouTube no devolvió el id del video")
        return data["id"]

    async def wait_processed(self, video_id: str, timeout: float = 240, every: float = 10) -> bool:
        """Wait until YouTube finishes processing an upload. A cover sent before that may not be
        applied to a Short. False when it is still processing after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            data = await self._get(VIDEOS_URL, {"part": "status", "id": video_id}, "no se pudo leer el estado del video")
            items = data.get("items") or []
            state = (items[0].get("status") or {}).get("uploadStatus") if items else None
            if state == "processed":
                return True
            if state in ("failed", "rejected", "deleted"):
                raise YouTubeError(f"YouTube no procesó el video ({state})")
            if time.monotonic() + every > deadline:
                return False
            await asyncio.sleep(every)

    async def set_thumbnail(self, video_id: str, image: Path) -> None:
        """Set a video's cover. Needs a channel with custom thumbnails enabled (phone-verified)."""
        image = Path(image)
        kind = "image/jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        token = await self._access_token()
        async with self._http() as client:
            resp = await client.post(
                THUMBNAIL_URL, params={"videoId": video_id, "uploadType": "media"}, content=image.read_bytes(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": kind}, timeout=120)
        self._json(resp, "YouTube rechazó la miniatura")

    async def create_playlist(self, title: str, description: str = "") -> str:
        data = await self._post(PLAYLISTS_URL, {"part": "snippet,status"}, {
            "snippet": {"title": title[:150], "description": description[:5000], "defaultLanguage": "es"},
            "status": {"privacyStatus": "public"},
        }, "no se pudo crear la lista de reproducción")
        return data["id"]

    async def add_to_playlist(self, playlist_id: str, video_id: str) -> None:
        await self._post(PLAYLIST_ITEMS_URL, {"part": "snippet"}, {
            "snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}},
        }, "no se pudo añadir el video a la lista")

    async def public_stats(self, video_ids: list[str]) -> dict[str, dict]:
        """The public counters (views, likes, comments) per video id, as shown on YouTube right now.
        Analytics lags a day or two; these do not."""
        result: dict[str, dict] = {}
        for i in range(0, len(video_ids), 50):
            data = await self._get(VIDEOS_URL, {"part": "statistics", "id": ",".join(video_ids[i:i + 50])},
                                   "no se pudieron leer los contadores")
            for item in data.get("items") or []:
                s = item.get("statistics") or {}
                result[item["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                                      "comments": int(s.get("commentCount", 0))}
        return result

    async def video_stats(self, video_ids: list[str]) -> dict[str, dict]:
        """Lifetime totals per video id (ids without data yet are simply absent)."""
        if not video_ids:
            return {}
        data = await self._get(ANALYTICS_URL, {
            "ids": "channel==MINE", "startDate": ANALYTICS_START, "endDate": date.today().isoformat(),
            "metrics": STATS_METRICS, "dimensions": "video", "filters": "video==" + ",".join(video_ids),
        }, "no se pudieron leer las estadísticas")
        names = [h["name"] for h in data.get("columnHeaders", [])]
        return {row[0]: dict(zip(names[1:], row[1:])) for row in data.get("rows") or []}

    async def retention(self, video_id: str) -> list[list[float]]:
        """Audience retention curve: [position in the video 0-1, share of viewers still watching]."""
        data = await self._get(ANALYTICS_URL, {
            "ids": "channel==MINE", "startDate": ANALYTICS_START, "endDate": date.today().isoformat(),
            "metrics": "audienceWatchRatio", "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={video_id}",
        }, "no se pudo leer la retención")
        return [[float(r[0]), float(r[1])] for r in data.get("rows") or []]


MAX_TITLE = 100


class PublishRejected(Exception):
    pass


class ChannelYouTube(YouTubeClient):
    """The channel's own account: its Google application file (youtube_client_secret.json) and its
    session (the token) both live in the channel's data directory."""

    def __init__(self, profile, **kwargs):
        super().__init__(profile.data_dir, **kwargs)
