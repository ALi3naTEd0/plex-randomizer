import flet as ft
import requests
import xml.etree.ElementTree as ET
import random
from typing import Optional, List, Dict
import re
from urllib.parse import urlparse
import urllib3
from config import get_config, save_config as save_app_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1x1 transparent PNG used when no movie thumbnail is available.
TRANSPARENT_PIXEL_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/w8AAusB9Y9z8f4AAAAASUVORK5CYII="
)


def extract_token_from_text(text: str) -> Optional[str]:
    """Extract X-Plex-Token value from a URL or raw text."""
    if not text:
        return None

    match = re.search(r"(?:\?|&)X-Plex-Token=([^&\s]+)", text)
    if match:
        return match.group(1).strip()

    return None


def extract_server_from_url(text: str) -> Optional[str]:
    """Extract Plex server base URL from a full request URL."""
    if not text:
        return None

    try:
        parsed = urlparse(text.strip())
        if not parsed.scheme or not parsed.netloc:
            return None
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        return normalize_plex_url(base_url)
    except Exception:
        return None


def normalize_token(raw_token: str) -> str:
    """Allow users to paste full token fragments like X-Plex-Token=abc123."""
    cleaned = (raw_token or "").strip()
    match = re.search(r"(?:^|[?&])X-Plex-Token=([^&\s]+)", cleaned)
    if match:
        return match.group(1).strip()
    return cleaned


def build_candidate_urls(url: str) -> List[str]:
    """Build candidate base URLs trying both HTTP and HTTPS for manual IP input."""
    cleaned = normalize_plex_url(url)
    parsed = urlparse(cleaned)

    if not parsed.hostname:
        return [cleaned]

    host = parsed.hostname
    port = parsed.port or 32400

    if parsed.scheme == "https":
        schemes = ["https", "http"]
    elif parsed.scheme == "http":
        schemes = ["http", "https"]
    else:
        schemes = ["http", "https"]

    return [f"{scheme}://{host}:{port}" for scheme in schemes]


def normalize_plex_url(url: str) -> str:
    """Normalize user/server URL, including plex.direct hostnames."""
    cleaned = url.strip().rstrip("/")
    if not cleaned.startswith("http"):
        cleaned = "http://" + cleaned

    try:
        parsed = urlparse(cleaned)
        hostname = parsed.hostname or ""
        port = parsed.port or 32400

        # Example: 10-0-220-110.<hash>.plex.direct -> http://10.0.220.110:32400
        if hostname.endswith(".plex.direct"):
            match = re.match(r"^(\d{1,3}(?:-\d{1,3}){3})\.", hostname)
            if match:
                ip = match.group(1).replace("-", ".")
                return f"http://{ip}:{port}"

        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return cleaned

