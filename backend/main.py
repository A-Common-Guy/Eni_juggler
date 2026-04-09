"""
FastAPI application for the ENI Juggler web tool.

Provides REST API endpoints for loading, editing, and exporting
EtherCAT ENI configuration files.
"""

from __future__ import annotations

import copy
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.engine.config_store import (
    AVAILABLE_MODELS,
    get_groq_api_key,
    get_model,
    load_dotenv,
    save_config as save_env_config,
)

load_dotenv()  # load .env before anything reads env vars

from backend.engine.ai_assistant import AIAssistant, is_available as ai_is_available
from backend.engine.operation_log import OperationLog
from backend.engine.recalculator import recalculate
from backend.models.eni_model import (
    EniConfig,
    PdoEntry,
    PdoMapping,
    Slave,
)
from backend.parser.eni_exporter import export_eni
from backend.parser.eni_parser import parse_eni_file, parse_eni_string

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENI_DIR = BASE_DIR / "eni_files"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="ENI Juggler", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AppState:
    config: Optional[EniConfig] = None
    current_file: Optional[str] = None
    op_log: OperationLog = OperationLog()


state = AppState()


def _get_config() -> EniConfig:
    if state.config is None:
        raise HTTPException(status_code=400, detail="No ENI file loaded. Load a file first.")
    return state.config


def _find_slave(slave_id: str) -> Slave:
    config = _get_config()
    for slave in config.slaves:
        if slave.id == slave_id:
            return slave
    raise HTTPException(status_code=404, detail=f"Slave {slave_id} not found")


def _slave_to_dict(slave: Slave) -> dict:
    return slave.to_summary()


def _pdo_entry_to_dict(entry: PdoEntry) -> dict:
    return {
        "index": entry.index,
        "subindex": entry.subindex,
        "bit_len": entry.bit_len,
        "name": entry.name,
        "data_type": entry.data_type,
        "comment": entry.comment,
        "depend_on_slot": entry.depend_on_slot,
    }


def _pdo_to_dict(pdo: PdoMapping, arr_idx: int = 0) -> dict:
    return {
        "arr_idx": arr_idx,
        "index": pdo.index,
        "name": pdo.name,
        "sm": pdo.sm,
        "fixed": pdo.fixed,
        "is_active": pdo.sm is not None,
        "depend_on_slot": pdo.depend_on_slot,
        "excludes": pdo.excludes,
        "total_bit_length": pdo.total_bit_length,
        "entries": [_pdo_entry_to_dict(e) for e in pdo.entries],
    }


# ── File management ─────────────────────────────────────────────


@app.get("/api/files")
def list_files() -> list[dict]:
    files = []
    if ENI_DIR.exists():
        for f in sorted(ENI_DIR.iterdir()):
            if f.suffix.lower() == ".xml":
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                })
    return files


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Only .xml files are accepted")

    ENI_DIR.mkdir(parents=True, exist_ok=True)
    dest = ENI_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": file.filename, "size": len(content)}


# ── Parse / Load ─────────────────────────────────────────────────


@app.post("/api/parse/{filename}")
def parse_file(filename: str) -> dict:
    filepath = ENI_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")

    try:
        config = parse_eni_file(filepath)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse ENI file: {e}")

    state.config = config
    state.current_file = filename
    state.op_log = OperationLog()
    state.op_log.log_load(filename, len(config.slaves))

    return {
        "filename": filename,
        "slave_count": len(config.slaves),
        "slaves": [_slave_to_dict(s) for s in config.slaves],
        "cyclic": {
            "cycle_time": config.cyclic.cycle_time,
            "priority": config.cyclic.priority,
        },
    }


# ── Slave operations ─────────────────────────────────────────────


@app.get("/api/slaves")
def get_slaves() -> list[dict]:
    config = _get_config()
    return [_slave_to_dict(s) for s in config.slaves]


class ReorderRequest(BaseModel):
    slave_ids: list[str]


@app.put("/api/slaves/reorder")
def reorder_slaves(req: ReorderRequest) -> list[dict]:
    config = _get_config()

    id_to_slave = {s.id: s for s in config.slaves}
    new_list = []
    for sid in req.slave_ids:
        if sid not in id_to_slave:
            raise HTTPException(status_code=400, detail=f"Unknown slave id: {sid}")
        new_list.append(id_to_slave[sid])

    remaining = [s for s in config.slaves if s.id not in set(req.slave_ids)]
    config.slaves = new_list + remaining

    state.op_log.log_reorder(req.slave_ids)
    recalculate(config)

    return [_slave_to_dict(s) for s in config.slaves]


