# Agentmetry logo assets

Chevron **A** monogram with an orange record pulse, plus a clean sans wordmark.

The dot is doing two jobs: it is the letter's counter and it is the record light
of a flight recorder. One idea, so the mark survives at 16px.

## Source (SVG)

| File | Use |
|------|-----|
| `agentmetry-logo-black.svg` | README (light mode), light backgrounds |
| `agentmetry-logo-white.svg` | README (dark mode), dark backgrounds |
| `agentmetry-icon.svg` | `currentColor` icon for theming |

## Rendered (PNG)

GitHub will not accept SVG for a social preview or an avatar, so these are
raster copies at the sizes those surfaces want.

| File | Size | Use |
|------|------|-----|
| `social-preview.png` | 1280x640 | Repo Settings, General, Social preview. The card that renders when the repo URL is shared |
| `avatar-dark.png` | 512x512 | Account or organization avatar, dark ground. Reads better at 20px |
| `avatar-orange.png` | 512x512 | Same, orange ground |

Generated from the SVG rather than drawn, so the mark cannot drift between them:

```bash
cd apps/dashboard
node -e "require('sharp')('../../docs/logo/agentmetry-icon.svg',{density:288}).resize(512,512).png().toFile('out.png')"
```

Text in the social preview uses a system font stack (Segoe UI, Arial,
Helvetica), not Inter, because the renderer cannot be relied on to have a
webfont installed and a missing face silently drops the wordmark.

Dashboard copies live in `apps/dashboard/public/`.
