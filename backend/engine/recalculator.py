"""
Recalculation engine for ENI configurations.

When slaves are added, removed, or reordered, this module recalculates
all cascading addresses, offsets, and references to produce a valid ENI.
"""

from __future__ import annotations

import struct

from lxml import etree

from backend.models.eni_model import (
    CyclicCmd,
    CyclicFrame,
    EniConfig,
    PreviousPort,
    ProcessImage,
    ProcessImageVariable,
    Slave,
)


def _patch_adp_in_init_cmds(init_cmds: etree._Element, old_addr: int, new_addr: int) -> None:
    """Replace all <Adp> values matching old_addr with new_addr in InitCmds."""
    if old_addr == new_addr:
        return
    for adp_el in init_cmds.iter("Adp"):
        try:
            if int(adp_el.text.strip()) == old_addr:
                adp_el.text = str(new_addr)
        except (ValueError, AttributeError):
            pass


def _patch_fmmu_logical_addr(
    init_cmds: etree._Element,
    fmmu_type: str,
    new_logical_addr: int,
) -> None:
    """
    Patch the logical start address in FMMU setup InitCmd data.

    FMMU data is a 16-byte hex string where bytes 0-3 are the
    logical start address (little-endian).

    fmmu_type: substring to match in Comment (e.g. "fmmu 0" for outputs, "fmmu 1" for inputs)
    """
    for init_cmd in init_cmds.findall("InitCmd"):
        comment_el = init_cmd.find("Comment")
        if comment_el is None or comment_el.text is None:
            continue

        comment = comment_el.text.strip().lower()
        if f"set {fmmu_type}" not in comment:
            continue

        data_el = init_cmd.find("Data")
        if data_el is None or data_el.text is None:
            continue

        hex_data = data_el.text.strip()
        if len(hex_data) != 32:
            continue

        raw = bytes.fromhex(hex_data)
        addr_bytes = struct.pack("<I", new_logical_addr)
        patched = addr_bytes + raw[4:]
        data_el.text = patched.hex()


def _compute_process_data_layout(slaves: list[Slave]) -> dict[str, dict]:
    """
    Compute the process data bit layout for enabled slaves.

    Returns a dict keyed by slave.id with:
      - send_bit_start: bit offset for RxPdo (master sends to slave)
      - send_bit_length: bit length of RxPdo
      - recv_bit_start: bit offset for TxPdo (slave sends to master)
      - recv_bit_length: bit length of TxPdo
      - send_byte_offset: byte offset within the logical process data region
      - recv_byte_offset: byte offset within the logical process data region
    """
    layout = {}

    send_bit_cursor = 0
    recv_bit_cursor = 0
    first_slave_with_send = True
    first_slave_with_recv = True

    for slave in slaves:
        pd = slave.process_data
        entry = {
            "send_bit_start": 0,
            "send_bit_length": 0,
            "recv_bit_start": 0,
            "recv_bit_length": 0,
            "send_byte_offset": 0,
            "recv_byte_offset": 0,
        }

        if pd.send is not None and pd.send.bit_length > 0:
            if first_slave_with_send:
                send_bit_cursor = pd.send.bit_start
                first_slave_with_send = False

            entry["send_bit_start"] = send_bit_cursor
            entry["send_bit_length"] = pd.send.bit_length
            entry["send_byte_offset"] = send_bit_cursor // 8
            send_bit_cursor += pd.send.bit_length

        if pd.recv is not None and pd.recv.bit_length > 0:
            if first_slave_with_recv:
                recv_bit_cursor = pd.recv.bit_start
                first_slave_with_recv = False

            entry["recv_bit_start"] = recv_bit_cursor
            entry["recv_bit_length"] = pd.recv.bit_length
            entry["recv_byte_offset"] = recv_bit_cursor // 8
            recv_bit_cursor += pd.recv.bit_length

        layout[slave.id] = entry

    return layout


def _rebuild_process_image(slaves: list[Slave], layout: dict) -> ProcessImage:
    """Rebuild the ProcessImage from the current slave layout."""
    pi = ProcessImage()
    input_vars: list[ProcessImageVariable] = []
    output_vars: list[ProcessImageVariable] = []

    for slave in slaves:
        slave_layout = layout.get(slave.id, {})
        pd = slave.process_data

        active_tx = pd.active_tx_pdo
        if active_tx and slave_layout.get("recv_bit_length", 0) > 0:
            bit_cursor = slave_layout["recv_bit_start"]
            for entry in active_tx.entries:
                input_vars.append(ProcessImageVariable(
                    name=f"{slave.info.name}.{active_tx.name}.{entry.name}",
                    data_type=entry.data_type,
                    bit_size=entry.bit_len,
                    bit_offs=bit_cursor,
                    comment=entry.comment,
                ))
                bit_cursor += entry.bit_len

        active_rx = pd.active_rx_pdo
        if active_rx and slave_layout.get("send_bit_length", 0) > 0:
            bit_cursor = slave_layout["send_bit_start"]
            for entry in active_rx.entries:
                output_vars.append(ProcessImageVariable(
                    name=f"{slave.info.name}.{active_rx.name}.{entry.name}",
                    data_type=entry.data_type,
                    bit_size=entry.bit_len,
                    bit_offs=bit_cursor,
                    comment=entry.comment,
                ))
                bit_cursor += entry.bit_len

    pi.input_variables = input_vars
    pi.output_variables = output_vars

    if input_vars:
        max_bit = max(v.bit_offs + v.bit_size for v in input_vars)
        pi.inputs_byte_size = (max_bit + 7) // 8
    if output_vars:
        max_bit = max(v.bit_offs + v.bit_size for v in output_vars)
        pi.outputs_byte_size = (max_bit + 7) // 8

    return pi


