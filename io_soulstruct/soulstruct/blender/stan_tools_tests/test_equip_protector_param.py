from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path


def _load_module(name: str, filename: str):
    path = Path(__file__).resolve().parents[1] / "stan_tools" / filename
    qual = f"stan_tools_{name}_test"
    spec = importlib.util.spec_from_file_location(qual, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)
    return mod


_epp = _load_module("equip_protector_param", "equip_protector_param.py")
protector_stem_for_row = _epp.protector_stem_for_row
_load_xml_rows = _epp._load_xml_rows


def test_protector_stem_head_male():
    row = {"equipModelId": 1500, "headEquip": 1}
    assert protector_stem_for_row(row, female=False) == "hd_m_1500"


def test_protector_stem_body_male():
    row = {"equipModelId": 1501, "bodyEquip": 1}
    assert protector_stem_for_row(row, female=False) == "bd_m_1501"


def test_protector_stem_arm_female():
    row = {"equipModelId": 1500, "armEquip": 1}
    assert protector_stem_for_row(row, female=True) == "am_f_1500"


def test_protector_stem_leg_male():
    row = {"equipModelId": 1500, "legEquip": 1}
    assert protector_stem_for_row(row, female=False) == "lg_m_1500"


def test_protector_stem_no_slot_flag():
    row = {"equipModelId": 1500}
    assert protector_stem_for_row(row, female=False) is None


def test_protector_stem_missing_equip_model_id():
    row = {"headEquip": 1}
    assert protector_stem_for_row(row, female=False) is None


def test_load_xml_rows_parses_protector_row(tmp_path):
    xml = tmp_path / "EquipParamProtector.param.xml"
    xml.write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <PARAMMETA>
              <Rows>
                <row id="980000" equipModelId="1500" headEquip="1" bodyEquip="0" armEquip="0" legEquip="0" />
              </Rows>
            </PARAMMETA>
            """
        ),
        encoding="utf-8",
    )
    rows = _load_xml_rows(str(xml), xml.stat().st_mtime_ns)
    assert rows[980000]["equipModelId"] == 1500
    assert rows[980000]["headEquip"] == 1
