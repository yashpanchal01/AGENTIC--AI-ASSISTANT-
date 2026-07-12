# Spotify setup — one time, about 5 minutes

After this, you can say things like **"Jarvis, play some lo-fi"**,
**"pause the music"**, **"skip"**, **"what's playing?"**, and
**"turn it up"** — and Spotify obeys.

**What you need**

- Your normal Spotify account (the one you listen with).
- A browser and 5 minutes. Everything below is free.
- Heads-up: Spotify only lets outside apps *control* playback (play, pause,
  skip, volume) on **Spotify Premium** accounts. That's Spotify's rule, not
  JARVIS's. On a free account JARVIS will tell you aloud when Spotify refuses.

---

## Step 1 — Create your own (free) Spotify app

JARVIS talks to Spotify through an "app" that belongs to you. Making one is
just a form:

1. Open **https://developer.spotify.com/dashboard** in your browser.
2. Click **Log in** and sign in with your normal Spotify account.
3. If it asks you to accept the Developer Terms, tick the box and accept.
4. Click the **Create app** button.
5. Fill in the form:
   - **App name:** `JARVIS`
   - **App description:** `My personal voice assistant`
   - **Redirect URIs:** paste exactly this, then click **Add**:

     ```
     http://127.0.0.1:8898/callback
     ```

     (Every character matters — copy-paste it. This is JARVIS's own computer
     address for the one-time sign-in; nothing goes to the internet.)
   - Where it asks **Which API/SDKs are you planning to use?** tick **Web API**.
6. Tick the terms checkbox and click **Save**.

## Step 2 — Copy your Client ID

1. You should now be on your new app's page. Click **Settings** (top right).
2. At the top you'll see **Client ID** — a long string of letters and numbers.
3. Click **copy** (or select it and press Ctrl+C).

You do **not** need the "Client secret". JARVIS never uses it — leave it alone.

## Step 3 — Give the Client ID to JARVIS

Pick either way:

**Way A — settings file (recommended).** Open (or create) this file in Notepad:

```
C:\Users\<you>\.jarvis\settings.json
```

and add a `spotify_client_id` line. If the file was empty, it should look like:

```json
{
  "spotify_client_id": "paste-your-client-id-here"
}
```

(If the file already has other lines like `"hotkey"`, just add the
`"spotify_client_id"` line after a comma — keep it valid JSON.)

**Way B — environment variable.** In PowerShell:

```powershell
setx JARVIS_SPOTIFY_CLIENT_ID "paste-your-client-id-here"
```

then close and reopen the terminal.

## Step 4 — Sign in once

In a terminal, from the project folder:

```powershell
py -3.13 -m jarvis --spotify-login
```

Your browser opens a Spotify page → click **Agree**. The tab will say
"JARVIS is linked to Spotify" — close it. The terminal prints where the
sign-in token was saved (under `%LOCALAPPDATA%\Jarvis\`, never inside
JARVIS's readable memory notes). You won't need to do this again; the token
refreshes itself.

## Step 5 — Try it

Open the Spotify app and play any song once (that makes your PC the "active
device"). Then:

```powershell
py -3.13 -m jarvis --no-speak --once "what's playing"
py -3.13 -m jarvis --no-speak --once "pause the music"
py -3.13 -m jarvis --no-speak --once "play bohemian rhapsody by queen"
```

Or just talk to the running daemon: "Jarvis, play some lo-fi."

---

## What you can say

| You say | JARVIS does |
|---------|-------------|
| "play bohemian rhapsody by queen" | finds and plays the song |
| "play something by daft punk" | plays the artist |
| "play the playlist chill vibes" | plays your playlist |
| "play some lo-fi" | searches and plays lo-fi |
| "pause the music" / "stop the music" | pauses |
| "resume the music" / "keep playing" | resumes |
| "skip" / "next song" | next track |
| "what's playing?" | says the current track |
| "turn it up" / "quieter" | volume ±10 |
| "set the volume to 30" | volume to 30% |

## If something goes wrong

- **Browser says "INVALID_CLIENT: Invalid redirect URI"** — the Redirect URI
  in your app's Settings must be *exactly* `http://127.0.0.1:8898/callback`.
  Fix it there, Save, and run `--spotify-login` again.
- **JARVIS says "Spotify isn't active on any device"** — open the Spotify app
  and press play once, then repeat the command.
- **JARVIS says playback needs Premium** — Spotify blocks remote control for
  free accounts. "What's playing" still works; controlling playback needs
  Premium.
- **JARVIS says "Spotify isn't set up yet"** — Step 3 didn't stick. Check the
  spelling of `spotify_client_id` in settings.json (and that the file is
  valid JSON), or reopen the terminal if you used `setx`.
- **"Couldn't open the login port 8898"** — something else is using that
  port. Set `JARVIS_SPOTIFY_PORT` to another number (say `8899`), change the
  app's Redirect URI to `http://127.0.0.1:8899/callback`, and sign in again.
