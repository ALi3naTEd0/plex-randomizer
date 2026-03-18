# Plex Movie Randomizer

Flet app to pick a random movie from your Plex server.

Works on desktop (Linux, Windows, macOS) and can be packaged for Android.

## Features

- Random movie picker from a Plex library section.
- Auto-reconnect on startup using saved config.
- Movie poster, title, year, duration, rating, and synopsis.
- Quick links: open movie in Plex and search on IMDb.
- Movie history with previous/next navigation.
- Token helper in UI: paste a Network URL and click "Grab token".

## Requirements

- Python 3.10+
- A reachable Plex Media Server
- Plex token (`X-Plex-Token`)

## Project Structure

```text
plex-randomizer/
├── main.py
├── config.py
├── requirements.txt
├── .gitignore
└── README.md
```

## Installation

```bash
cd plex-randomizer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Windows (PowerShell):

```powershell
cd plex-randomizer
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## First-Time Setup

When you open the app for the first time, fill:

1. `Plex Server URL`
2. `Plex Token`
3. `Section ID`

Then click `Connect`.

If connection succeeds, settings are saved to `plex_config.json`.
On next launch, the app tries to reconnect automatically and goes straight to the randomizer view.

## Plex URL Examples

- Local server: `http://localhost:32400`
- LAN server: `http://192.168.1.125:32400`
- You can also paste a `plex.direct` URL from DevTools/Network; the app normalizes it.

## Getting the Plex Token

Fastest method:

1. Open Plex web (`http://localhost:32400/web`) or `https://app.plex.tv/desktop`.
2. Open DevTools (`F12`) and go to `Network`.
3. Reload page (`F5`).
4. Open any request URL that includes `X-Plex-Token`.
5. Copy only the token value.

Example:

```text
...&X-Plex-Token=abc123XYZ...
```

Token is `abc123XYZ...`.

Tip: you can paste the full request URL into the app and click `Grab token`.

## Section ID

- Movies is often section `1`, but not always.
- If no movies appear, try section `2`, `3`, etc.

## Runtime Behavior

- IMDb link is a search query (`title + year`) because IMDb ID is not requested from Plex in current implementation.
- Rating shown is Plex metadata field `rating`.

## Troubleshooting

### Connection timeout

- Ensure Plex server is running.
- Verify host/port from the same machine running the app.
- Test manually:

```bash
curl "http://YOUR_PLEX_IP:32400/identity?X-Plex-Token=YOUR_TOKEN"
```

### Token issues

- Remove spaces before/after token.
- If you pasted `X-Plex-Token=...`, app normalizes it automatically.
- Regenerate token from Plex web if needed.

### Linux shared library error (`libmpv.so.1`)

If Flet fails with missing `libmpv.so.1`, install mpv library for your distro.

Arch:

```bash
sudo pacman -S mpv
```

Debian/Ubuntu:

```bash
sudo apt install mpv libmpv1
```

### No movies shown

- Check that selected section contains movies.
- Confirm token has access to that library.
- Try a different section ID.

## Android Packaging (Optional)

Android packaging can be handled in CI/CD (for example, GitHub Actions), so this repository intentionally keeps only runtime app files.

## License

MIT
