"""
Integration test for ENI Juggler.

Tests the full pipeline: parse → modify → recalculate → export → verify.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.parser.eni_parser import parse_eni_file
from backend.parser.eni_exporter import export_eni
from backend.engine.recalculator import recalculate
from backend.engine.operation_log import OperationLog
from lxml import etree


def test_parse_all_files():
    """Test that all ENI files parse without errors."""
    eni_dir = Path("eni_files")
    files = list(eni_dir.glob("*.xml"))
    assert len(files) > 0, "No ENI files found"

    parsed = 0
    skipped = 0
    for f in files:
        print(f"  Parsing {f.name}...", end=" ")
        try:
            config = parse_eni_file(f)
            assert len(config.slaves) > 0, f"No slaves in {f.name}"
            print(f"OK ({len(config.slaves)} slaves)")
            parsed += 1
        except ValueError as e:
            if "ESI" in str(e):
                print(f"SKIPPED (ESI file, not ENI)")
                skipped += 1
            else:
                raise

    print(f"  {parsed} ENI files parsed, {skipped} ESI files skipped.")


def test_round_trip_small():
    """Test parse→export→reparse on the small eni.xml file."""
    config = parse_eni_file("eni_files/eni.xml")
    assert len(config.slaves) == 2

    xml_out = export_eni(config)
    assert "EtherCATConfig" in xml_out
    assert "<Slave>" in xml_out

    root = etree.fromstring(xml_out.encode("utf-8"))
    slaves = root.findall(".//Slave")
    assert len(slaves) == 2, f"Expected 2 slaves, got {len(slaves)}"
    print("  Round-trip OK for eni.xml (2 slaves)")


def test_remove_slave():
    """Test removing a slave and verifying recalculation."""
    config = parse_eni_file("eni_files/eni.xml")
    original_count = len(config.slaves)
    assert original_count == 2

    removed = config.slaves.pop(1)
    recalculate(config)

    assert len(config.enabled_slaves) == 1
    assert config.slaves[0].info.phys_addr == 1001
    assert config.slaves[0].info.auto_inc_addr == 0

    xml_out = export_eni(config)
    root = etree.fromstring(xml_out.encode("utf-8"))
    slaves = root.findall(".//Slave")
    assert len(slaves) == 1
    print(f"  Remove slave OK: removed '{removed.info.name}', 1 remaining")


def test_disable_slave():
    """Test disabling a slave (excluded from export)."""
    config = parse_eni_file("eni_files/eni.xml")
    config.slaves[1].enabled = False
    recalculate(config)

    assert len(config.slaves) == 2
    assert len(config.enabled_slaves) == 1

    xml_out = export_eni(config)
    root = etree.fromstring(xml_out.encode("utf-8"))
    slaves = root.findall(".//Slave")
    assert len(slaves) == 1, f"Expected 1 slave in export, got {len(slaves)}"
    print("  Disable slave OK: 2 slaves, 1 enabled, 1 in export")


def test_reorder_slaves():
    """Test reordering slaves."""
    config = parse_eni_file("eni_files/eni.xml")
    s0_name = config.slaves[0].info.name
    s1_name = config.slaves[1].info.name

    config.slaves.reverse()
    recalculate(config)

    assert config.slaves[0].info.name == s1_name
    assert config.slaves[1].info.name == s0_name
    assert config.slaves[0].info.phys_addr == 1001
    assert config.slaves[1].info.phys_addr == 1002
    assert config.slaves[0].info.auto_inc_addr == 0
    assert config.slaves[1].info.auto_inc_addr == 65535

    xml_out = export_eni(config)
    root = etree.fromstring(xml_out.encode("utf-8"))
    first_name = root.find(".//Slave/Info/Name").text
    assert first_name == s1_name
    print(f"  Reorder OK: {s1_name} now first, {s0_name} second")


def test_edit_slave_properties():
    """Test editing slave vendor/product codes."""
    config = parse_eni_file("eni_files/eni.xml")
    slave = config.slaves[0]

    old_vendor = slave.info.vendor_id
    slave.info.vendor_id = 9999
    slave.info.product_code = 12345

    recalculate(config)

    xml_out = export_eni(config)
    assert "9999" in xml_out
    assert "12345" in xml_out
    print(f"  Edit properties OK: vendor {old_vendor}→9999, product→12345")


def test_edit_pdo_entry():
    """Test modifying a PDO entry."""
    config = parse_eni_file("eni_files/eni.xml")
    slave = config.slaves[0]

    tx_pdos = slave.process_data.tx_pdos
    assert len(tx_pdos) > 0, "No TxPDOs"

    active_pdo = tx_pdos[0]
    assert len(active_pdo.entries) > 0, "No entries in first TxPDO"

    entry = active_pdo.entries[0]
    old_name = entry.name
    entry.name = "Modified_Status_Word"
    entry.bit_len = 32

    recalculate(config)

    xml_out = export_eni(config)
    assert "Modified_Status_Word" in xml_out
    print(f"  Edit PDO entry OK: '{old_name}' → 'Modified_Status_Word', 16→32 bits")


def test_large_file():
    """Test with the large 4ne1V2.xml file."""
    config = parse_eni_file("eni_files/4ne1V2.xml")
    n_slaves = len(config.slaves)
    print(f"  Large file: {n_slaves} slaves parsed")

    removed = config.slaves.pop(5)
    recalculate(config)

    for i, s in enumerate(config.enabled_slaves):
        assert s.info.phys_addr == 1001 + i, f"Slave {i} PhysAddr wrong: {s.info.phys_addr}"

    xml_out = export_eni(config)
    root = etree.fromstring(xml_out.encode("utf-8"))
    slaves = root.findall(".//Slave")
    assert len(slaves) == n_slaves - 1
    print(f"  Large file: removed '{removed.info.name}', {len(slaves)} remaining, addresses OK")


def test_process_image_regeneration():
    """Test that ProcessImage is correctly regenerated."""
    config = parse_eni_file("eni_files/eni.xml")
    recalculate(config)

    pi = config.process_image
    assert len(pi.input_variables) > 0, "No input variables in ProcessImage"
    assert len(pi.output_variables) > 0, "No output variables in ProcessImage"

    for var in pi.input_variables:
        assert var.bit_offs >= 0
        assert var.bit_size > 0
        assert var.name

    for var in pi.output_variables:
        assert var.bit_offs >= 0
        assert var.bit_size > 0

    print(f"  ProcessImage OK: {len(pi.input_variables)} inputs, {len(pi.output_variables)} outputs")


def test_operation_log():
    """Test operation logging."""
    log = OperationLog()
    log.log_load("test.xml", 5)
    log.log_remove_slave("id1", "Drive1", 0)
    log.log_reorder(["id2", "id3"])
    log.log_edit_slave_info("id2", "vendor_id", 100, 200)

    ops = log.get_operations()
    assert len(ops) == 4

    summary = log.get_summary()
    assert summary["total_operations"] == 4
    print(f"  OperationLog OK: {summary['total_operations']} ops recorded")


def test_duplicate_slave():
    """Test slave duplication."""
    import copy
    config = parse_eni_file("eni_files/eni.xml")
    original_count = len(config.slaves)
    source = config.slaves[0]

    from backend.models.eni_model import Slave
    import uuid
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
    config.slaves.insert(1, new_slave)

    recalculate(config)

    assert len(config.slaves) == original_count + 1
    assert config.slaves[1].info.name.endswith("_copy")
    assert config.slaves[0].info.phys_addr == 1001
    assert config.slaves[1].info.phys_addr == 1002
    assert config.slaves[2].info.phys_addr == 1003

    xml_out = export_eni(config)
    root = etree.fromstring(xml_out.encode("utf-8"))
    slaves = root.findall(".//Slave")
    assert len(slaves) == original_count + 1
    print(f"  Duplicate OK: {original_count} → {original_count + 1} slaves")


if __name__ == "__main__":
    tests = [
        ("Parse all files", test_parse_all_files),
        ("Round-trip small", test_round_trip_small),
        ("Remove slave", test_remove_slave),
        ("Disable slave", test_disable_slave),
        ("Reorder slaves", test_reorder_slaves),
        ("Edit properties", test_edit_slave_properties),
        ("Edit PDO entry", test_edit_pdo_entry),
        ("Large file", test_large_file),
        ("ProcessImage regeneration", test_process_image_regeneration),
        ("Operation log", test_operation_log),
        ("Duplicate slave", test_duplicate_slave),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        print(f"\n[TEST] {name}")
        try:
            func()
            passed += 1
            print(f"  ✓ PASSED")
        except Exception as e:
            failed += 1
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")

    if failed > 0:
        sys.exit(1)
