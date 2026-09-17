from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


def decode_stream_array(html: str) -> list:
    """
    Extract and decode the serialized React Router state embedded in
    a saved ChatGPT share-page HTML file.
    """
    chunks: list[str] = []

    pattern = re.compile(
        r'window\.__reactRouterContext\.streamController\.enqueue\('
        r'("(?:\\.|[^"\\])*")'
        r'\);'
    )

    for match in pattern.finditer(html):
        chunk = json.loads(match.group(1))

        if chunk.startswith("["):
            chunks.append(chunk)

    if not chunks:
        raise ValueError(
            "Could not find serialized ChatGPT conversation state."
        )

    return json.loads(chunks[0])


def dereference(data: list) -> dict:
    """
    Resolve references within the serialized ChatGPT conversation state.

    Integer values reference other positions in the serialized data array.
    """
    sys.setrecursionlimit(20000)

    def resolve_ref(ref: Any, memo: dict[int, Any]) -> Any:
        if isinstance(ref, int):
            if ref < 0:
                return None

            return decode(ref, memo)

        return ref

    def decode(index: int, memo: dict[int, Any]) -> Any:
        if index in memo:
            return memo[index]

        value = data[index]

        if isinstance(value, dict):
            output: dict[Any, Any] = {}
            memo[index] = output

            for key_ref, value_ref in value.items():
                if (
                    isinstance(key_ref, str)
                    and key_ref.startswith("_")
                    and key_ref[1:].isdigit()
                ):
                    key = resolve_ref(int(key_ref[1:]), memo)
                else:
                    key = key_ref

                output[key] = resolve_ref(value_ref, memo)

            return output

        if isinstance(value, list):
            output: list[Any] = []
            memo[index] = output

            output.extend(
                resolve_ref(item, memo)
                for item in value
            )

            return output

        return value

    result = decode(0, {})

    if not isinstance(result, dict):
        raise ValueError(
            "The decoded ChatGPT conversation state is not a dictionary."
        )

    return result


def text_from_part(part: Any) -> str:
    """
    Convert a message content part into Markdown-compatible text.
    """
    if isinstance(part, str):
        return part

    if not isinstance(part, dict):
        return ""

    content_type = part.get("content_type")

    if content_type == "image_asset_pointer":
        width = part.get("width")
        height = part.get("height")

        if width and height:
            return f"*_[Uploaded image: {width} × {height}]_*"

        return "*_[Uploaded image]_*"

    if content_type == "audio_asset_pointer":
        return "*_[Uploaded audio]_*"

    if isinstance(part.get("text"), str):
        return part["text"]

    if isinstance(part.get("content"), str):
        return part["content"]

    return ""


def message_text(message: dict) -> str:
    """
    Extract the visible textual content from a ChatGPT message.
    """
    content = message.get("content") or {}
    content_type = content.get("content_type")

    if content_type in {"text", "multimodal_text"}:
        parts = content.get("parts") or []

        extracted_parts = [
            text_from_part(part)
            for part in parts
        ]

        return "\n\n".join(
            text
            for text in extracted_parts
            if text
        ).strip()

    if content_type == "code":
        code = (content.get("text") or "").strip()

        if not code:
            return ""

        language = (
            content.get("language")
            or content.get("response_format_name")
            or ""
        )

        return create_code_block(code, str(language))

    return ""


def create_code_block(code: str, language: str = "") -> str:
    """
    Wrap code in a Markdown fenced code block.

    The fence length is increased when the code itself contains
    triple backticks.
    """
    backtick_groups = re.findall(r"`+", code)
    longest_group = max(
        (len(group) for group in backtick_groups),
        default=0,
    )

    fence = "`" * max(3, longest_group + 1)

    language = re.sub(
        r"[^A-Za-z0-9_+#.-]",
        "",
        language.strip(),
    )

    return f"{fence}{language}\n{code}\n{fence}"


