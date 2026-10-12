from __future__ import annotations

import asyncio
import os
import re

from ..schemas import DocumentSegment, ExtractedItem, LLMItem, ParsedDocument, ResultCategory, empty_result
from .chunker import TextChunk, build_chunks
from .llm_client import LLMClient


def _find_segment(item: LLMItem, segments: dict[str, DocumentSegment]) -> DocumentSegment | None:
    segment = segments.get(item.source_id)
    if segment:
        evidence = item.evidence.strip()
        return segment if evidence and evidence in segment.text else None
    match = re.fullmatch(r"(.+)-part-\d+", item.source_id)
    if not match:
        return None
    original = segments.get(match.group(1))
    if not original or not item.evidence.strip():
        return None
    return original if item.evidence.strip() in original.text else None


def _normalize_time(text: str) -> str | None:
    if not re.search(r"\d{1,4}年|\d{1,2}月|\d{1,2}[日号]|\d{1,2}:\d{2}", text):
        return None
    return text[:120]


def validate_and_merge(items: list[LLMItem], document: ParsedDocument) -> dict[str, list[ExtractedItem]]:
    source_map = {segment.source_id: segment for segment in document.segments}
    result = empty_result()
    for item in items:
        segment = _find_segment(item, source_map)
        verified = segment is not None
        if segment is None:
            location = None
            note = "模型引用无法在原文片段中匹配，需人工核验。"
        else:
            location = segment.location
            note = "原文摘录已与解析片段匹配。"
        confidence = max(0.0, min(1.0, item.confidence))
        if not verified:
            confidence = min(confidence, 0.3)
        if item.category == ResultCategory.deadlines and not item.normalized_time:
            item.normalized_time = _normalize_time(item.evidence)
        if item.category == ResultCategory.deadlines and item.ambiguity is None and not item.normalized_time:
            item.ambiguity = "时间表达式不完整或未能可靠标准化。"
        item_data = item.model_dump()
        item_data["severity"] = item.severity if verified else "待核验"
        extracted = ExtractedItem(
            **item_data,
            verified=verified,
            verification_note=note,
            location=location,
        )
        result[item.category.value].append(extracted)

    for category, values in result.items():
        deduped: list[ExtractedItem] = []
        seen: set[tuple[str, str, str]] = set()
        for value in values:
            key = (value.category.value, value.requirement.strip(), value.source_id)
            if key not in seen:
                seen.add(key)
                deduped.append(value)
        result[category] = deduped
    return result


async def analyze_document(
    document: ParsedDocument,
    client: LLMClient,
    *,
    max_chars: int = 12000,
    max_chunks: int = 80,
    max_concurrency: int | None = None,
) -> dict[str, list[ExtractedItem]]:
    chunks = build_chunks(document.segments, max_chars=max_chars, max_chunks=max_chunks)
    concurrency = max_concurrency or int(os.getenv("CHECKER_MAX_CONCURRENCY", "2"))
    concurrency = max(1, min(concurrency, 4))
    semaphore = asyncio.Semaphore(concurrency)

    async def extract_chunk(chunk: TextChunk) -> list[LLMItem]:
        async with semaphore:
            return await client.extract(chunk)

    chunk_results = await asyncio.gather(*(extract_chunk(chunk) for chunk in chunks))
    all_items = [item for items in chunk_results for item in items]
    return validate_and_merge(all_items, document)
