from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .schemas import AnalyzeOptions, TaskStatus
from .services.document_parser import SUPPORTED_EXTENSIONS, parse_document
from .services.exporter import result_csv, result_json
from .services.extractor import analyze_document
from .services.llm_client import LLMClient

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_FILE_MB = int(os.getenv("CHECKER_MAX_FILE_MB", "20"))
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
TASK_TTL_SECONDS = max(60, int(os.getenv("CHECKER_TASK_TTL_SECONDS", "3600")))
MAX_RETAINED_TASKS = max(1, int(os.getenv("CHECKER_MAX_RETAINED_TASKS", "100")))
MAX_ACTIVE_TASKS = max(1, int(os.getenv("CHECKER_MAX_ACTIVE_TASKS", "1")))
TEMP_ROOT = Path(tempfile.gettempdir()) / "tender-checker"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="招投标文件漏项检查工具", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_tasks: dict[str, TaskStatus] = {}
_task_created_at: dict[str, float] = {}
_active_reservations = 0


def _cleanup_tasks() -> None:
    now = time.monotonic()
    terminal = [
        task_id
        for task_id, task in _tasks.items()
        if task.status in {"completed", "failed"} and now - _task_created_at.get(task_id, now) > TASK_TTL_SECONDS
    ]
    for task_id in terminal:
        _tasks.pop(task_id, None)
        _task_created_at.pop(task_id, None)

    terminal = [task_id for task_id, task in _tasks.items() if task.status in {"completed", "failed"}]
    terminal.sort(key=lambda task_id: _task_created_at.get(task_id, 0))
    for task_id in terminal[:-MAX_RETAINED_TASKS]:
        _tasks.pop(task_id, None)
        _task_created_at.pop(task_id, None)


def _get_task(task_id: str) -> TaskStatus:
    _cleanup_tasks()
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期。")
    return task


def _safe_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="缺少文件名。")
    name = Path(filename).name
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="只支持 PDF、DOCX、TXT 或 MD 文件。")
    return name


def _safe_base_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in allowed_hosts:
        raise HTTPException(status_code=400, detail="代理地址默认只允许本机回环地址。请通过服务端环境变量显式配置远程代理。")
    return value.rstrip("/")


def _validate_model_options(model: str | None, protocol: str | None, base_url: str | None) -> tuple[str, str, str]:
    normalized_model = (model or "").strip()
    normalized_protocol = (protocol or "").strip().lower()
    normalized_base_url = _safe_base_url((base_url or "").strip())
    if not normalized_model:
        raise HTTPException(status_code=400, detail="请填写模型名称。")
    if normalized_protocol not in {"openai", "anthropic"}:
        raise HTTPException(status_code=400, detail="请选择有效的协议。")
    if not normalized_base_url:
        raise HTTPException(status_code=400, detail="请填写代理地址。")
    return normalized_model, normalized_protocol, normalized_base_url


def _active_task_count() -> int:
    return sum(task.status in {"queued", "running"} for task in _tasks.values()) + _active_reservations


def _set_status(task_id: str, **changes: Any) -> None:
    current = _tasks[task_id]
    _tasks[task_id] = current.model_copy(update=changes)

@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def config() -> dict[str, Any]:
    client = LLMClient()
    return {
        "base_url": "",
        "model": "",
        "protocol": "",
        "max_file_mb": MAX_FILE_MB,
        "max_active_tasks": MAX_ACTIVE_TASKS,
        "mock": client.mock,
    }


@app.get("/api/connection")
async def connection(protocol: str = "openai", model: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    normalized_model, normalized_protocol, normalized_base_url = _validate_model_options(model, protocol, base_url)
    client = LLMClient(protocol=normalized_protocol, model=normalized_model, base_url=normalized_base_url)
    return await client.check_connection()


@app.post("/api/analyze", response_model=TaskStatus)
async def create_analysis(
    file: UploadFile = File(...),
    model: str | None = Form(default=None),
    protocol: str = Form(default="openai"),
    base_url: str | None = Form(default=None),
) -> TaskStatus:
    normalized_model, normalized_protocol, normalized_base_url = _validate_model_options(model, protocol, base_url)
    global _active_reservations
    filename = _safe_filename(file.filename)
    _cleanup_tasks()
    if _active_task_count() >= MAX_ACTIVE_TASKS:
        await file.close()
        raise HTTPException(status_code=429, detail="当前已有检查任务处理中，请稍后再试。")
    _active_reservations += 1
    task_id = uuid.uuid4().hex
    task_dir = TEMP_ROOT / task_id
    try:
        task_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        _active_reservations -= 1
        await file.close()
        raise
    destination = task_dir / filename
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {MAX_FILE_MB} MB。")
                output.write(chunk)
    except Exception:
        _active_reservations -= 1
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    _active_reservations -= 1
    status = TaskStatus(task_id=task_id, filename=filename, status="queued", stage="等待处理", progress=0)
    _tasks[task_id] = status
    _task_created_at[task_id] = time.monotonic()
    asyncio.create_task(_run_analysis(task_id, destination, AnalyzeOptions(model=normalized_model, protocol=normalized_protocol, base_url=normalized_base_url)))
    return status


async def _run_analysis(task_id: str, path: Path, options: AnalyzeOptions) -> None:
    try:
        _set_status(task_id, status="running", stage="解析文档", progress=10, message="正在提取带位置的原文片段。")
        document = await asyncio.to_thread(parse_document, path)
        if not document.segments:
            _set_status(task_id, status="failed", stage="解析失败", progress=100, error="；".join(document.warnings) or "没有可提取的文字。", warnings=document.warnings)
            return
        _set_status(task_id, stage="抽取条款", progress=30, warnings=document.warnings, message=f"已解析 {len(document.segments)} 个原文片段。")
        client = LLMClient(model=options.model, protocol=options.protocol, base_url=options.base_url)
        result = await analyze_document(
            document,
            client,
            max_chars=int(os.getenv("CHECKER_CHUNK_CHARS", "12000")),
            max_chunks=int(os.getenv("CHECKER_MAX_CHUNKS", "80")),
            max_concurrency=int(os.getenv("CHECKER_MAX_CONCURRENCY", "2")),
        )
        _set_status(task_id, stage="校验引用", progress=85, message="正在核验模型返回的原文摘录。")
        _set_status(task_id, status="completed", stage="完成", progress=100, message="检查完成，结果仍需人工复核。", result=result)
    except Exception as exc:
        _set_status(task_id, status="failed", stage="失败", progress=100, error=str(exc))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


@app.get("/api/tasks/{task_id}", response_model=TaskStatus)
async def get_task(task_id: str) -> TaskStatus:
    return _get_task(task_id)


@app.get("/api/tasks/{task_id}/export.json")
async def export_json(task_id: str) -> JSONResponse:
    task = _get_task(task_id)
    result = task.result
    if result is None or task.status != "completed":
        raise HTTPException(status_code=409, detail="任务尚未完成。")
    return JSONResponse(content={key: [item.model_dump(mode="json") for item in items] for key, items in result.items()})


@app.get("/api/tasks/{task_id}/export.csv")
async def export_csv(task_id: str) -> PlainTextResponse:
    task = _get_task(task_id)
    result = task.result
    if result is None or task.status != "completed":
        raise HTTPException(status_code=409, detail="任务尚未完成。")
    return PlainTextResponse(result_csv(result), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=check-results.csv"})
