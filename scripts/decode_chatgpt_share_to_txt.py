from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def decode_stream_array(html: str) -> list:
    chunks: list[str] = []
    pattern = re.compile(
        r"window\.__reactRouterContext\.streamController\.enqueue\((\"(?:\\.|[^\"\\])*\")\);"
    )
    for match in pattern.finditer(html):
        chunk = json.loads(match.group(1))
        if chunk.startswith("["):
            chunks.append(chunk)
    if not chunks:
        raise ValueError("Could not find serialized ChatGPT conversation state.")
    return json.loads(chunks[0])


def dereference(data: list) -> dict:
    sys.setrecursionlimit(20000)

    def resolve_ref(ref, memo):
        if isinstance(ref, int):
            if ref < 0:
                return None
            return decode(ref, memo)
        return ref

    def decode(index: int, memo):
        if index in memo:
            return memo[index]
        value = data[index]
        if isinstance(value, dict):
            output = {}
            memo[index] = output
            for key_ref, value_ref in value.items():
                if isinstance(key_ref, str) and key_ref.startswith("_") and key_ref[1:].isdigit():
                    key = resolve_ref(int(key_ref[1:]), memo)
                else:
                    key = key_ref
                output[key] = resolve_ref(value_ref, memo)
            return output
        if isinstance(value, list):
            output = []
            memo[index] = output
            output.extend(resolve_ref(item, memo) for item in value)
            return output
        return value

    return decode(0, {})


def text_from_part(part) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    content_type = part.get("content_type")
    if content_type == "image_asset_pointer":
        width = part.get("width")
        height = part.get("height")
        suffix = f" ({width}x{height})" if width and height else ""
        return f"[Uploaded image{suffix}]"
    if content_type == "audio_asset_pointer":
        return "[Uploaded audio]"
    if isinstance(part.get("text"), str):
        return part["text"]
    if isinstance(part.get("content"), str):
        return part["content"]
    return ""


def message_text(message: dict) -> str:
    content = message.get("content") or {}
    content_type = content.get("content_type")
    if content_type in {"text", "multimodal_text"}:
        parts = content.get("parts") or []
        return "\n".join(text for text in (text_from_part(part) for part in parts) if text).strip()
    if content_type == "code":
        return (content.get("text") or "").strip()
    return ""


def find_conversation(root: dict) -> dict:
    loader_data = root.get("loaderData") or {}
    for value in loader_data.values():
        if isinstance(value, dict):
            server_response = value.get("serverResponse")
            if isinstance(server_response, dict) and isinstance(server_response.get("data"), dict):
                data = server_response["data"]
                if "linear_conversation" in data:
                    return data
    raise ValueError("Could not locate conversation data in serialized state.")


def safe_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "ChatGPT Share"


def export_txt(html_path: Path, output_dir: Path, source_url: str) -> Path:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    root = dereference(decode_stream_array(html))
    conversation = find_conversation(root)
    title = conversation.get("title") or "ChatGPT Share"

    rows: list[tuple[str, str]] = []
    for item in conversation.get("linear_conversation") or []:
        message = item.get("message") if isinstance(item, dict) else None
        if not message:
            continue
        role = (message.get("author") or {}).get("role")
        if role not in {"user", "assistant"}:
            continue
        metadata = message.get("metadata") or {}
        if metadata.get("is_visually_hidden_from_conversation") or metadata.get("is_redacted"):
            continue
        text = message_text(message)
        if text:
            rows.append((role, text))

    if not rows:
        raise ValueError("No visible messages found.")

    lines = [
        f"{title} - ChatGPT Share",
        f"Source: {source_url}",
        f"Exported visible messages: {len(rows)}",
        "",
    ]
    for index, (role, text) in enumerate(rows, 1):
        label = "You" if role == "user" else "ChatGPT"
        lines.append(f"{index}. {label}:")
        lines.append(text.replace("\r\n", "\n").replace("\r", "\n").strip())
        lines.append("")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_filename(title)} - ChatGPT Share.txt"
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "title": title, "messages": len(rows), "bytes": output_path.stat().st_size}))
    return output_path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: decode_chatgpt_share_to_txt.py <html-path> <output-dir> <source-url>")
    export_txt(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])


if __name__ == "__main__":
    main()
