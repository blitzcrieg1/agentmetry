#!/bin/bash
# Build a macOS installer payload for the LaunchDaemon, LaunchAgent, and scripts.
#
# Signing identities and the notary password come from the environment.
# This script does not contain a certificate, a key, or an app-specific password.
# With no identity set, it builds an unsigned package only when
# AGENTMETRY_ALLOW_UNSIGNED=1. Otherwise it stops.
#
#   AGENTMETRY_CODESIGN_IDENTITY   codesign identity (Developer ID Application)
#   AGENTMETRY_INSTALLER_IDENTITY  productsign identity (Developer ID Installer)
#   APPLE_ID                       notarytool Apple ID
#   APPLE_TEAM_ID                  notarytool team id
#   APPLE_APP_PASSWORD             notarytool app-specific password
#   AGENTMETRY_ALLOW_UNSIGNED=1    permit an unsigned pkg when identities are unset
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
STAGE=$(mktemp -d)
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

PAYLOAD="$STAGE/payload"
mkdir -p "$PAYLOAD/Library/LaunchDaemons" \
         "$PAYLOAD/Library/LaunchAgents" \
         "$PAYLOAD/usr/local/lib/agentmetry" \
         "$PAYLOAD/var/db/agentmetry/logs" \
         "$PAYLOAD/etc/agentmetry"

cp "$ROOT/ai.agentmetry.daemon.plist" "$PAYLOAD/Library/LaunchDaemons/ai.agentmetry.daemon.plist"
cp "$ROOT/ai.agentmetry.agent.plist" "$PAYLOAD/Library/LaunchAgents/ai.agentmetry.agent.plist"
cp "$ROOT/agentmetry-daemon.sh" "$ROOT/agentmetry-user-agent.sh" "$PAYLOAD/usr/local/lib/agentmetry/"
chmod 755 "$PAYLOAD/usr/local/lib/agentmetry/"*.sh

# Optional self-contained interpreter. The caller points this at a tree they
# built (a relocatable venv or a python.org framework). It is not downloaded
# here, and it is what codesign --options runtime is for.
if [ -n "${AGENTMETRY_RUNTIME_DIR:-}" ]; then
    mkdir -p "$PAYLOAD/usr/local/lib/agentmetry/runtime"
    cp -R "$AGENTMETRY_RUNTIME_DIR"/. "$PAYLOAD/usr/local/lib/agentmetry/runtime/"
fi
chmod 644 "$PAYLOAD/Library/LaunchDaemons/ai.agentmetry.daemon.plist" \
          "$PAYLOAD/Library/LaunchAgents/ai.agentmetry.agent.plist"

# An empty policy file is root-owned once pkgbuild runs as root. The sensor
# refuses it if a user can write it. Do not put secrets in this file.
printf 'schema: 1\n' > "$PAYLOAD/etc/agentmetry/policy.yaml"

sign_bins() {
    local identity=$1 path
    # Hardened runtime is a Mach-O flag. Shell scripts are not signed with it.
    while IFS= read -r path; do
        if file "$path" | grep -q 'Mach-O'; then
            codesign --force --options runtime --timestamp --sign "$identity" "$path"
        fi
    done < <(find "$PAYLOAD" -type f -print)
}

if [ -n "${AGENTMETRY_CODESIGN_IDENTITY:-}" ]; then
    sign_bins "$AGENTMETRY_CODESIGN_IDENTITY"
elif [ "${AGENTMETRY_ALLOW_UNSIGNED:-}" != "1" ]; then
    echo "AGENTMETRY_CODESIGN_IDENTITY is unset. Set it, or AGENTMETRY_ALLOW_UNSIGNED=1." >&2
    exit 1
fi

COMPONENT="$STAGE/agentmetry-component.pkg"
pkgbuild --root "$PAYLOAD" \
         --identifier ai.agentmetry.sensor \
         --version "${AGENTMETRY_PKG_VERSION:-0.9.8}" \
         --install-location / \
         "$COMPONENT"

OUT="${AGENTMETRY_PKG_OUT:-$ROOT/Agentmetry.pkg}"
if [ -n "${AGENTMETRY_INSTALLER_IDENTITY:-}" ]; then
    productbuild --package "$COMPONENT" \
                 --sign "$AGENTMETRY_INSTALLER_IDENTITY" \
                 "$OUT"
else
    if [ "${AGENTMETRY_ALLOW_UNSIGNED:-}" != "1" ]; then
        echo "AGENTMETRY_INSTALLER_IDENTITY is unset. Set it, or AGENTMETRY_ALLOW_UNSIGNED=1." >&2
        exit 1
    fi
    productbuild --package "$COMPONENT" "$OUT"
fi

if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
    xcrun notarytool submit "$OUT" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" \
        --wait
    xcrun stapler staple "$OUT"
else
    echo "Notarization skipped (APPLE_ID, APPLE_TEAM_ID, or APPLE_APP_PASSWORD unset)."
fi

echo "wrote $OUT"