def _rebuild_cyclic(
    config: EniConfig,
    layout: dict,
    total_send_bytes: int,
    total_recv_bytes: int,
) -> None:
    """Update cyclic frame data lengths and offsets."""
    data_length = max(total_send_bytes, total_recv_bytes)
    if data_length == 0:
        return

    slave_count = len(config.enabled_slaves)

    for frame in config.cyclic.frames:
        for cmd in frame.commands:
            if cmd.cmd == 12 and cmd.addr is not None:
                cmd.data_length = data_length
                cmd.cnt = slave_count * 3


def recalculate(config: EniConfig) -> None:
    """
    Recalculate all addresses and offsets in the ENI config.

    This is the main entry point after any modification (reorder, remove,
    edit PDOs, etc.). It updates:
      - PhysAddr / AutoIncAddr sequencing
      - ProcessData Send/Recv BitStart offsets
      - InitCmd Adp patching
      - FMMU logical address patching
      - PreviousPort topology
      - Cyclic frame data lengths
      - ProcessImage variable offsets
      - Master mailbox count
    """
    enabled = config.enabled_slaves

    for i, slave in enumerate(enabled):
        old_phys = slave.info.phys_addr
        new_phys = 1001 + i

        if i == 0:
            new_auto_inc = 0
        else:
            new_auto_inc = 65536 - i

        slave.info.phys_addr = new_phys
        slave.info.auto_inc_addr = new_auto_inc

        if slave.init_cmds_raw is not None:
            _patch_adp_in_init_cmds(slave.init_cmds_raw, old_phys, new_phys)

    layout = _compute_process_data_layout(enabled)

    base_logical_addr = 0x01000000

    for slave in enabled:
        sl = layout.get(slave.id, {})

        if slave.process_data.send is not None:
            slave.process_data.send.bit_start = sl.get("send_bit_start", 0)
        if slave.process_data.recv is not None:
            slave.process_data.recv.bit_start = sl.get("recv_bit_start", 0)

        if slave.init_cmds_raw is not None:
            send_byte_off = sl.get("send_byte_offset", 0)
            recv_byte_off = sl.get("recv_byte_offset", 0)

            fmmu_byte_offset = min(
                send_byte_off if sl.get("send_bit_length", 0) > 0 else 999999,
                recv_byte_off if sl.get("recv_bit_length", 0) > 0 else 999999,
            )
            if fmmu_byte_offset == 999999:
                fmmu_byte_offset = 0

            header_bytes = 0
            if enabled.index(slave) == 0 and slave.process_data.send is not None:
                header_bytes = slave.process_data.send.bit_start // 8

            logical_addr = base_logical_addr + fmmu_byte_offset - header_bytes

            _patch_fmmu_logical_addr(slave.init_cmds_raw, "fmmu 0", logical_addr)
            _patch_fmmu_logical_addr(slave.init_cmds_raw, "fmmu 1", logical_addr)

    for i, slave in enumerate(enabled):
        if i == 0:
            slave.previous_port = None
        else:
            prev_slave = enabled[i - 1]
            port = "B"
            if prev_slave.info.physics and len(prev_slave.info.physics) >= 4:
                for pi, ch in enumerate(prev_slave.info.physics):
                    if ch == "Y" and pi > 0:
                        port = chr(ord("A") + pi)
                        break
                else:
                    port = "B"

            slave.previous_port = PreviousPort(
                port=port,
                phys_addr=prev_slave.info.phys_addr,
                selected=True,
            )

    total_send_bits = 0
    total_recv_bits = 0
    for slave in enabled:
        sl = layout.get(slave.id, {})
        total_send_bits += sl.get("send_bit_length", 0)
        total_recv_bits += sl.get("recv_bit_length", 0)

    total_send_bytes = (total_send_bits + 7) // 8
    total_recv_bytes = (total_recv_bits + 7) // 8

    config.process_image = _rebuild_process_image(enabled, layout)

    _rebuild_cyclic(config, layout, total_send_bytes, total_recv_bytes)

    has_mailbox = sum(1 for s in enabled if s.mailbox_raw is not None)
    config.master.mailbox_count = has_mailbox * 2 if has_mailbox else 0
    config.master.eoe_max_ports = len(enabled) + 5
