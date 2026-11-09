"""Regenerate `general/character_names/eclipse.json`: display names for Nightreign Eclipse's own characters (ports).

Source: the Eclipse port roster `souls-script-kt/scripts/tools/castle-variants/config/ports.tsv` (one row per ported
NpcParam variant: name, NR model). A model with several variants gets their shared base name ('Lothric Knight
(Spear)' -> 'Lothric Knight') or the first two names. `EXTRA` covers retired ports no longer in the roster.

    python tools/gen_eclipse_names.py [path/to/ports.tsv]
"""
import collections
import csv
import json
import re
import sys
from pathlib import Path

DEFAULT_ROSTER = Path(r"S:\souls-script-kt\scripts\tools\castle-variants\config\ports.tsv")
OUT = Path(__file__).resolve().parent.parent / "io_soulstruct/soulstruct/blender/general/character_names/eclipse.json"
EXTRA = {  # retired or roster-less ports (eclipse-trash-mobs.md)
    9860: "Hollow (DS1)",
    9874: "Ariandel Wolf (retired)",
    9875: "Skittish Wolf (retired)",
    9891: "Basilisk (DS3, retired)",
}
SKIP = {0}  # c0000 is the human body every human NPC uses, not a port


def main():
    roster = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROSTER
    lines = (line for line in roster.read_text(encoding="utf-8").splitlines() if not line.startswith("#"))
    by_chr = collections.defaultdict(list)
    for row in csv.DictReader(lines, delimiter="\t"):
        chr_id, name = (row.get("chr") or "").strip(), (row.get("name") or "").strip()
        if re.fullmatch(r"c\d{4}", chr_id) and name and int(chr_id[1:]) not in SKIP:
            by_chr[int(chr_id[1:])].append(name)
    names = {}
    for chr_id, variants in by_chr.items():
        bases = list(dict.fromkeys(re.sub(r"\s*\(.*?\)\s*$", "", n) for n in variants))
        names[chr_id] = bases[0] if len(bases) == 1 else " / ".join(bases[:2]) + (" / ..." if len(bases) > 2 else "")
    for chr_id, name in EXTRA.items():
        names.setdefault(chr_id, name)
    OUT.write_text(json.dumps({str(k): names[k] for k in sorted(names)}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {len(names)} names to {OUT}")


if __name__ == "__main__":
    main()