class PlexRandomizer:
    def __init__(self):
        self.plex_url: Optional[str] = None
        self.plex_token: Optional[str] = None
        self.section_id: Optional[str] = None
        self.server_id: Optional[str] = None
        self.verify_ssl: bool = True
        self.last_error: str = ""
        self.movies: List[Dict] = []
        self.movie_history: List[Dict] = []
        self.current_history_index: int = -1
        
    def set_config(self, url: str, token: str, section_id: str) -> bool:
        """Validate and set Plex configuration"""
        token = normalize_token(token)
        candidates = build_candidate_urls(url)
        errors: List[str] = []

        for base_url in candidates:
            use_verify = not base_url.startswith("https://")
            try:
                response = requests.get(
                    f"{base_url}/identity",
                    params={"X-Plex-Token": token},
                    timeout=8,
                    verify=use_verify,
                )
                response.raise_for_status()

                # Parse server ID
                root = ET.fromstring(response.content)
                self.server_id = root.get("machineIdentifier")

                self.plex_url = base_url
                self.plex_token = token
                self.section_id = section_id
                self.verify_ssl = use_verify
                self.last_error = ""
                return True
            except Exception as e:
                errors.append(f"{base_url} -> {e}")

        self.last_error = errors[0] if errors else "Could not connect to Plex server"
        print(f"Configuration error: {self.last_error}")
        return False
    
    def fetch_movies(self) -> bool:
        """Fetch all movies from Plex library"""
        if not self.plex_url or not self.plex_token:
            return False
        
        try:
            url = f"{self.plex_url}/library/sections/{self.section_id}/all?X-Plex-Token={self.plex_token}"
            response = requests.get(url, timeout=12, verify=self.verify_ssl)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            self.movies = []

            def normalize_resolution_label(media_node: ET.Element) -> str:
                resolution = (media_node.get("videoResolution") or "").lower()
                if resolution:
                    if resolution == "4k":
                        return "2160p"
                    if resolution == "2k":
                        return "1440p"
                    if resolution.endswith("p"):
                        return resolution
                    if resolution.isdigit():
                        return f"{resolution}p"

                try:
                    height = int(media_node.get("height") or 0)
                    if height >= 2160:
                        return "2160p"
                    if height >= 1440:
                        return "1440p"
                    if height >= 1080:
                        return "1080p"
                    if height >= 720:
                        return "720p"
                    if height >= 480:
                        return "480p"
                except ValueError:
                    pass

                return "Unknown"

            def detect_dynamic_range(media_node: ET.Element, video_stream: Optional[ET.Element]) -> str:
                if video_stream is None:
                    return ""

                text_blob = " ".join(
                    [
                        video_stream.get("extendedDisplayTitle") or "",
                        video_stream.get("displayTitle") or "",
                        video_stream.get("title") or "",
                        video_stream.get("colorTrc") or "",
                        media_node.get("videoProfile") or "",
                        media_node.get("videoDynamicRange") or "",
                    ]
                ).lower()

                tags: List[str] = []
                has_dv = (
                    video_stream.get("DOVIPresent") == "1"
                    or "dolby vision" in text_blob
                    or "dovi" in text_blob
                )
                if has_dv:
                    tags.append("DV")

                if "hdr10+" in text_blob:
                    tags.append("HDR10+")
                elif "hdr10" in text_blob:
                    tags.append("HDR10")
                elif "hdr" in text_blob or "hlg" in text_blob or "pq" in text_blob:
                    tags.append("HDR")

                return "/".join(tags)

            def build_media_details(video_node: ET.Element) -> Dict[str, str]:
                media = video_node.find("./Media")
                if media is None:
                    return {
                        "quality": "Unknown",
                        "audio": "Unknown",
                    }

                part = media.find("./Part")
                video_streams = part.findall("./Stream[@streamType='1']") if part is not None else []
                audio_streams = part.findall("./Stream[@streamType='2']") if part is not None else []

                selected_video = next((s for s in video_streams if s.get("selected") == "1"), None)
                if selected_video is None and video_streams:
                    selected_video = video_streams[0]

                selected_audio = next((s for s in audio_streams if s.get("selected") == "1"), None)
                if selected_audio is None and audio_streams:
                    selected_audio = audio_streams[0]

                quality_parts: List[str] = []
                quality_parts.append(normalize_resolution_label(media))

                video_codec = (media.get("videoCodec") or "").upper()
                if video_codec:
                    quality_parts.append(video_codec)

                dynamic_range = detect_dynamic_range(media, selected_video)
                if dynamic_range:
                    quality_parts.append(dynamic_range)

                bitrate = media.get("bitrate")
                if bitrate:
                    try:
                        mbps = max(1, round(int(bitrate) / 1000))
                        quality_parts.append(f"{mbps} Mbps")
                    except ValueError:
                        pass

                audio_codec = (
                    (selected_audio.get("codec") if selected_audio is not None else None)
                    or media.get("audioCodec")
                    or ""
                )
                audio_channels = (
                    (selected_audio.get("channels") if selected_audio is not None else None)
                    or media.get("audioChannels")
                    or ""
                )
                audio_language = (
                    selected_audio.get("language") if selected_audio is not None else None
                ) or ""

                audio_parts: List[str] = []
                if audio_codec:
                    audio_parts.append(audio_codec.upper())
                if audio_channels:
                    audio_parts.append(f"{audio_channels}ch")
                if audio_language:
                    audio_parts.append(audio_language)
                audio_label = " • ".join(audio_parts) if audio_parts else "Unknown"

                quality_label = " • ".join([p for p in quality_parts if p and p != "Unknown"])
                if not quality_label:
                    quality_label = "Unknown"

                return {
                    "quality": quality_label,
                    "audio": audio_label,
                }
            
            for video in root.findall('.//Video'):
                media_details = build_media_details(video)
                movie = {
                    'title': video.get('title', 'Unknown'),
                    'year': video.get('year', 'Unknown'),
                    'duration': int(video.get('duration', 0)) // 60000,
                    'key': video.get('ratingKey'),
                    'thumb': video.get('thumb'),
                    'rating': video.get('rating', 'N/A'),
                    'summary': video.get('summary', ''),
                    'quality': media_details['quality'],
                    'audio': media_details['audio'],
                    'details_loaded': False,
                }
                self.movies.append(movie)
            
            return len(self.movies) > 0
        except Exception as e:
            self.last_error = str(e)
            print(f"Fetch movies error: {e}")
            return False

    def enrich_movie_media_details(self, movie: Dict) -> None:
        """Fetch detailed metadata for a movie to improve quality/HDR/audio fields."""
        if not self.plex_url or not self.plex_token:
            return
        if not movie.get("key"):
            return

        try:
            url = f"{self.plex_url}/library/metadata/{movie['key']}?X-Plex-Token={self.plex_token}"
            response = requests.get(url, timeout=10, verify=self.verify_ssl)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            video = root.find(".//Video")
            if video is None:
                movie["details_loaded"] = True
                return

            media = video.find("./Media")
            if media is None:
                movie["details_loaded"] = True
                return

            resolution = (media.get("videoResolution") or "").lower()
            if resolution == "4k":
                resolution_label = "2160p"
            elif resolution == "2k":
                resolution_label = "1440p"
            elif resolution.endswith("p"):
                resolution_label = resolution
            elif resolution.isdigit():
                resolution_label = f"{resolution}p"
            else:
                try:
                    height = int(media.get("height") or 0)
                    if height >= 2160:
                        resolution_label = "2160p"
                    elif height >= 1440:
                        resolution_label = "1440p"
                    elif height >= 1080:
                        resolution_label = "1080p"
                    elif height >= 720:
                        resolution_label = "720p"
                    elif height >= 480:
                        resolution_label = "480p"
                    else:
                        resolution_label = "Unknown"
                except ValueError:
                    resolution_label = "Unknown"

            part = media.find("./Part")
            video_streams = part.findall("./Stream[@streamType='1']") if part is not None else []
            audio_streams = part.findall("./Stream[@streamType='2']") if part is not None else []
            selected_video = next((s for s in video_streams if s.get("selected") == "1"), None)
            if selected_video is None and video_streams:
                selected_video = video_streams[0]
            selected_audio = next((s for s in audio_streams if s.get("selected") == "1"), None)
            if selected_audio is None and audio_streams:
                selected_audio = audio_streams[0]

            text_blob = " ".join(
                [
                    (selected_video.get("extendedDisplayTitle") if selected_video is not None else "") or "",
                    (selected_video.get("displayTitle") if selected_video is not None else "") or "",
                    (selected_video.get("title") if selected_video is not None else "") or "",
                    (selected_video.get("colorTrc") if selected_video is not None else "") or "",
                    media.get("videoProfile") or "",
                    media.get("videoDynamicRange") or "",
                ]
            ).lower()

            dynamic_tags: List[str] = []
            has_dv = (
                (selected_video is not None and selected_video.get("DOVIPresent") == "1")
                or "dolby vision" in text_blob
                or "dovi" in text_blob
            )
            if has_dv:
                dynamic_tags.append("DV")

            if "hdr10+" in text_blob:
                dynamic_tags.append("HDR10+")
            elif "hdr10" in text_blob:
                dynamic_tags.append("HDR10")
            elif "hdr" in text_blob or "hlg" in text_blob or "pq" in text_blob:
                dynamic_tags.append("HDR")

            dynamic_range = "/".join(dynamic_tags)

            quality_parts: List[str] = [resolution_label]
            video_codec = (media.get("videoCodec") or "").upper()
            if video_codec:
                quality_parts.append(video_codec)
            if dynamic_range:
                quality_parts.append(dynamic_range)
            bitrate = media.get("bitrate")
            if bitrate:
                try:
                    mbps = max(1, round(int(bitrate) / 1000))
                    quality_parts.append(f"{mbps} Mbps")
                except ValueError:
                    pass
            movie["quality"] = " • ".join([p for p in quality_parts if p and p != "Unknown"]) or "Unknown"

            audio_codec = (
                (selected_audio.get("codec") if selected_audio is not None else None)
                or media.get("audioCodec")
                or ""
            )
            audio_channels = (
                (selected_audio.get("channels") if selected_audio is not None else None)
                or media.get("audioChannels")
                or ""
            )
            audio_language = (
                selected_audio.get("language") if selected_audio is not None else None
            ) or ""
            audio_parts: List[str] = []
            if audio_codec:
                audio_parts.append(audio_codec.upper())
            if audio_channels:
                audio_parts.append(f"{audio_channels}ch")
            if audio_language:
                audio_parts.append(audio_language)
            movie["audio"] = " • ".join(audio_parts) if audio_parts else "Unknown"
            movie["details_loaded"] = True
        except Exception:
            movie["details_loaded"] = True
    
    def get_random_movie(self) -> Optional[Dict]:
        """Get a random movie from the library"""
        if not self.movies:
            return None
        
        random_movie = random.choice(self.movies)
        
        # Add to history
        if self.current_history_index < len(self.movie_history) - 1:
            self.movie_history = self.movie_history[:self.current_history_index + 1]
        
        self.movie_history.append(random_movie)
        self.current_history_index = len(self.movie_history) - 1
        
        return random_movie
    
    def get_movie_url(self, movie_key: str) -> str:
        """Generate Plex movie URL"""
        return f"{self.plex_url}/web/index.html#!/server/{self.server_id}/details?key=%2Flibrary%2Fmetadata%2F{movie_key}"
    
    def get_imdb_url(self, title: str, year: str) -> str:
        """Generate IMDb search URL"""
        return f"https://www.imdb.com/find?q={requests.utils.quote(title + ' ' + str(year))}&s=tt"
    
    def get_thumb_url(self, thumb_path: str) -> str:
        """Generate thumbnail URL"""
        if not thumb_path:
            return None
        return f"{self.plex_url}{thumb_path}?X-Plex-Token={self.plex_token}"


