"""
Exporter for EtherCAT Network Information (ENI) XML files.

Serializes the EniConfig data model back to valid ENI XML. Preserves
raw XML subtrees (InitCmds, Mailbox) for lossless round-tripping
on sections that weren't edited.
"""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from backend.models.eni_model import (
    CyclicCmd,
    CyclicConfig,
    CyclicFrame,
    EniConfig,
    Master,
    PdoEntry,
    PdoMapping,
    ProcessData,
    ProcessImage,
    ProcessImageVariable,
    Slave,
    SyncManager,
)


def _sub(parent: etree._Element, tag: str, text: str | None = None, **attribs) -> etree._Element:
    el = etree.SubElement(parent, tag, **attribs)
    if text is not None:
        el.text = str(text)
    return el


def _sub_cdata(parent: etree._Element, tag: str, text: str) -> etree._Element:
    el = etree.SubElement(parent, tag)
    el.text = text
    return el


def build_pdo_entry(parent: etree._Element, entry: PdoEntry) -> None:
    entry_el = _sub(parent, "Entry")
    idx_el = _sub(entry_el, "Index", entry.index)
    if entry.depend_on_slot:
        idx_el.set("DependOnSlot", "true")
    _sub(entry_el, "SubIndex", entry.subindex)
    _sub(entry_el, "BitLen", str(entry.bit_len))
    _sub(entry_el, "Name", entry.name)
    if entry.comment:
        _sub(entry_el, "Comment", entry.comment)
    _sub(entry_el, "DataType", entry.data_type)


def build_pdo(parent: etree._Element, pdo: PdoMapping, tag: str) -> None:
    attribs = {}
    if pdo.sm is not None:
        attribs["Sm"] = pdo.sm
    if pdo.fixed is not None:
        attribs["Fixed"] = pdo.fixed

    pdo_el = _sub(parent, tag, **attribs)

    idx_el = _sub(pdo_el, "Index", pdo.index)
    if pdo.depend_on_slot:
        idx_el.set("DependOnSlot", "true")

    _sub(pdo_el, "Name", pdo.name)

    for exc in pdo.excludes:
        _sub(pdo_el, "Exclude", exc)

    for entry in pdo.entries:
        build_pdo_entry(pdo_el, entry)


def build_sync_manager(parent: etree._Element, sm: SyncManager) -> None:
    sm_el = _sub(parent, f"Sm{sm.index}")
    _sub(sm_el, "Type", sm.sm_type)
    if sm.default_size is not None:
        _sub(sm_el, "DefaultSize", str(sm.default_size))
    if sm.start_address is not None:
        _sub(sm_el, "StartAddress", str(sm.start_address))
    if sm.control_byte is not None:
        _sub(sm_el, "ControlByte", str(sm.control_byte))
    if sm.enable is not None:
        _sub(sm_el, "Enable", str(sm.enable))
    if sm.pdo is not None:
        _sub(sm_el, "Pdo", str(sm.pdo))


def build_process_data(parent: etree._Element, pd: ProcessData) -> None:
    has_content = (
        pd.send is not None
        or pd.recv is not None
        or pd.sync_managers
        or pd.tx_pdos
        or pd.rx_pdos
    )

    pd_el = _sub(parent, "ProcessData")
    if not has_content:
        return

    if pd.send is not None:
        send_el = _sub(pd_el, "Send")
        _sub(send_el, "BitStart", str(pd.send.bit_start))
        _sub(send_el, "BitLength", str(pd.send.bit_length))

    if pd.recv is not None:
        recv_el = _sub(pd_el, "Recv")
        _sub(recv_el, "BitStart", str(pd.recv.bit_start))
        _sub(recv_el, "BitLength", str(pd.recv.bit_length))

    for sm in pd.sync_managers:
        build_sync_manager(pd_el, sm)

    for pdo in pd.tx_pdos:
        build_pdo(pd_el, pdo, "TxPdo")

    for pdo in pd.rx_pdos:
        build_pdo(pd_el, pdo, "RxPdo")


def build_slave_info(parent: etree._Element, slave: Slave) -> None:
    info_el = _sub(parent, "Info")
    _sub(info_el, "Name", slave.info.name)
    _sub(info_el, "PhysAddr", str(slave.info.phys_addr))
    _sub(info_el, "AutoIncAddr", str(slave.info.auto_inc_addr))

    if slave.info.identification is not None:
        info_el.append(copy.deepcopy(slave.info.identification))

    _sub(info_el, "Physics", slave.info.physics)
    _sub(info_el, "VendorId", str(slave.info.vendor_id))
    _sub(info_el, "ProductCode", str(slave.info.product_code))
    _sub(info_el, "RevisionNo", str(slave.info.revision_no))
    _sub(info_el, "SerialNo", str(slave.info.serial_no))


def build_slave(parent: etree._Element, slave: Slave) -> None:
    slave_el = _sub(parent, "Slave")

    build_slave_info(slave_el, slave)
    build_process_data(slave_el, slave.process_data)

    if slave.mailbox_raw is not None:
        slave_el.append(copy.deepcopy(slave.mailbox_raw))

    if slave.init_cmds_raw is not None:
        slave_el.append(copy.deepcopy(slave.init_cmds_raw))

    if slave.previous_port is not None:
        pp_el = _sub(slave_el, "PreviousPort")
        if slave.previous_port.selected:
            pp_el.set("Selected", "true")
        _sub(pp_el, "Port", slave.previous_port.port)
        _sub(pp_el, "PhysAddr", str(slave.previous_port.phys_addr))


