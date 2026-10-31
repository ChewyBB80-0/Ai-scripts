#!/usr/bin/env python3
"""Patch edge-tts constants.py to use new Microsoft endpoint."""

path = 'venv/lib/python3.14/site-packages/edge_tts/constants.py'

with open(path) as f:
    content = f.read()

# Keep BASE_URL for voice list (still works on old host)
# Override WSS_URL to use new endpoint
old_wss = 'WSS_URL = f"wss://{BASE_URL}/edge/v1?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"'
new_wss = 'WSS_URL = "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?TrustedClientToken=" + TRUSTED_CLIENT_TOKEN'

if old_wss in content:
    content = content.replace(old_wss, new_wss)
    print("Replaced WSS_URL")
else:
    print("WSS_URL pattern not found, checking current content:")
    for line in content.split('\n'):
        if 'WSS_URL' in line:
            print(f"  Found: {line}")

with open(path, 'w') as f:
    f.write(content)

print("Patched successfully")