def find_conversation(root: dict) -> dict:
    """
    Locate the conversation object inside the decoded page state.
    """
    loader_data = root.get("loaderData") or {}

    if not isinstance(loader_data, dict):
        raise ValueError(
            "Could not locate loaderData in serialized state."
        )

    for value in loader_data.values():
        if not isinstance(value, dict):
            continue

        server_response = value.get("serverResponse")

        if not isinstance(server_response, dict):
            continue

        data = server_response.get("data")

        if (
            isinstance(data, dict)
            and "linear_conversation" in data
        ):
            return data

    raise ValueError(
        "Could not locate conversation data in serialized state."
    )


def safe_filename(title: str) -> str:
    """
    Convert a conversation title into a safe filename.
    """
    cleaned = re.sub(
        r'[\\/:*?"<>|]+',
        " ",
        title,
    ).strip()

    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.rstrip(". ")

    return cleaned[:120] or "ChatGPT Share"


def safe_markdown_heading(text: str) -> str:
    """
    Prevent heading characters in the title from affecting
    the Markdown structure.
    """
    text = text.replace("\r\n", " ")
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()

    return text.replace("#", r"\#")


def normalize_message_text(text: str) -> str:
    """
    Normalize line endings while preserving the message's
    existing Markdown formatting.
    """
    return (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )


def export_md(
    html_path: Path,
    output_dir: Path,
    source_url: str,
) -> Path:
    """
    Export a saved ChatGPT share-page HTML file to Markdown.
    """
    if not html_path.exists():
        raise FileNotFoundError(
            f"HTML file not found: {html_path}"
        )

    if not html_path.is_file():
        raise ValueError(
            f"HTML path is not a file: {html_path}"
        )

    html = html_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    root = dereference(decode_stream_array(html))
    conversation = find_conversation(root)

    title = conversation.get("title") or "ChatGPT Share"

    if not isinstance(title, str):
        title = str(title)

    rows: list[tuple[str, str]] = []

    linear_conversation = (
        conversation.get("linear_conversation") or []
    )

    for item in linear_conversation:
        if not isinstance(item, dict):
            continue

        message = item.get("message")

        if not isinstance(message, dict):
            continue

        author = message.get("author") or {}
        role = author.get("role")

        if role not in {"user", "assistant"}:
            continue

        metadata = message.get("metadata") or {}

        if metadata.get("is_visually_hidden_from_conversation"):
            continue

        if metadata.get("is_redacted"):
            continue

        text = message_text(message)

        if text:
            rows.append(
                (
                    role,
                    normalize_message_text(text),
                )
            )

    if not rows:
        raise ValueError(
            "No visible user or assistant messages were found."
        )

    markdown_title = safe_markdown_heading(title)

    lines = [
        f"# {markdown_title}",
        "",
        f"**Source:** <{source_url}>",
        "",
        f"**Exported visible messages:** {len(rows)}",
        "",
        "---",
        "",
    ]

    for index, (role, text) in enumerate(rows, start=1):
        label = "You" if role == "user" else "ChatGPT"

        lines.extend(
            [
                f"## {index}. {label}",
                "",
                text,
                "",
            ]
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / f"{safe_filename(title)} - ChatGPT Share.md"
    )

    markdown_content = "\n".join(lines).rstrip() + "\n"

    output_path.write_text(
        markdown_content,
        encoding="utf-8",
    )

    result = {
        "output": str(output_path),
        "title": title,
        "messages": len(rows),
        "bytes": output_path.stat().st_size,
        "format": "markdown",
    }

    print(
        json.dumps(
            result,
            ensure_ascii=False,
        )
    )

    return output_path


def main() -> None:
    """
    Command-line entry point.
    """
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: decode_chatgpt_share_to_md.py "
            "<html-path> <output-dir> <source-url>"
        )

    html_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    source_url = sys.argv[3]

    try:
        export_md(
            html_path=html_path,
            output_dir=output_dir,
            source_url=source_url,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "type": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