def build_master(parent: etree._Element, master: Master) -> None:
    master_el = _sub(parent, "Master")

    info_el = _sub(master_el, "Info")
    _sub(info_el, "Name", master.info.name)
    _sub(info_el, "Destination", master.info.destination)
    _sub(info_el, "Source", master.info.source)
    _sub(info_el, "EtherType", master.info.ether_type)

    mbs_el = _sub(master_el, "MailboxStates")
    _sub(mbs_el, "StartAddr", str(master.mailbox_start_addr))
    _sub(mbs_el, "Count", str(master.mailbox_count))

    eoe_el = _sub(master_el, "EoE")
    _sub(eoe_el, "MaxPorts", str(master.eoe_max_ports))
    _sub(eoe_el, "MaxFrames", str(master.eoe_max_frames))
    _sub(eoe_el, "MaxMACs", str(master.eoe_max_macs))

    if master.init_cmds_raw is not None:
        master_el.append(copy.deepcopy(master.init_cmds_raw))


def build_cyclic_cmd(parent: etree._Element, cmd: CyclicCmd) -> None:
    cmd_el = _sub(parent, "Cmd")
    for state in cmd.states:
        _sub(cmd_el, "State", state)
    if cmd.comment:
        _sub(cmd_el, "Comment", cmd.comment)
    _sub(cmd_el, "Cmd", str(cmd.cmd))

    if cmd.addr is not None:
        _sub(cmd_el, "Addr", str(cmd.addr))
    if cmd.adp is not None:
        _sub(cmd_el, "Adp", str(cmd.adp))
    if cmd.ado is not None:
        _sub(cmd_el, "Ado", str(cmd.ado))

    _sub(cmd_el, "DataLength", str(cmd.data_length))

    if cmd.cnt is not None:
        _sub(cmd_el, "Cnt", str(cmd.cnt))

    _sub(cmd_el, "InputOffs", str(cmd.input_offs))
    _sub(cmd_el, "OutputOffs", str(cmd.output_offs))


def build_cyclic(parent: etree._Element, cyclic: CyclicConfig) -> None:
    cyclic_el = _sub(parent, "Cyclic")

    if cyclic.comment:
        _sub(cyclic_el, "Comment", cyclic.comment)
    _sub(cyclic_el, "CycleTime", str(cyclic.cycle_time))
    _sub(cyclic_el, "Priority", str(cyclic.priority))
    _sub(cyclic_el, "TaskId", str(cyclic.task_id))

    for frame in cyclic.frames:
        frame_el = _sub(cyclic_el, "Frame")
        for cmd in frame.commands:
            build_cyclic_cmd(frame_el, cmd)


def build_process_image(parent: etree._Element, pi: ProcessImage) -> None:
    pi_el = _sub(parent, "ProcessImage")

    if pi.input_variables:
        inputs_el = _sub(pi_el, "Inputs")
        _sub(inputs_el, "ByteSize", str(pi.inputs_byte_size))
        for var in pi.input_variables:
            var_el = _sub(inputs_el, "Variable")
            _sub(var_el, "Name", var.name)
            if var.comment:
                _sub(var_el, "Comment", var.comment)
            _sub(var_el, "DataType", var.data_type)
            _sub(var_el, "BitSize", str(var.bit_size))
            _sub(var_el, "BitOffs", str(var.bit_offs))

    if pi.output_variables:
        outputs_el = _sub(pi_el, "Outputs")
        _sub(outputs_el, "ByteSize", str(pi.outputs_byte_size))
        for var in pi.output_variables:
            var_el = _sub(outputs_el, "Variable")
            _sub(var_el, "Name", var.name)
            if var.comment:
                _sub(var_el, "Comment", var.comment)
            _sub(var_el, "DataType", var.data_type)
            _sub(var_el, "BitSize", str(var.bit_size))
            _sub(var_el, "BitOffs", str(var.bit_offs))


def export_eni(config: EniConfig) -> str:
    """Export EniConfig to an ENI XML string."""
    root = etree.Element("EtherCATConfig")

    for key, value in config.root_attribs.items():
        root.set(key, value)
    if "Version" not in config.root_attribs:
        root.set("Version", config.version)

    config_el = _sub(root, "Config")

    build_master(config_el, config.master)

    for slave in config.enabled_slaves:
        build_slave(config_el, slave)

    build_cyclic(config_el, config.cyclic)
    build_process_image(config_el, config.process_image)

    etree.indent(root, space="\t")

    xml_bytes = etree.tostring(
        root,
        xml_declaration=True,
        encoding="utf-8",
        pretty_print=True,
    )
    return xml_bytes.decode("utf-8")


def export_eni_to_file(config: EniConfig, filepath: str | Path) -> None:
    """Export EniConfig to an ENI XML file."""
    xml_str = export_eni(config)
    Path(filepath).write_text(xml_str, encoding="utf-8")
