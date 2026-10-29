# Refreshing the README demo media

## CLI demo GIF

`docs/assets/demo.gif` and `docs/assets/demo-short.gif` were rendered by
`scripts/make_demo_gif.py` from `scripts/demo.py`. They do not show the
tamper/verify ending that `agentmetry demo` prints as of 0.9.4 (the section
that starts `Now try to rewrite it`), so the README does not use them. Its hero
is the 90-second demo video instead: the poster image, served by agentmetry.ai,
linking to the player at https://agentmetry.ai/#watch. Do not treat the
checked-in GIFs as the 0.9.4 transcript until they are re-rendered from it.

## Console tour

The README's "The console" section is the 84-second console tour: a poster
served by agentmetry.ai (`/video/agentmetry-console-poster.jpg`) linking to the
player at https://agentmetry.ai/#console. The MP4 lives in the site repo under
`public/video/agentmetry-console-84s.mp4`. The poster keeps its name so links
already published (PyPI's copy of this README) show the current tour; bump the
`?v=` on the README's image URL when it changes, because GitHub's image proxy
caches by URL.

It follows one detection from the Overview to a triage decision, then tool
policy and `agentmetry verify`. Every screen is the 0.10.1 dashboard captured at
2x over a synthetic trail seeded by `scripts/seed_demo.py` (host `demo-laptop`),
with the dashboard's "Sample data" badge on screen. Nothing of a real machine is
in it. The composition is a HyperFrames project rendered locally with
`npx hyperframes render`, narrated by a local Kokoro voice, with no music. The
site copy is re-encoded from the master render (H.264, CRF 26, faststart) to
about 7 MB. Re-capture the screens when the dashboard changes visibly.

It replaced the one-minute tour of the earlier dashboard. To make the tour an
inline player in the README too, upload it the way the next section describes
and put the bare `user-attachments` URL in the section.

## Inline players on GitHub

An inline video player in a README works only when the URL points at an asset
GitHub hosts itself:

```
https://github.com/user-attachments/assets/<uuid>
```

Keep that line **bare and on its own line**. Wrapping it in an `<a>`, an `<img>`,
or markdown link syntax turns it back into a plain link. GitHub rewrites the bare
URL into a `<video controls>` element pointing at a signed
`private-user-images.githubusercontent.com` URL served as `video/mp4`.

`user-attachments` URLs are minted by GitHub's web upload. There is no API or
`gh` command for it, so refreshing the video is a manual browser step.

Verified as non-working, so nobody retries them (all serve
`application/octet-stream`, so the browser downloads instead of playing):

| Source | Result |
|--------|--------|
| `<video src="docs/assets/agentmetry.mp4">` | stripped by the HTML sanitizer |
| Release asset URL | 302 to a CDN with `Content-Disposition: attachment` |
| `raw.githubusercontent.com` URL | `application/octet-stream` |
| Blob view (`/blob/master/...mp4`) | shows "Download raw file", no player |

## Replacing the video

1. Re-record and overwrite `docs/assets/agentmetry.mp4`.
2. Refresh the release copy (used by the site and by direct links):
   `gh release upload demo-assets docs/assets/agentmetry.mp4 --clobber`
3. Open a new issue draft on github.com and drag the new MP4 into the comment
   box. Wait for the upload, copy the `user-attachments` URL it inserts, then
   close the tab without submitting. The asset stays uploaded.
4. Swap that URL into the README hero line and open a PR.

To confirm the player renders on a branch before merging:

```bash
curl -sL https://github.com/<owner>/<repo>/blob/<branch>/README.md | grep -o '<video[^>]*>'
```

A `<video ... controls="controls" ...>` match means the player is live. Text
extraction tools show only the filename, so they cannot confirm this.

## The demo videos

`scripts/make_demo_video.py` renders two cuts from one set of scenes, frame by
frame with Pillow and ffmpeg, with a voiceover:

| Command | Output | Use |
|---|---|---|
| `python scripts/make_demo_video.py` | `docs/assets/agentmetry-demo-90s.mp4`, 1920x1080, 90 s | README, agentmetry.ai |
| `python scripts/make_demo_video.py --cut social` | `agentmetry-linkedin-1x1.mp4`, 1080x1080, 37 s | LinkedIn |
| `python scripts/make_demo_video.py --cut social --aspect 4:5` | `agentmetry-linkedin-4x5.mp4`, 1080x1350, 37 s | LinkedIn, portrait |

Add `--stills` for two PNGs per scene (in `docs/assets/demo-stills/`) to check
the look, or `--no-voice` for picture only. The social cut has captions burned
in, each held at least 2.5 s, for muted autoplay.

Terminal lines are real 0.9.4 output (`agentmetry demo`, `agentmetry
benchmark`, `agentmetry hooks status`, `agentmetry mcp`, and the hook's
`dlp:` and `tool_policy:` reasons), typed into the script as literals, so
re-run those commands and update the lines when their output changes. The MCP
server names in the fleet scene are illustrative; the line format is real.

Two strings are placeholders, marked `TODO` near the block scene:
`CURSOR_DENY_TEXT` (what Cursor shows when a hook denies a command) and
`CLAUDE_ASK_TEXT` (Claude Code's prompt for a hook `ask`). Replace them with
the agents' real text and re-render.

The voice is Kokoro (`am_michael`) through `npx hyperframes@0.8.149 tts`,
which runs locally. Lines are spelled for the voice ("E D R", "dot A I") and
the script refuses to render if one would run into the next. Clips are cached
in `docs/assets/voice/` and regenerated only when their text, voice or speed
changes.

It needs Pillow, ffmpeg on `PATH`, Node for `npx`, and the IBM Plex fonts the
marketing site bundles (`../ai-audit-watch/node_modules/@fontsource`, or set
`AGENTMETRY_PLEX_DIR`). The rendered files are not committed. The copy
agentmetry.ai serves lives in that repo under `public/video/`, so copy a new
render there and open a site PR.