@app.delete("/api/slaves/{slave_id}")
def remove_slave(slave_id: str) -> dict:
    config = _get_config()
    slave = _find_slave(slave_id)
    idx = config.slaves.index(slave)

    config.slaves.remove(slave)
    state.op_log.log_remove_slave(slave_id, slave.info.name, idx)
    recalculate(config)

    return {"removed": slave.info.name, "remaining": len(config.slaves)}


class ToggleRequest(BaseModel):
    enabled: bool


@app.put("/api/slaves/{slave_id}/toggle")
def toggle_slave(slave_id: str, req: ToggleRequest) -> dict:
    slave = _find_slave(slave_id)
    slave.enabled = req.enabled

    state.op_log.log_toggle_slave(slave_id, slave.info.name, req.enabled)
    recalculate(_get_config())

    return _slave_to_dict(slave)


class EditSlaveInfoRequest(BaseModel):
    name: Optional[str] = None
    vendor_id: Optional[int] = None
    product_code: Optional[int] = None
    revision_no: Optional[int] = None
    serial_no: Optional[int] = None
    physics: Optional[str] = None


@app.put("/api/slaves/{slave_id}")
def edit_slave(slave_id: str, req: EditSlaveInfoRequest) -> dict:
    slave = _find_slave(slave_id)

    for field_name in ["name", "vendor_id", "product_code", "revision_no", "serial_no", "physics"]:
        new_val = getattr(req, field_name)
        if new_val is not None:
            old_val = getattr(slave.info, field_name)
            setattr(slave.info, field_name, new_val)
            state.op_log.log_edit_slave_info(slave_id, field_name, old_val, new_val, slave_name=slave.info.name)

    recalculate(_get_config())
    return _slave_to_dict(slave)


# ── PDO operations ───────────────────────────────────────────────


@app.get("/api/slaves/{slave_id}/pdos")
def get_slave_pdos(slave_id: str) -> dict:
    slave = _find_slave(slave_id)
    return {
        "tx_pdos": [_pdo_to_dict(p, i) for i, p in enumerate(slave.process_data.tx_pdos)],
        "rx_pdos": [_pdo_to_dict(p, i) for i, p in enumerate(slave.process_data.rx_pdos)],
    }


class SetActivePdoRequest(BaseModel):
    pdo_idx: int


@app.put("/api/slaves/{slave_id}/pdos/{pdo_type}/active")
def set_active_pdo(slave_id: str, pdo_type: str, req: SetActivePdoRequest) -> dict:
    """Switch which PDO mapping is active by moving the Sm attribute."""
    slave = _find_slave(slave_id)

    if pdo_type == "tx":
        pdos = slave.process_data.tx_pdos
        default_sm = "3"
    elif pdo_type == "rx":
        pdos = slave.process_data.rx_pdos
        default_sm = "2"
    else:
        raise HTTPException(status_code=400, detail="pdo_type must be 'tx' or 'rx'")

    if req.pdo_idx < 0 or req.pdo_idx >= len(pdos):
        raise HTTPException(status_code=404, detail="PDO index out of range")

    current_sm = None
    for p in pdos:
        if p.sm is not None:
            current_sm = p.sm
            break
    sm_value = current_sm or default_sm

    for p in pdos:
        p.sm = None
    pdos[req.pdo_idx].sm = sm_value

    state.op_log.record(
        "set_active_pdo",
        slave_id=slave_id,
        pdo_type=pdo_type,
        pdo_index=pdos[req.pdo_idx].index,
    )
    recalculate(_get_config())

    return {
        "tx_pdos": [_pdo_to_dict(p, i) for i, p in enumerate(slave.process_data.tx_pdos)],
        "rx_pdos": [_pdo_to_dict(p, i) for i, p in enumerate(slave.process_data.rx_pdos)],
    }


class EditPdoEntryRequest(BaseModel):
    index: Optional[str] = None
    subindex: Optional[str] = None
    bit_len: Optional[int] = None
    name: Optional[str] = None
    data_type: Optional[str] = None
    comment: Optional[str] = None


