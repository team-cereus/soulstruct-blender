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


_wap = _load_module("wep_absorp_param", "wep_absorp_param.py")
hand_bone_from_disp_pos_type = _wap.hand_bone_from_disp_pos_type
WepAbsorpRow = _wap.WepAbsorpRow
_load_xml_rows = _wap._load_xml_rows


def test_hand_bone_from_disp_pos_type():
    assert hand_bone_from_disp_pos_type(0) == "R_Hand"
    assert hand_bone_from_disp_pos_type(1) == "L_Hand"
    assert hand_bone_from_disp_pos_type(3) == "R_Hand"


def test_parse_wep_absorp_xml_rows(tmp_path):
    xml = tmp_path / "WepAbsorpPosParam.param.xml"
    xml.write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <PARAMMETA>
              <Rows>
                <row id="100" right_0="42" dispPosType_right_0="1" isSkeletonBind="1" />
                <row id="200" right_0="-1" dispPosType_right_0="0" isSkeletonBind="0" />
              </Rows>
            </PARAMMETA>
            """
        ),
        encoding="utf-8",
    )
    rows = _load_xml_rows(str(xml), xml.stat().st_mtime_ns)
    assert rows[100] == WepAbsorpRow(
        row_id=100,
        right_0=42,
        disp_pos_type_right_0=1,
        is_skeleton_bind=True,
    )
    assert rows[200].right_0 == -1
    assert rows[200].disp_pos_type_right_0 == 0
    assert hand_bone_from_disp_pos_type(rows[200].disp_pos_type_right_0) == "R_Hand"
    assert hand_bone_from_disp_pos_type(rows[100].disp_pos_type_right_0) == "L_Hand"
