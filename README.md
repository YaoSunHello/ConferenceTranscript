# ConferenceTranscript

Utilities and exported transcripts from shared ChatGPT conversations.

## What This Contains

- `scripts/extract_chatgpt_share.mjs` loads a ChatGPT share URL in Chrome through the DevTools protocol and saves the rendered text plus full hydrated HTML.
- `scripts/decode_chatgpt_share_to_txt.py` decodes the serialized ChatGPT conversation state from that HTML and writes a full visible-message transcript as `.txt`.

The decoder is the important step. ChatGPT share pages virtualize long conversations, so scraping `innerText` can miss earlier turns. The decoder reads `linear_conversation` from the page state and filters out hidden/system/internal messages.

## Requirements

- macOS with Google Chrome installed
- Node.js 24+ or another Node version with global `WebSocket`
- Python 3.10+

No Python packages are required.

## Export A Share Link

Set the share URL and choose a temporary prefix:

```bash
SHARE_URL="https://chatgpt.com/share/..."
PREFIX="/tmp/chatgpt-share"
PORT=9225
```

Start Chrome with a temporary profile and DevTools enabled:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new \
  --disable-gpu \
  --no-first-run \
  --disable-extensions \
  --user-data-dir="${PREFIX}-chrome-profile" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="${PORT}" \
  about:blank
```

In another terminal, extract the hydrated page:

```bash
node scripts/extract_chatgpt_share.mjs \
  "$SHARE_URL" \
  "${PREFIX}.visible.txt" \
  "${PREFIX}.html" \
  "$PORT"
```

Decode the full visible conversation to TXT:

```bash
python3 scripts/decode_chatgpt_share_to_txt.py \
  "${PREFIX}.html" \
  . \
  "$SHARE_URL"
```

The output filename is derived from the ChatGPT share title, for example:

```text
Meeting recording organizer - ChatGPT Share.txt
```

## Output Format

Each transcript begins with:

```text
<title> - ChatGPT Share
Source: <share URL>
Exported visible messages: <count>
```

Messages are then numbered in order as `You` or `ChatGPT`. Uploaded images are represented as placeholders such as:

```text
[Uploaded image (1536x1152)]
```

## Notes

- The extractor dismisses the cookie prompt if present.
- The visible-text file from the extraction step is only a fallback/debug artifact.
- For long conversations, trust the decoded TXT output from `decode_chatgpt_share_to_txt.py`, not the visible-text scrape.
