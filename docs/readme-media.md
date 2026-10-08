# Refreshing the README demo video

The README hero is a real inline player. It works because the URL points at an
asset GitHub hosts itself:

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

## The 90-second demo video

`scripts/make_demo_video.py` renders `docs/assets/agentmetry-demo-90s.mp4`
(1080p30, silent) and `agentmetry-demo-poster.png` frame by frame with Pillow
and ffmpeg. Every terminal line in it is real output from `agentmetry demo` and
`agentmetry benchmark`, typed into the script as literals, so re-run both
commands and update those lines whenever their output changes.

```bash
python scripts/make_demo_video.py --stills   # ten PNGs to check the look
python scripts/make_demo_video.py            # the full render, about a minute
```

It needs Pillow, ffmpeg on `PATH`, and the IBM Plex fonts the marketing site
bundles (`../ai-audit-watch/node_modules/@fontsource`, or set
`AGENTMETRY_PLEX_DIR`). The rendered files are not committed. The copy
agentmetry.ai serves lives in that repo under `public/video/`, so copy a new
render there and open a site PR.