def main(page: ft.Page):
    page.title = "Plex Movie Randomizer"
    page.window.width = 400
    page.window.height = 700
    page.padding = 0
    
    plex = PlexRandomizer()
    
    # Load saved config if exists
    saved_config = get_config()
    
    # ==================== SETUP VIEW ====================
    setup_url = ft.TextField(
        label="Plex Server URL",
        hint_text="http://localhost:32400 or your IP:32400",
        value=saved_config['url'] if saved_config else "http://localhost:32400",
        width=300
    )
    
    setup_token = ft.TextField(
        label="Plex Token",
        hint_text="Your Plex token",
        password=True,
        value=saved_config['token'] if saved_config else "",
        width=300
    )

    token_source_url = ft.TextField(
        label="Paste Network URL here (optional)",
        hint_text="...&X-Plex-Token=YOUR_TOKEN...",
        multiline=True,
        min_lines=2,
        max_lines=3,
        width=300,
    )

    token_grab_status = ft.Text(size=11, color=ft.colors.BLUE_GREY_700)
    
    setup_section = ft.TextField(
        label="Section ID",
        hint_text="Library section ID (e.g., 1 for Movies)",
        value=saved_config['section_id'] if saved_config else "1",
        width=300
    )
    
    setup_error = ft.Text(color=ft.colors.RED, size=12)
    setup_info = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text("How to connect your Plex server:", weight="bold", size=14),
            ft.Text("", size=10),
            ft.Text("1. Server URL:", weight="bold", size=12),
            ft.Text("   • Local: http://localhost:32400", size=10),
            ft.Text("   • Remote: http://[YOUR_IP]:32400", size=10),
            ft.Text("   • App: https://app.plex.tv/desktop", size=10),
            ft.Text("", size=10),
            ft.Text("2. Get token (quick method):", weight="bold", size=12),
            ft.Text("   1. Open Plex (local or app.plex.tv)", size=10),
            ft.Text("   2. Press F12 to open DevTools", size=10),
            ft.Text("   3. Open the 'Network' tab", size=10),
            ft.Text("   4. Reload page (F5)", size=10),
            ft.Text("   5. Find any request URL with token", size=10),
            ft.Text("   6. Copy: X-Plex-Token=XXXXX", size=10),
            ft.Text("", size=10),
            ft.Text("3. Section ID:", weight="bold", size=12),
            ft.Text("   • Default is usually 1 for Movies", size=10),
            ft.Text("   • If you have more libraries, try 1, 2, 3...", size=10),
            ft.Text("", size=10),
            ft.Text("Tip: token is usually ~20-25 chars", size=10),
        ],
        width=350,
        height=300
    )
    
    def on_save_config(e):
        url = setup_url.value.strip()
        token = normalize_token(setup_token.value.strip())
        section = setup_section.value.strip()
        
        setup_error.value = ""
        
        if not url or not token or not section:
            setup_error.value = "All fields are required"
            page.update()
            return
        
        if plex.set_config(url, token, section):
            setup_token.value = token
            if plex.fetch_movies():
                setup_error.value = f"Connected. {len(plex.movies)} movies found"
                # Save configuration
                save_config_to_file(plex.plex_url or url, token, section)
                page.update()
                # Switch to movie view
                show_movie_view()
            else:
                setup_error.value = f"No movies found in this section. {plex.last_error}"
                page.update()
        else:
            setup_error.value = f"Connection error. {plex.last_error}"
            page.update()

    def grab_token_from_url(e):
        raw_url = token_source_url.value.strip()
        token_grab_status.value = ""
        setup_error.value = ""

        if not raw_url:
            token_grab_status.value = "Paste a Network URL that contains X-Plex-Token first"
            page.update()
            return

        token = extract_token_from_text(raw_url)
        if not token:
            token_grab_status.value = "Could not find X-Plex-Token in that text"
            page.update()
            return

        setup_token.value = token
        detected_server = extract_server_from_url(raw_url)
        if detected_server:
            setup_url.value = detected_server

        token_grab_status.value = "Token captured and applied"
        page.update()

    def open_local_plex(e):
        page.launch_url("http://localhost:32400/web")

    def open_plex_web(e):
        page.launch_url("https://app.plex.tv/desktop")
    
    def save_config_to_file(url, token, section):
        """Helper to save config"""
        save_app_config(url, token, section)
    
    setup_btn = ft.ElevatedButton(
        text="Connect",
        on_click=on_save_config,
        width=300,
        height=45
    )

    grab_token_btn = ft.OutlinedButton(
        text="Grab token",
        icon=ft.icons.CONTENT_PASTE_SEARCH,
        on_click=grab_token_from_url,
        width=145,
    )

    open_local_btn = ft.TextButton(
        text="Open local Plex",
        on_click=open_local_plex,
    )

    open_web_btn = ft.TextButton(
        text="Open app.plex.tv",
        on_click=open_plex_web,
    )

    home_btn = ft.IconButton(
        ft.icons.HOME,
        on_click=lambda e: show_movie_view(),
        tooltip="Back to home",
        visible=False,
    )
    
    setup_footer = ft.Container(
        content=ft.Text("v1.0.0", size=10, color=ft.colors.GREY_500),
        alignment=ft.alignment.center,
        padding=ft.padding.only(top=8, bottom=6),
    )

    setup_view = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text("Setup", weight="bold", size=18),
                                    home_btn,
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Divider(),
                            setup_info,
                            ft.Divider(),
                            setup_url,
                            setup_token,
                            token_source_url,
                            ft.Row(
                                controls=[grab_token_btn],
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                            token_grab_status,
                            ft.Row(
                                controls=[open_local_btn, open_web_btn],
                                alignment=ft.MainAxisAlignment.CENTER,
                            ),
                            setup_section,
                            setup_btn,
                            setup_error,
                        ],
                        scroll=ft.ScrollMode.AUTO,
                        spacing=15,
                    ),
                    expand=True,
                ),
                setup_footer,
            ],
            spacing=0,
            expand=True,
        ),
        padding=20,
        expand=True
    )
    
    # ==================== MOVIE VIEW ====================
    movie_title = ft.Text("Press \"🎲 Random\" to begin", weight="bold", size=16)
    movie_year = ft.Text("Year: -", size=12)
    movie_duration = ft.Text("Duration: -", size=12)
    movie_quality = ft.Text("Quality: -", size=12)
    movie_audio = ft.Text("Audio: -", size=12)
    movie_rating = ft.Text("Tomatometer: -", size=12)
    rating_row = ft.Row(
        controls=[
            ft.Text("🍅", size=16),
            movie_rating,
        ],
        spacing=6,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    movie_summary = ft.Text(
        "Connect and pick a movie to view details.",
        size=14,
        color=ft.colors.BLACK,
        selectable=True,
        text_align=ft.TextAlign.LEFT,
    )
    movie_thumb = ft.Image(
        src_base64=TRANSPARENT_PIXEL_BASE64,
        width=200,
        height=300,
        fit=ft.ImageFit.COVER,
    )
    
    history_status = ft.Text("(no selection)", size=10, color=ft.colors.GREY)

    def get_summary_width() -> int:
        # Keep synopsis panel around 70% of available width while respecting minimum.
        viewport_width = page.width or page.window.width or 400
        return max(300, int(viewport_width * 0.7))

    synopsis_container = ft.Container(
        content=movie_summary,
        padding=14,
        width=get_summary_width(),
        bgcolor=ft.colors.WHITE,
        border=ft.border.all(1, ft.colors.BLUE_GREY_200),
        border_radius=14,
    )

    def on_window_resized(e):
        synopsis_container.width = get_summary_width()
        page.update()

    page.window.on_resized = on_window_resized
    
    def update_movie_display(movie: Dict):
        if not movie:
            movie_title.value = "No movies available"
            movie_year.value = "Year: -"
            movie_duration.value = "Duration: -"
            movie_quality.value = "Quality: -"
            movie_audio.value = "Audio: -"
            movie_rating.value = "Tomatometer: -"
            movie_summary.value = "No movies were found to display."
            movie_thumb.src = None
            movie_thumb.src_base64 = TRANSPARENT_PIXEL_BASE64
            history_status.value = "(no selection)"
            plex_btn.disabled = True
            imdb_btn.disabled = True
            page.update()
            return
        
        if not movie.get("details_loaded"):
            plex.enrich_movie_media_details(movie)

        movie_title.value = movie['title']
        movie_year.value = f"Year: {movie['year']}"
        movie_duration.value = f"Duration: {movie['duration']} mins"
        movie_quality.value = f"Quality: {movie.get('quality', 'Unknown')}"
        movie_audio.value = f"Audio: {movie.get('audio', 'Unknown')}"
        movie_rating.value = f"Tomatometer: {movie['rating']}"
        movie_summary.value = movie['summary'][:200] + "..." if len(movie['summary']) > 200 else movie['summary']
        
        thumb_url = plex.get_thumb_url(movie['thumb'])
        if thumb_url:
            movie_thumb.src = thumb_url
            movie_thumb.src_base64 = None
        else:
            movie_thumb.src = None
            movie_thumb.src_base64 = TRANSPARENT_PIXEL_BASE64

        plex_btn.disabled = False
        imdb_btn.disabled = False
        
        # Update history status
        if plex.current_history_index >= 0:
            history_status.value = f"({plex.current_history_index + 1}/{len(plex.movie_history)})"
        
        page.update()
    
    def pick_random(e):
        movie = plex.get_random_movie()
        if movie:
            update_movie_display(movie)
        else:
            page.snack_bar = ft.SnackBar(ft.Text("No movies available for random pick."))
            page.snack_bar.open = True
            page.update()
    
    def previous_movie(e):
        if plex.current_history_index > 0:
            plex.current_history_index -= 1
            update_movie_display(plex.movie_history[plex.current_history_index])
    
    def next_movie(e):
        if plex.current_history_index < len(plex.movie_history) - 1:
            plex.current_history_index += 1
            update_movie_display(plex.movie_history[plex.current_history_index])
    
    prev_btn = ft.IconButton(
        ft.icons.ARROW_BACK,
        on_click=previous_movie,
        tooltip="Previous movie"
    )
    
    next_btn = ft.ElevatedButton(
        text="Next",
        on_click=next_movie,
        width=150
    )
    
    random_btn = ft.ElevatedButton(
        text="🎲 Random",
        on_click=pick_random,
        width=150,
        height=50
    )
    
    def open_in_plex(e):
        if plex.current_history_index >= 0:
            movie = plex.movie_history[plex.current_history_index]
            url = plex.get_movie_url(movie['key'])
            page.launch_url(url)
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Pick a movie first."))
            page.snack_bar.open = True
            page.update()
    
    def open_imdb(e):
        if plex.current_history_index >= 0:
            movie = plex.movie_history[plex.current_history_index]
            url = plex.get_imdb_url(movie['title'], movie['year'])
            page.launch_url(url)
        else:
            page.snack_bar = ft.SnackBar(ft.Text("Pick a movie first."))
            page.snack_bar.open = True
            page.update()
    
    plex_btn = ft.IconButton(ft.icons.PLAY_CIRCLE_FILL_ROUNDED, on_click=open_in_plex, tooltip="Open in Plex", disabled=True)
    imdb_btn = ft.IconButton(ft.icons.LANGUAGE, on_click=open_imdb, tooltip="Search on IMDb", disabled=True)
    
    def back_to_setup(e):
        show_setup_view()
    
    config_btn = ft.IconButton(ft.icons.SETTINGS, on_click=back_to_setup, tooltip="Edit config")
    
    movie_footer = ft.Container(
        content=ft.Text("v1.0.0", size=10, color=ft.colors.GREY_500),
        alignment=ft.alignment.center,
        padding=ft.padding.only(top=8, bottom=6),
    )

    movie_view = ft.Container(
        content=ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row([
                                ft.Container(width=40),
                                ft.Container(
                                    content=ft.Text(
                                        "Plex Movie Randomizer",
                                        weight="bold",
                                        size=18,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    expand=True,
                                ),
                                config_btn
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Divider(),
                            ft.Row([movie_thumb], alignment=ft.MainAxisAlignment.CENTER),
                            ft.Column(
                                controls=[
                                    movie_title,
                                    movie_year,
                                    movie_duration,
                                    movie_quality,
                                    movie_audio,
                                    rating_row,
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=4,
                            ),
                            synopsis_container,
                            ft.Row([
                                plex_btn,
                                imdb_btn,
                            ], alignment=ft.MainAxisAlignment.CENTER),
                            ft.Divider(),
                            ft.Row([random_btn], alignment=ft.MainAxisAlignment.CENTER),
                            ft.Row([
                                prev_btn,
                                ft.Text("History"),
                                history_status,
                                next_btn,
                            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
                        ],
                        scroll=ft.ScrollMode.AUTO,
                        spacing=10,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                ),
                movie_footer,
            ],
            spacing=0,
            expand=True,
        ),
        padding=20,
        expand=True
    )
    
    def show_setup_view():
        home_btn.visible = bool(plex.movies)
        page.clean()
        page.add(setup_view)
    
    def show_movie_view():
        page.clean()
        page.add(movie_view)
        if plex.movie_history and plex.current_history_index >= 0:
            update_movie_display(plex.movie_history[plex.current_history_index])
            return

        if plex.movies:
            update_movie_display(plex.get_random_movie())

    def try_auto_connect() -> bool:
        """Try connecting with saved config and skip setup if successful."""
        if not saved_config:
            return False

        saved_url = (saved_config.get("url") or "").strip()
        saved_token = normalize_token((saved_config.get("token") or "").strip())
        saved_section = str(saved_config.get("section_id") or "").strip()

        if not saved_url or not saved_token or not saved_section:
            return False

        setup_url.value = saved_url
        setup_token.value = saved_token
        setup_section.value = saved_section

        if plex.set_config(saved_url, saved_token, saved_section) and plex.fetch_movies():
            setup_error.value = ""
            return True

        # If auto-connect fails, keep setup visible with a helpful message.
        setup_error.value = (
            "Could not reconnect automatically. "
            f"{plex.last_error}"
        )
        return False
    
    # Start in movie view if saved config still works.
    if try_auto_connect():
        show_movie_view()
    else:
        show_setup_view()


if __name__ == "__main__":
    ft.app(target=main)
