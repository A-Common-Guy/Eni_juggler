"""
AI Assistant for ENI Juggler.

Uses Groq's API (OpenAI-compatible) with tool-calling to let users describe
EtherCAT config changes in natural language. The AI can inspect the current
config and apply modifications through the same operations the UI uses.

Rate-limit errors (429) are handled with exponential backoff.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"

# Retry config for 429 rate-limit errors
_RETRY_WAITS = [5, 15, 30]  # seconds between attempts

SYSTEM_PROMPT = """\
EtherCAT ENI config assistant. Call get_slaves before any change. \
Use exact slave IDs from tool results — never guess. \
For PDO edits call get_slave_details first, then match the target entry by its index field value — not by position or name. \
PDO index values use the format #xNNNN (e.g. #x2033, #x6041). \
When the user gives a hex value like 0x2051 always convert it to #x2051 format before passing to tools. Never pass decimal. \
Confirm before removing slaves. Summarize changes after. \
Drive types in this project: DR3247A-10/48-E, DR3247B-30/48-E, DEN-NET-E, CAP-NET-E, GX-JC06-H, LAN9255, SE1. \
NEVER call set_active_pdo — the active PDO mapping must never be changed.\
"""

# Tools in OpenAI/Groq format (type + function wrapper)
def _fn(name: str, desc: str, props: dict, required: list) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": required}}}

_sid = {"slave_id": {"type": "string"}}
_pdo_common = {**_sid, "pdo_type": {"type": "string", "enum": ["tx", "rx"]}, "pdo_idx": {"type": "integer"}}

TOOLS = [
    _fn("get_slaves",        "List all slaves with key properties.",                   {}, []),
    _fn("get_slave_details", "Full slave details including all PDO entries.",          _sid, ["slave_id"]),
    _fn("get_operations",    "Session change log.",                                    {}, []),
    _fn("toggle_slave",      "Enable or disable a slave (disabled = excluded from export).",
        {**_sid, "enabled": {"type": "boolean"}}, ["slave_id", "enabled"]),
    _fn("remove_slave",      "Permanently remove slave. Prefer toggle if reversibility needed.",
        _sid, ["slave_id"]),
    _fn("reorder_slaves",    "Reorder chain. Provide all slave IDs in new order.",
        {"slave_ids": {"type": "array", "items": {"type": "string"}}}, ["slave_ids"]),
    _fn("edit_slave_property", "Edit one slave field.",
        {**_sid,
         "field": {"type": "string", "enum": ["name", "vendor_id", "product_code", "revision_no", "serial_no", "physics"]},
         "value": {}},
        ["slave_id", "field", "value"]),
    _fn("edit_pdo_entry", "Edit one field of a PDO entry.",
        {**_pdo_common,
         "entry_idx": {"type": "integer"},
         "field": {"type": "string", "enum": ["index", "subindex", "bit_len", "name", "data_type"]},
         "value": {}},
        ["slave_id", "pdo_type", "pdo_idx", "entry_idx", "field", "value"]),
    _fn("add_pdo_entry", "Append a new entry to a PDO.",
        {**_pdo_common,
         "index": {"type": "string"},
         "subindex": {"type": "string"},
         "bit_len": {"type": "integer"},
         "name": {"type": "string"},
         "data_type": {"type": "string", "enum": ["BOOL", "SINT", "INT", "DINT", "USINT", "UINT", "UDINT", "REAL", "LREAL"]}},
        ["slave_id", "pdo_type", "pdo_idx", "index", "bit_len", "name", "data_type"]),
    _fn("remove_pdo_entry", "Remove a PDO entry by index.",
        {**_pdo_common, "entry_idx": {"type": "integer"}},
        ["slave_id", "pdo_type", "pdo_idx", "entry_idx"]),
    _fn("duplicate_slave", "Copy a slave and insert it after the original.", _sid, ["slave_id"]),
]


def is_available() -> bool:
    """Check if the AI assistant can be used (API key set, SDK installed)."""
    from backend.engine.config_store import get_groq_api_key
    if not get_groq_api_key():
        return False
    try:
        import groq  # noqa: F401
        return True
    except ImportError:
        return False


class AIAssistant:
    """Groq-powered assistant that operates on the ENI config through tools."""

    MAX_ITERATIONS = 15

    def __init__(self, app_state: Any):
        from backend.engine.config_store import get_groq_api_key, get_model
        self.state = app_state
        self.conversation_history: list[dict] = []
        self.model = get_model()

        import groq
        self.client = groq.Groq(api_key=get_groq_api_key())

    def _call_api(self, messages: list[dict]) -> Any:
        """Call the Groq API with exponential backoff on rate-limit errors."""
        import groq

        for attempt, wait in enumerate([0] + _RETRY_WAITS):
            if wait:
                logger.warning(f"Rate limited by Groq. Retrying in {wait}s (attempt {attempt + 1})...")
                time.sleep(wait)
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )
            except groq.RateLimitError:
                if attempt == len(_RETRY_WAITS):
                    raise
                continue

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the JSON result string."""
        from backend.engine.recalculator import recalculate
        from backend.models.eni_model import PdoEntry, Slave

        config = self.state.config
        if config is None and tool_name != "get_operations":
            return json.dumps({"error": "No ENI file loaded."})

        try:
            if tool_name == "get_slaves":
                return json.dumps([s.to_summary() for s in config.slaves])

            elif tool_name == "get_slave_details":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": f"Slave {tool_input['slave_id']} not found"})
                summary = slave.to_summary()
                pd = slave.process_data
                summary["tx_pdos"] = [
                    {
                        "arr_idx": i, "index": pdo.index, "name": pdo.name,
                        "is_active": pdo.sm is not None,
                        "total_bit_length": pdo.total_bit_length,
                        "entries": [
                            {"idx": j, "index": e.index, "subindex": e.subindex,
                             "bit_len": e.bit_len, "name": e.name, "data_type": e.data_type}
                            for j, e in enumerate(pdo.entries)
                        ],
                    }
                    for i, pdo in enumerate(pd.tx_pdos)
                ]
                summary["rx_pdos"] = [
                    {
                        "arr_idx": i, "index": pdo.index, "name": pdo.name,
                        "is_active": pdo.sm is not None,
                        "total_bit_length": pdo.total_bit_length,
                        "entries": [
                            {"idx": j, "index": e.index, "subindex": e.subindex,
                             "bit_len": e.bit_len, "name": e.name, "data_type": e.data_type}
                            for j, e in enumerate(pdo.entries)
                        ],
                    }
                    for i, pdo in enumerate(pd.rx_pdos)
                ]
                return json.dumps(summary)

            elif tool_name == "get_operations":
                return json.dumps({
                    "operations": self.state.op_log.get_operations(),
                    "summary": self.state.op_log.get_summary(),
                })

            elif tool_name == "toggle_slave":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                slave.enabled = tool_input["enabled"]
                self.state.op_log.log_toggle_slave(slave.id, slave.info.name, slave.enabled)
                recalculate(config)
                return json.dumps({"ok": True, "name": slave.info.name, "enabled": slave.enabled})

            elif tool_name == "remove_slave":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                idx = config.slaves.index(slave)
                name = slave.info.name
                config.slaves.remove(slave)
                self.state.op_log.log_remove_slave(slave.id, name, idx)
                recalculate(config)
                return json.dumps({"ok": True, "removed": name, "remaining": len(config.slaves)})

            elif tool_name == "reorder_slaves":
                id_map = {s.id: s for s in config.slaves}
                new_list = []
                for sid in tool_input["slave_ids"]:
                    if sid not in id_map:
                        return json.dumps({"error": f"Unknown slave id: {sid}"})
                    new_list.append(id_map[sid])
                remaining = [s for s in config.slaves if s.id not in set(tool_input["slave_ids"])]
                config.slaves = new_list + remaining
                self.state.op_log.log_reorder(tool_input["slave_ids"])
                recalculate(config)
                return json.dumps({"ok": True, "new_order": [s.info.name for s in config.slaves]})

            elif tool_name == "edit_slave_property":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                field = tool_input["field"]
                value = tool_input["value"]
                if field in ("vendor_id", "product_code", "revision_no", "serial_no"):
                    value = int(value)
                old_val = getattr(slave.info, field)
                setattr(slave.info, field, value)
                self.state.op_log.log_edit_slave_info(slave.id, field, old_val, value, slave_name=slave.info.name)
                recalculate(config)
                return json.dumps({"ok": True, "name": slave.info.name, "field": field, "old": str(old_val), "new": str(value)})

            elif tool_name == "edit_pdo_entry":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                pdos = slave.process_data.tx_pdos if tool_input["pdo_type"] == "tx" else slave.process_data.rx_pdos
                pdo_idx = tool_input["pdo_idx"]
                if pdo_idx < 0 or pdo_idx >= len(pdos):
                    return json.dumps({"error": "PDO index out of range"})
                pdo = pdos[pdo_idx]
                entry_idx = tool_input["entry_idx"]
                if entry_idx < 0 or entry_idx >= len(pdo.entries):
                    return json.dumps({"error": "Entry index out of range"})
                entry = pdo.entries[entry_idx]
                field = tool_input["field"]
                value = int(tool_input["value"]) if field == "bit_len" else tool_input["value"]
                old_val = getattr(entry, field)
                setattr(entry, field, value)
                self.state.op_log.log_edit_pdo_entry(slave.id, tool_input["pdo_type"], pdo.index, entry_idx, field, old_val, value, slave_name=slave.info.name, entry_name=entry.name)
                recalculate(config)
                return json.dumps({"ok": True, "entry": entry.name, "field": field, "old": str(old_val), "new": str(value)})

            elif tool_name == "add_pdo_entry":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                pdos = slave.process_data.tx_pdos if tool_input["pdo_type"] == "tx" else slave.process_data.rx_pdos
                pdo_idx = tool_input["pdo_idx"]
                if pdo_idx < 0 or pdo_idx >= len(pdos):
                    return json.dumps({"error": "PDO index out of range"})
                pdo = pdos[pdo_idx]
                new_entry = PdoEntry(
                    index=tool_input["index"],
                    subindex=tool_input.get("subindex", "0"),
                    bit_len=int(tool_input["bit_len"]),
                    name=tool_input["name"],
                    data_type=tool_input["data_type"],
                )
                pdo.entries.append(new_entry)
                self.state.op_log.log_add_pdo_entry(slave.id, tool_input["pdo_type"], pdo.index, slave_name=slave.info.name, entry_name=new_entry.name)
                recalculate(config)
                return json.dumps({"ok": True, "added": new_entry.name, "to_pdo": pdo.index})

            elif tool_name == "remove_pdo_entry":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                pdos = slave.process_data.tx_pdos if tool_input["pdo_type"] == "tx" else slave.process_data.rx_pdos
                pdo_idx = tool_input["pdo_idx"]
                if pdo_idx < 0 or pdo_idx >= len(pdos):
                    return json.dumps({"error": "PDO index out of range"})
                pdo = pdos[pdo_idx]
                entry_idx = tool_input["entry_idx"]
                if entry_idx < 0 or entry_idx >= len(pdo.entries):
                    return json.dumps({"error": "Entry index out of range"})
                removed = pdo.entries.pop(entry_idx)
                self.state.op_log.log_remove_pdo_entry(slave.id, tool_input["pdo_type"], pdo.index, entry_idx, slave_name=slave.info.name, entry_name=removed.name)
                recalculate(config)
                return json.dumps({"ok": True, "removed": removed.name, "from_pdo": pdo.index})

            elif tool_name == "duplicate_slave":
                source = self._find_slave(tool_input["slave_id"])
                if not source:
                    return json.dumps({"error": "Slave not found"})
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
                self.state.op_log.log_duplicate_slave(source.id, new_slave.id, slave_name=source.info.name)
                recalculate(config)
                return json.dumps({"ok": True, "new_id": new_slave.id, "name": new_slave.info.name})

            elif tool_name == "set_active_pdo":
                slave = self._find_slave(tool_input["slave_id"])
                if not slave:
                    return json.dumps({"error": "Slave not found"})
                pdos = slave.process_data.tx_pdos if tool_input["pdo_type"] == "tx" else slave.process_data.rx_pdos
                default_sm = "3" if tool_input["pdo_type"] == "tx" else "2"
                pdo_idx = tool_input["pdo_idx"]
                if pdo_idx < 0 or pdo_idx >= len(pdos):
                    return json.dumps({"error": "PDO index out of range"})
                current_sm = next((p.sm for p in pdos if p.sm is not None), None)
                sm_val = current_sm or default_sm
                for p in pdos:
                    p.sm = None
                pdos[pdo_idx].sm = sm_val
                self.state.op_log.record("set_active_pdo", slave_id=slave.id, pdo_type=tool_input["pdo_type"], pdo_index=pdos[pdo_idx].index)
                recalculate(config)
                return json.dumps({"ok": True, "active_pdo": pdos[pdo_idx].index})

            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

        except Exception as e:
            logger.exception(f"Tool execution error: {tool_name}")
            return json.dumps({"error": str(e)})

    def _find_slave(self, slave_id: str) -> Optional[Any]:
        if self.state.config is None:
            return None
        for s in self.state.config.slaves:
            if s.id == slave_id:
                return s
        return None

    def chat(self, user_message: str) -> dict:
        """
        Process a user message and return the AI response.

        Returns:
            dict with keys:
                - response: str
                - actions: list[dict]
                - error: str | None
        """
        import groq as groq_module

        self.conversation_history.append({"role": "user", "content": user_message})
        messages = list(self.conversation_history)
        actions_taken = []

        for _ in range(self.MAX_ITERATIONS):
            try:
                response = self._call_api(messages)
            except groq_module.RateLimitError as e:
                error_msg = "Rate limit reached. Please wait a moment and try again."
                self.conversation_history.append({"role": "assistant", "content": error_msg})
                return {"response": error_msg, "actions": actions_taken, "error": str(e)}
            except Exception as e:
                logger.exception("Groq API error")
                error_msg = f"AI service error: {e}"
                self.conversation_history.append({"role": "assistant", "content": error_msg})
                return {"response": error_msg, "actions": actions_taken, "error": str(e)}

            choice = response.choices[0]
            finish_reason = choice.finish_reason

            if finish_reason == "stop":
                assistant_text = choice.message.content or ""
                self.conversation_history.append({"role": "assistant", "content": assistant_text})
                return {"response": assistant_text, "actions": actions_taken, "error": None}

            if finish_reason == "tool_calls":
                # Add assistant turn with tool_calls to messages
                messages.append({
                    "role": "assistant",
                    "content": choice.message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in choice.message.tool_calls
                    ],
                })

                # Execute each tool and collect results
                for tc in choice.message.tool_calls:
                    tool_input = json.loads(tc.function.arguments)
                    logger.info(f"AI tool call: {tc.function.name}({tc.function.arguments[:200]})")
                    result_str = self._execute_tool(tc.function.name, tool_input)
                    actions_taken.append({
                        "tool": tc.function.name,
                        "input": tool_input,
                        "result_preview": result_str[:300],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
                continue

            # Unexpected finish reason
            assistant_text = choice.message.content or "I completed the request."
            self.conversation_history.append({"role": "assistant", "content": assistant_text})
            return {"response": assistant_text, "actions": actions_taken, "error": None}

        fallback = "I've reached the maximum number of steps. Please check the current state and let me know if you need more changes."
        self.conversation_history.append({"role": "assistant", "content": fallback})
        return {"response": fallback, "actions": actions_taken, "error": None}

    def clear_history(self) -> None:
        self.conversation_history.clear()
