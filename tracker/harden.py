#!/usr/bin/env python3
"""Insert a strict Content-Security-Policy into the page before it is published to GitHub Pages.

GitHub Pages cannot send custom HTTP headers, so the policy goes in a <meta> tag.
The page loads only its own files: script, styles, data.json and feed.xml. Nothing from other hosts.
"""
import sys
from pathlib import Path

CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
       "object-src 'none'; upgrade-insecure-requests")
TAGS = (f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '<meta name="referrer" content="no-referrer">\n')

path = Path(sys.argv[1])
html = path.read_text(encoding="utf-8")
marker = "<!--security-->"
if marker not in html:
    sys.exit("security marker missing from page")
path.write_text(html.replace(marker, TAGS, 1), encoding="utf-8")
print("CSP inserted")
