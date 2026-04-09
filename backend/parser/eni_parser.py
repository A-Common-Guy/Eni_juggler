"""
Parser for EtherCAT Network Information (ENI) XML files.

Converts ENI XML into the EniConfig data model. Uses lxml for robust
XML handling. Preserves raw XML subtrees for InitCmds and Mailbox
sections to enable lossless round-tripping.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from lxml import etree

from backend.models.eni_model import (
    CyclicCmd,
    CyclicConfig,
    CyclicFrame,
    EniConfig,
    Master,
    MasterInfo,
    PdoEntry,
    PdoMapping,
    PreviousPort,
    ProcessData,
    ProcessDataOffsets,
    ProcessImage,
    ProcessImageVariable,
    Slave,
    SlaveInfo,
    SyncManager,
)


def _strip_namespaces(root: etree._Element) -> None:
    """Remove all namespace prefixes from element tags for uniform parsing."""
    for el in root.iter():
        if isinstance(el.tag, str) and "{" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        for key in list(el.attrib):
            if "{" in key:
                val = el.attrib.pop(key)
                new_key = key.split("}", 1)[1]
                el.attrib[new_key] = val


def _text(el: Optional[etree._Element], default: str = "") -> str:
    if el is None:
        return default
    return (el.text or "").strip()


def _int(el: Optional[etree._Element], default: int = 0) -> int:
    txt = _text(el)
    if not txt:
        return default
    return int(txt)


def _find(parent: etree._Element, tag: str) -> Optional[etree._Element]:
    return parent.find(tag)


def _find_text(parent: etree._Element, tag: str, default: str = "") -> str:
    return _text(parent.find(tag), default)


def _find_int(parent: etree._Element, tag: str, default: int = 0) -> int:
    return _int(parent.find(tag), default)


def parse_pdo_entry(entry_el: etree._Element) -> PdoEntry:
    index_el = entry_el.find("Index")
    depend = False
    if index_el is not None:
        depend = index_el.get("DependOnSlot", "").lower() == "true"

    return PdoEntry(
        index=_text(index_el),
        subindex=_find_text(entry_el, "SubIndex"),
        bit_len=_find_int(entry_el, "BitLen"),
        name=_find_text(entry_el, "Name"),
        data_type=_find_text(entry_el, "DataType"),
        comment=_find_text(entry_el, "Comment") or None,
        depend_on_slot=depend,
    )


def parse_pdo(pdo_el: etree._Element) -> PdoMapping:
    index_el = pdo_el.find("Index")
    depend = False
    if index_el is not None:
        depend = index_el.get("DependOnSlot", "").lower() == "true"

    entries = [parse_pdo_entry(e) for e in pdo_el.findall("Entry")]
    excludes = [_text(e) for e in pdo_el.findall("Exclude")]

    return PdoMapping(
        index=_text(index_el),
        name=_find_text(pdo_el, "Name"),
        sm=pdo_el.get("Sm"),
        fixed=pdo_el.get("Fixed"),
        entries=entries,
        excludes=excludes,
        depend_on_slot=depend,
    )


def parse_sync_manager(sm_el: etree._Element, index: int) -> SyncManager:
    return SyncManager(
        index=index,
        sm_type=_find_text(sm_el, "Type"),
        default_size=_find_int(sm_el, "DefaultSize") or None,
        start_address=_find_int(sm_el, "StartAddress") or None,
        control_byte=_find_int(sm_el, "ControlByte") or None,
        enable=_find_int(sm_el, "Enable") or None,
        pdo=_find_int(sm_el, "Pdo") or None,
    )


def parse_process_data(pd_el: Optional[etree._Element]) -> ProcessData:
    if pd_el is None:
        return ProcessData()

    pd = ProcessData()

    send_el = pd_el.find("Send")
    if send_el is not None:
        pd.send = ProcessDataOffsets(
            bit_start=_find_int(send_el, "BitStart"),
            bit_length=_find_int(send_el, "BitLength"),
        )

    recv_el = pd_el.find("Recv")
    if recv_el is not None:
        pd.recv = ProcessDataOffsets(
            bit_start=_find_int(recv_el, "BitStart"),
            bit_length=_find_int(recv_el, "BitLength"),
        )

    for i in range(8):
        sm_el = pd_el.find(f"Sm{i}")
        if sm_el is not None:
            pd.sync_managers.append(parse_sync_manager(sm_el, i))

    for txpdo_el in pd_el.findall("TxPdo"):
        pd.tx_pdos.append(parse_pdo(txpdo_el))

    for rxpdo_el in pd_el.findall("RxPdo"):
        pd.rx_pdos.append(parse_pdo(rxpdo_el))

    return pd


def parse_slave_info(info_el: etree._Element) -> SlaveInfo:
    ident_el = info_el.find("Identification")

    return SlaveInfo(
        name=_find_text(info_el, "Name"),
        phys_addr=_find_int(info_el, "PhysAddr"),
        auto_inc_addr=_find_int(info_el, "AutoIncAddr"),
        physics=_find_text(info_el, "Physics"),
        vendor_id=_find_int(info_el, "VendorId"),
        product_code=_find_int(info_el, "ProductCode"),
        revision_no=_find_int(info_el, "RevisionNo"),
        serial_no=_find_int(info_el, "SerialNo"),
        identification=copy.deepcopy(ident_el) if ident_el is not None else None,
    )


def parse_previous_port(pp_el: Optional[etree._Element]) -> Optional[PreviousPort]:
    if pp_el is None:
        return None
    return PreviousPort(
        port=_find_text(pp_el, "Port"),
        phys_addr=_find_int(pp_el, "PhysAddr"),
        selected=pp_el.get("Selected", "").lower() == "true",
    )


def parse_slave(slave_el: etree._Element) -> Slave:
    slave = Slave()

    info_el = slave_el.find("Info")
    if info_el is not None:
        slave.info = parse_slave_info(info_el)

    slave.process_data = parse_process_data(slave_el.find("ProcessData"))
    slave.previous_port = parse_previous_port(slave_el.find("PreviousPort"))

    mb_el = slave_el.find("Mailbox")
    if mb_el is not None:
        slave.mailbox_raw = copy.deepcopy(mb_el)

    ic_el = slave_el.find("InitCmds")
    if ic_el is not None:
        slave.init_cmds_raw = copy.deepcopy(ic_el)

    return slave


def parse_master(master_el: etree._Element) -> Master:
    master = Master()

    info_el = master_el.find("Info")
    if info_el is not None:
        master.info = MasterInfo(
            name=_find_text(info_el, "Name"),
            destination=_find_text(info_el, "Destination"),
            source=_find_text(info_el, "Source"),
            ether_type=_find_text(info_el, "EtherType"),
        )

    mbs_el = master_el.find("MailboxStates")
    if mbs_el is not None:
        master.mailbox_start_addr = _find_int(mbs_el, "StartAddr")
        master.mailbox_count = _find_int(mbs_el, "Count")

    eoe_el = master_el.find("EoE")
    if eoe_el is not None:
        master.eoe_max_ports = _find_int(eoe_el, "MaxPorts")
        master.eoe_max_frames = _find_int(eoe_el, "MaxFrames")
        master.eoe_max_macs = _find_int(eoe_el, "MaxMACs")

    ic_el = master_el.find("InitCmds")
    if ic_el is not None:
        master.init_cmds_raw = copy.deepcopy(ic_el)

    return master


def parse_cyclic_cmd(cmd_el: etree._Element) -> CyclicCmd:
    return CyclicCmd(
        states=[_text(s) for s in cmd_el.findall("State")],
        comment=_find_text(cmd_el, "Comment"),
        cmd=_find_int(cmd_el, "Cmd"),
        addr=_find_int(cmd_el, "Addr") if cmd_el.find("Addr") is not None else None,
        adp=_find_int(cmd_el, "Adp") if cmd_el.find("Adp") is not None else None,
        ado=_find_int(cmd_el, "Ado") if cmd_el.find("Ado") is not None else None,
        data_length=_find_int(cmd_el, "DataLength"),
        cnt=_find_int(cmd_el, "Cnt") if cmd_el.find("Cnt") is not None else None,
        input_offs=_find_int(cmd_el, "InputOffs"),
        output_offs=_find_int(cmd_el, "OutputOffs"),
    )


def parse_cyclic(cyclic_el: Optional[etree._Element]) -> CyclicConfig:
    if cyclic_el is None:
        return CyclicConfig()

    config = CyclicConfig(
        comment=_find_text(cyclic_el, "Comment"),
        cycle_time=_find_int(cyclic_el, "CycleTime", 1000),
        priority=_find_int(cyclic_el, "Priority", 1),
        task_id=_find_int(cyclic_el, "TaskId", 2),
    )

    for frame_el in cyclic_el.findall("Frame"):
        frame = CyclicFrame()
        for cmd_el in frame_el.findall("Cmd"):
            frame.commands.append(parse_cyclic_cmd(cmd_el))
        config.frames.append(frame)

    return config


def parse_process_image(pi_el: Optional[etree._Element]) -> ProcessImage:
    if pi_el is None:
        return ProcessImage()

    pi = ProcessImage()

    inputs_el = pi_el.find("Inputs")
    if inputs_el is not None:
        pi.inputs_byte_size = _find_int(inputs_el, "ByteSize")
        for var_el in inputs_el.findall("Variable"):
            pi.input_variables.append(ProcessImageVariable(
                name=_find_text(var_el, "Name"),
                data_type=_find_text(var_el, "DataType"),
                bit_size=_find_int(var_el, "BitSize"),
                bit_offs=_find_int(var_el, "BitOffs"),
                comment=_find_text(var_el, "Comment") or None,
            ))

    outputs_el = pi_el.find("Outputs")
    if outputs_el is not None:
        pi.outputs_byte_size = _find_int(outputs_el, "ByteSize")
        for var_el in outputs_el.findall("Variable"):
            pi.output_variables.append(ProcessImageVariable(
                name=_find_text(var_el, "Name"),
                data_type=_find_text(var_el, "DataType"),
                bit_size=_find_int(var_el, "BitSize"),
                bit_offs=_find_int(var_el, "BitOffs"),
                comment=_find_text(var_el, "Comment") or None,
            ))

    return pi


def parse_eni_file(filepath: str | Path) -> EniConfig:
    """Parse an ENI XML file into an EniConfig data model."""
    tree = etree.parse(str(filepath))
    root = tree.getroot()
    _strip_namespaces(root)

    config = EniConfig()
    config.version = root.get("Version", "1.3")
    config.root_attribs = dict(root.attrib)

    config_el = root.find("Config")
    if config_el is None:
        root_tag = root.tag if isinstance(root.tag, str) else str(root.tag)
        if "Info" in root_tag:
            raise ValueError(
                "This appears to be an ESI (EtherCAT Slave Information) file, "
                "not an ENI (EtherCAT Network Information) file. "
                "ENI files have <EtherCATConfig> as the root element."
            )
        raise ValueError("No <Config> element found in ENI file")

    master_el = config_el.find("Master")
    if master_el is not None:
        config.master = parse_master(master_el)

    for slave_el in config_el.findall("Slave"):
        config.slaves.append(parse_slave(slave_el))

    config.cyclic = parse_cyclic(config_el.find("Cyclic"))
    config.process_image = parse_process_image(config_el.find("ProcessImage"))

    return config


def parse_eni_string(xml_content: str) -> EniConfig:
    """Parse ENI XML from a string."""
    root = etree.fromstring(xml_content.encode("utf-8"))
    _strip_namespaces(root)

    config = EniConfig()
    config.version = root.get("Version", "1.3")
    config.root_attribs = dict(root.attrib)

    config_el = root.find("Config")
    if config_el is None:
        raise ValueError("No <Config> element found in ENI file")

    master_el = config_el.find("Master")
    if master_el is not None:
        config.master = parse_master(master_el)

    for slave_el in config_el.findall("Slave"):
        config.slaves.append(parse_slave(slave_el))

    config.cyclic = parse_cyclic(config_el.find("Cyclic"))
    config.process_image = parse_process_image(config_el.find("ProcessImage"))

    return config
