"""
Data model for EtherCAT Network Information (ENI) files.

Uses a hybrid approach: key editable fields are modeled explicitly as dataclasses,
while complex subsections (InitCmds, Mailbox internals) are preserved as raw lxml
Elements for lossless round-tripping.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree


@dataclass
class PdoEntry:
    index: str
    subindex: str
    bit_len: int
    name: str
    data_type: str
    comment: Optional[str] = None
    depend_on_slot: bool = False


@dataclass
class PdoMapping:
    index: str
    name: str
    sm: Optional[str] = None
    fixed: Optional[str] = None
    entries: list[PdoEntry] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    depend_on_slot: bool = False

    @property
    def total_bit_length(self) -> int:
        return sum(e.bit_len for e in self.entries)


@dataclass
class SyncManager:
    index: int
    sm_type: str
    default_size: Optional[int] = None
    start_address: Optional[int] = None
    control_byte: Optional[int] = None
    enable: Optional[int] = None
    pdo: Optional[int] = None


@dataclass
class ProcessDataOffsets:
    bit_start: int = 0
    bit_length: int = 0


@dataclass
class ProcessData:
    send: Optional[ProcessDataOffsets] = None
    recv: Optional[ProcessDataOffsets] = None
    sync_managers: list[SyncManager] = field(default_factory=list)
    tx_pdos: list[PdoMapping] = field(default_factory=list)
    rx_pdos: list[PdoMapping] = field(default_factory=list)

    @property
    def active_tx_pdo(self) -> Optional[PdoMapping]:
        for pdo in self.tx_pdos:
            if pdo.sm is not None:
                return pdo
        return self.tx_pdos[0] if self.tx_pdos else None

    @property
    def active_rx_pdo(self) -> Optional[PdoMapping]:
        for pdo in self.rx_pdos:
            if pdo.sm is not None:
                return pdo
        return self.rx_pdos[0] if self.rx_pdos else None

    @property
    def tx_bit_length(self) -> int:
        pdo = self.active_tx_pdo
        return pdo.total_bit_length if pdo else 0

    @property
    def rx_bit_length(self) -> int:
        pdo = self.active_rx_pdo
        return pdo.total_bit_length if pdo else 0


@dataclass
class SlaveInfo:
    name: str
    phys_addr: int
    auto_inc_addr: int
    physics: str
    vendor_id: int
    product_code: int
    revision_no: int
    serial_no: int = 0
    identification: Optional[etree._Element] = None


@dataclass
class PreviousPort:
    port: str
    phys_addr: int
    selected: bool = True


@dataclass
class Slave:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    info: SlaveInfo = field(default_factory=lambda: SlaveInfo("", 0, 0, "", 0, 0, 0))
    process_data: ProcessData = field(default_factory=ProcessData)
    previous_port: Optional[PreviousPort] = None
    enabled: bool = True

    mailbox_raw: Optional[etree._Element] = None
    init_cmds_raw: Optional[etree._Element] = None

    @property
    def display_name(self) -> str:
        return self.info.name

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.info.name,
            "phys_addr": self.info.phys_addr,
            "auto_inc_addr": self.info.auto_inc_addr,
            "vendor_id": self.info.vendor_id,
            "product_code": self.info.product_code,
            "revision_no": self.info.revision_no,
            "serial_no": self.info.serial_no,
            "physics": self.info.physics,
            "enabled": self.enabled,
            "has_tx_pdo": len(self.process_data.tx_pdos) > 0,
            "has_rx_pdo": len(self.process_data.rx_pdos) > 0,
            "tx_bit_length": self.process_data.tx_bit_length,
            "rx_bit_length": self.process_data.rx_bit_length,
        }


@dataclass
class ProcessImageVariable:
    name: str
    data_type: str
    bit_size: int
    bit_offs: int
    comment: Optional[str] = None


@dataclass
class ProcessImage:
    inputs_byte_size: int = 0
    outputs_byte_size: int = 0
    input_variables: list[ProcessImageVariable] = field(default_factory=list)
    output_variables: list[ProcessImageVariable] = field(default_factory=list)


@dataclass
class CyclicCmd:
    states: list[str] = field(default_factory=list)
    comment: str = ""
    cmd: int = 0
    addr: Optional[int] = None
    adp: Optional[int] = None
    ado: Optional[int] = None
    data_length: int = 0
    cnt: Optional[int] = None
    input_offs: int = 0
    output_offs: int = 0


@dataclass
class CyclicFrame:
    commands: list[CyclicCmd] = field(default_factory=list)


@dataclass
class CyclicConfig:
    comment: str = ""
    cycle_time: int = 1000
    priority: int = 1
    task_id: int = 2
    frames: list[CyclicFrame] = field(default_factory=list)


@dataclass
class MasterInfo:
    name: str = ""
    destination: str = ""
    source: str = ""
    ether_type: str = ""


@dataclass
class Master:
    info: MasterInfo = field(default_factory=MasterInfo)
    mailbox_start_addr: int = 0
    mailbox_count: int = 0
    eoe_max_ports: int = 0
    eoe_max_frames: int = 0
    eoe_max_macs: int = 0
    init_cmds_raw: Optional[etree._Element] = None


@dataclass
class EniConfig:
    """Top-level ENI configuration container."""
    version: str = "1.3"
    master: Master = field(default_factory=Master)
    slaves: list[Slave] = field(default_factory=list)
    cyclic: CyclicConfig = field(default_factory=CyclicConfig)
    process_image: ProcessImage = field(default_factory=ProcessImage)

    root_attribs: dict = field(default_factory=dict)

    @property
    def enabled_slaves(self) -> list[Slave]:
        return [s for s in self.slaves if s.enabled]
