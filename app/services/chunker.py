from __future__ import annotations

from dataclasses import dataclass

from ..schemas import DocumentSegment


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    text: str
    segments: tuple[DocumentSegment, ...]


def _split_segment(segment: DocumentSegment, max_chars: int) -> list[DocumentSegment]:
    if len(segment.text) <= max_chars:
        return [segment]
    fragments: list[DocumentSegment] = []
    for part_number, start in enumerate(range(0, len(segment.text), max_chars), start=1):
        end = min(start + max_chars, len(segment.text))
        fragment_id = f"{segment.source_id}-part-{part_number}"
        location = segment.location.model_copy(
            update={
                "source_id": fragment_id,
                "label": f"{segment.location.label}（片段 {part_number}）",
            }
        )
        fragments.append(
            segment.model_copy(
                update={
                    "source_id": fragment_id,
                    "text": segment.text[start:end],
                    "location": location,
                    "start_offset": segment.start_offset + start,
                    "end_offset": segment.start_offset + end,
                }
            )
        )
    return fragments


def build_chunks(
    segments: list[DocumentSegment],
    max_chars: int = 12000,
    max_chunks: int = 80,
) -> list[TextChunk]:
    if max_chars < 500:
        raise ValueError("分块大小不能小于 500 个字符。")
    chunks: list[TextChunk] = []
    current: list[DocumentSegment] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if not current:
            return
        chunks.append(
            TextChunk(
                chunk_id=f"chunk-{len(chunks) + 1}",
                text="\n".join(segment.text for segment in current),
                segments=tuple(current),
            )
        )
        current = []
        current_length = 0

    for segment in segments:
        for fragment in _split_segment(segment, max_chars):
            fragment_length = len(fragment.text)
            separator_length = 1 if current else 0
            if current and current_length + separator_length + fragment_length > max_chars:
                flush()
            current.append(fragment)
            current_length += (1 if len(current) > 1 else 0) + fragment_length
    flush()

    if len(chunks) > max_chunks:
        raise ValueError(
            f"文件解析后有 {len(chunks)} 个片段，超过当前上限 {max_chunks}；"
            "请调大 CHECKER_MAX_CHUNKS 或拆分文件后再检查。"
        )
    return chunks
