# NrUnpack

Extracts selected folders (`chr/`, `parts/`, `map/`, ...) from a Nightreign install's encrypted archives into loose
files, so Stan's Tools can import characters, weapons and maps without UXM. It only reads the game folder: it never
patches the executable, so the game stays playable online.

Users never run this by hand: **Stan's Tools → Setup → Unpack Nightreign Files** downloads the published exe from
this repo's GitHub release and runs it (see `stan_tools/nr_unpack.py`).

```
NrUnpack --game "<...>\ELDEN RING NIGHTREIGN\Game" --out <folder> --include chr/ --include parts/ [--skip-existing] [--dry-run]
```

Output lines for callers: `TOTAL <files>`, `BYTES <bytes still to write>`, `PROGRESS <done> <total>`,
`DONE <written> <skipped> <errors>`. `--dry-run` stops after `BYTES`. Exit code 3 means some files failed.

## Building and publishing

Needs the .NET 9 SDK and a Smithbox clone (Andre.IO, MIT; pinned at `854818a37`).

```powershell
dotnet publish -c Release -o publish -p:SmithboxDir=S:\Smithbox
gh release create nr-unpack-v<version> publish\NrUnpack.exe THIRD-PARTY-NOTICES.txt --repo team-cereus/soulstruct-blender
```

Then update `UNPACKER_VERSION`, `UNPACKER_SHA256` in `io_soulstruct/soulstruct/blender/stan_tools/nr_unpack.py`
(Blender verifies the download against it). Bump `<Version>` in `NrUnpack.csproj` for every new release.