@app.put("/api/slaves/{slave_id}/pdos/{pdo_type}/{pdo_idx}/entries/{entry_idx}")
def edit_pdo_entry(
    slave_id: str,
    pdo_type: str,
    pdo_idx: int,
    entry_idx: int,
    req: EditPdoEntryRequest,
) -> dict:
    slave = _find_slave(slave_id)

    if pdo_type == "tx":
        pdos = slave.process_data.tx_pdos
    elif pdo_type == "rx":
        pdos = slave.process_data.rx_pdos
    else:
        raise HTTPException(status_code=400, detail="pdo_type must be 'tx' or 'rx'")

    if pdo_idx < 0 or pdo_idx >= len(pdos):
        raise HTTPException(status_code=404, detail="PDO index out of range")

    pdo = pdos[pdo_idx]
    if entry_idx < 0 or entry_idx >= len(pdo.entries):
        raise HTTPException(status_code=404, detail="Entry index out of range")

    entry = pdo.entries[entry_idx]

    for field_name in ["index", "subindex", "bit_len", "name", "data_type", "comment"]:
        new_val = getattr(req, field_name)
        if new_val is not None:
            old_val = getattr(entry, field_name)
            setattr(entry, field_name, new_val)
            state.op_log.log_edit_pdo_entry(
                slave_id, pdo_type, pdo.index, entry_idx, field_name, old_val, new_val,
                slave_name=slave.info.name, entry_name=entry.name,
            )

    recalculate(_get_config())
    return _pdo_to_dict(pdo)


class AddPdoEntryRequest(BaseModel):
    index: str = "#x0000"
    subindex: str = "0"
    bit_len: int = 16
    name: str = "New Entry"
    data_type: str = "UINT"


@app.post("/api/slaves/{slave_id}/pdos/{pdo_type}/{pdo_idx}/entries")
def add_pdo_entry(
    slave_id: str,
    pdo_type: str,
    pdo_idx: int,
    req: AddPdoEntryRequest,
) -> dict:
    slave = _find_slave(slave_id)

    if pdo_type == "tx":
        pdos = slave.process_data.tx_pdos
    elif pdo_type == "rx":
        pdos = slave.process_data.rx_pdos
    else:
        raise HTTPException(status_code=400, detail="pdo_type must be 'tx' or 'rx'")

    if pdo_idx < 0 or pdo_idx >= len(pdos):
        raise HTTPException(status_code=404, detail="PDO index out of range")

    pdo = pdos[pdo_idx]
    new_entry = PdoEntry(
        index=req.index,
        subindex=req.subindex,
        bit_len=req.bit_len,
        name=req.name,
        data_type=req.data_type,
    )
    pdo.entries.append(new_entry)
    state.op_log.log_add_pdo_entry(slave_id, pdo_type, pdo.index, slave_name=slave.info.name, entry_name=req.name)
    recalculate(_get_config())

    return _pdo_to_dict(pdo)


@app.delete("/api/slaves/{slave_id}/pdos/{pdo_type}/{pdo_idx}/entries/{entry_idx}")
def remove_pdo_entry(
    slave_id: str,
    pdo_type: str,
    pdo_idx: int,
    entry_idx: int,
) -> dict:
    slave = _find_slave(slave_id)

    if pdo_type == "tx":
        pdos = slave.process_data.tx_pdos
    elif pdo_type == "rx":
        pdos = slave.process_data.rx_pdos
    else:
        raise HTTPException(status_code=400, detail="pdo_type must be 'tx' or 'rx'")

    if pdo_idx < 0 or pdo_idx >= len(pdos):
        raise HTTPException(status_code=404, detail="PDO index out of range")

    pdo = pdos[pdo_idx]
    if entry_idx < 0 or entry_idx >= len(pdo.entries):
        raise HTTPException(status_code=404, detail="Entry index out of range")

    removed_entry = pdo.entries.pop(entry_idx)
    state.op_log.log_remove_pdo_entry(slave_id, pdo_type, pdo.index, entry_idx, slave_name=slave.info.name, entry_name=removed_entry.name)
    recalculate(_get_config())

    return _pdo_to_dict(pdo)


# ── Duplicate ────────────────────────────────────────────────────


