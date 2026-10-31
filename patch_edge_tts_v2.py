#!/usr/bin/env python3
"""Apply edge-tts PR #491 fix to patch the 403 error."""

import sys

# Path to the edge-tts package in the playbox venv
path = '/home/chewy/media_maker/venv/lib/python3.14/site-packages/edge_tts/constants.py'

with open(path) as f:
    content = f.read()

# Apply the exact fix from PR #491
old_line = 'WSS_URL = f"wss://{BASE_URL}/edge/v1?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"'
new_lines = '''# Since October 2026 the legacy host refuses speech synthesis with a 403.
# Microsoft Edge 155 synthesizes through api.msedgeservices.com, which also
# accepts the legacy token, given as Ocp-Apim-Subscription-Key. The voice
# list is still served by the legacy host.
WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
)'''

if old_line in content:
    content = content.replace(old_line, new_lines)
    print("✓ Replaced WSS_URL with new endpoint")
else:
    print("✗ Could not find old WSS_URL line")
    # Show what we have
    for i, line in enumerate(content.split('\n'), 1):
        if 'WSS_URL' in line:
            print(f"  Line {i}: {line}")
    sys.exit(1)

with open(path, 'w') as f:
    f.write(content)

print(f"✓ Patched {path}")
