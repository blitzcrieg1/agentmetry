# Refreshing the README demo video

GitHub renders an inline `<video>` player only for assets it hosts itself
(`github.com/user-attachments/assets/<uuid>`). These are created by the web
editor, not by any API or CLI, so the upload is a manual one-time step.

Verified as non-working (all serve `application/octet-stream`, so the browser
downloads instead of playing):

| Source | Result |
|--------|--------|
| `<video src="docs/assets/agentmetry.mp4">` | stripped by the HTML sanitizer |
| Release asset URL | `Content-Disposition: attachment` |
| `raw.githubusercontent.com` URL | `application/octet-stream` |
| Blob view (`/blob/master/...mp4`) | shows "Download raw file", no player |

## Upgrading the poster to a real inline player

1. Open `README.md` on github.com and click the pencil (Edit).
2. Drag `docs/assets/agentmetry.mp4` into the editor. GitHub uploads it and
   inserts a `https://github.com/user-attachments/assets/<uuid>` URL.
3. Replace the poster `<a>`/`<img>` block with that bare URL on its own line.
4. Preview to confirm a player appears, then commit.

## When the video changes

Re-record, replace `docs/assets/agentmetry.mp4`, refresh the release asset with
`gh release upload demo-assets docs/assets/agentmetry.mp4 --clobber`, then redo
the drag-and-drop above so the player points at the new file.