@app.post("/api/slaves/{slave_id}/duplicate")
def duplicate_slave(slave_id: str) -> dict:
    config = _get_config()
    source = _find_slave(slave_id)
    idx = config.slaves.index(source)

    new_slave = Slave(
        id=str(uuid.uuid4()),
        info=copy.deepcopy(source.info),
        process_data=copy.deepcopy(source.process_data),
        previous_port=copy.deepcopy(source.previous_port),
        enabled=True,
        mailbox_raw=copy.deepcopy(source.mailbox_raw),
        init_cmds_raw=copy.deepcopy(source.init_cmds_raw),
    )
    new_slave.info.name = source.info.name + "_copy"

    config.slaves.insert(idx + 1, new_slave)
    state.op_log.log_duplicate_slave(slave_id, new_slave.id, slave_name=source.info.name)
    recalculate(config)

    return _slave_to_dict(new_slave)


# ── Export ───────────────────────────────────────────────────────


class ExportRequest(BaseModel):
    filename: Optional[str] = None


@app.post("/api/export")
def export_config(req: ExportRequest) -> Response:
    config = _get_config()
    recalculate(config)

    xml_str = export_eni(config)
    filename = req.filename or state.current_file or "exported.xml"
    if not filename.endswith(".xml"):
        filename += ".xml"

    state.op_log.log_export(filename)

    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/save")
def save_config(req: ExportRequest) -> dict:
    config = _get_config()
    recalculate(config)

    xml_str = export_eni(config)
    filename = req.filename or state.current_file or "exported.xml"
    if not filename.endswith(".xml"):
        filename += ".xml"

    ENI_DIR.mkdir(parents=True, exist_ok=True)
    dest = ENI_DIR / filename
    dest.write_text(xml_str, encoding="utf-8")

    state.op_log.log_export(filename)
    return {"saved": filename, "size": len(xml_str)}


# ── Operations log ───────────────────────────────────────────────


@app.get("/api/operations")
def get_operations() -> dict:
    return {
        "operations": state.op_log.get_operations(),
        "summary": state.op_log.get_summary(),
    }


# ── Settings ────────────────────────────────────────────────────


@app.get("/api/settings")
def get_settings() -> dict:
    key = get_groq_api_key()
    if key and len(key) > 8:
        masked = key[:4] + "•" * (len(key) - 8) + key[-4:]
    elif key:
        masked = "•" * len(key)
    else:
        masked = None

    from backend.engine.config_store import _read_env_file
    source = "env" if os.environ.get("GROQ_API_KEY") else ("file" if _read_env_file().get("GROQ_API_KEY") else "none")

    return {
        "groq_api_key_set": bool(key),
        "groq_api_key_masked": masked,
        "model": get_model(),
        "source": source,
        "available_models": AVAILABLE_MODELS,
    }


class SaveSettingsRequest(BaseModel):
    groq_api_key: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/settings")
def save_settings(req: SaveSettingsRequest) -> dict:
    global _ai_assistant
    data = {}
    if req.groq_api_key is not None:
        data["groq_api_key"] = req.groq_api_key
    if req.model is not None:
        valid_ids = {m["id"] for m in AVAILABLE_MODELS}
        if req.model not in valid_ids:
            raise HTTPException(status_code=400, detail=f"Unknown model: {req.model}")
        data["model"] = req.model
    if data:
        save_env_config(data)
        _ai_assistant = None  # reset so next chat picks up new key/model
    return {"ok": True, "ai_available": ai_is_available()}


# ── AI Assistant ──────────────────────────────────────────────────

_ai_assistant: Optional[AIAssistant] = None


def _get_ai_assistant() -> AIAssistant:
    global _ai_assistant
    if not ai_is_available():
        raise HTTPException(status_code=503, detail="AI assistant unavailable (GROQ_API_KEY not set or groq SDK missing)")
    if _ai_assistant is None:
        _ai_assistant = AIAssistant(state)
    return _ai_assistant


@app.get("/api/ai/status")
def ai_status() -> dict:
    return {"available": ai_is_available()}


class AIChatRequest(BaseModel):
    message: str


@app.post("/api/ai/chat")
def ai_chat(req: AIChatRequest) -> dict:
    assistant = _get_ai_assistant()
    if state.config is None:
        raise HTTPException(status_code=400, detail="No ENI file loaded. Load a file first.")
    result = assistant.chat(req.message)
    return {
        "response": result["response"],
        "actions": result["actions"],
        "error": result.get("error"),
    }


@app.post("/api/ai/clear")
def ai_clear_history() -> dict:
    global _ai_assistant
    if _ai_assistant is not None:
        _ai_assistant.clear_history()
    return {"ok": True}


# ── Static files (frontend) ─────────────────────────────────────


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
