// Extracts selected folders (chr/, parts/, ...) from a Nightreign install's encrypted BHD/BDT archives into loose files,
// for Stan's Tools. Read-only on the game folder: it never patches the executable. Progress lines for Blender:
//   TOTAL <n>          files that match the includes
//   BYTES <b>          bytes still to write (with --dry-run, nothing else happens)
//   PROGRESS <done> <n>
//   DONE <written> <skipped> <errors>
//   PARAMS <written>   with --params: <out>/regulation-bin/<name>.param.xml files written from regulation.bin
// `--regulation <file> --out <folder>` writes only those params, from any regulation.bin (e.g. a mod's), and needs no
// game folder.
using System.Globalization;
using System.Reflection;
using System.Xml;
using Andre.IO.VFS;
using Andre.Core;
using SoulsFormats;

static int Usage()
{
    Console.Error.WriteLine(
        "Usage: NrUnpack --game <Nightreign Game folder> --out <folder> --include <prefix> [--include ...] [--skip-existing]\n" +
        "       NrUnpack --regulation <regulation.bin> --out <folder>   (params only)\n" +
        "Example: NrUnpack --game \"C:\\...\\ELDEN RING NIGHTREIGN\\Game\" --out D:\\nr-unpack --include chr/ --include parts/");
    return 1;
}

static string NormalizeVfs(string path) => path.Replace('\\', '/').TrimStart('/').ToLowerInvariant();

// Writes the params Stan's Tools reads as Witchy-style XML rows (the add-on only looks at <row> attributes). Every
// field is written, including default values, which Witchy would omit.
static int ExportParams(string regulationPath, string outDir, string workDir)
{
    var assembly = Assembly.GetExecutingAssembly();
    var destDir = Path.Combine(outDir, "regulation-bin");
    Directory.CreateDirectory(destDir);
    var written = 0;
    foreach (var file in SFUtil.DecryptNightreignRegulation(regulationPath).Files)
    {
        var name = Path.GetFileNameWithoutExtension(file.Name);
        using var defStream = assembly.GetManifestResourceStream($"ParamDefs.{name}.xml");
        if (defStream is null)
            continue;  // not a param the add-on reads
        var defPath = Path.Combine(workDir, $"{name}.paramdef.xml");
        using (var defFile = File.Create(defPath))
            defStream.CopyTo(defFile);
        var param = PARAM.Read(file.Bytes);
        param.ApplyParamdef(PARAMDEF.XmlDeserialize(defPath));

        var settings = new XmlWriterSettings { Indent = true, IndentChars = "", CheckCharacters = false };
        using var writer = XmlWriter.Create(Path.Combine(destDir, $"{name}.param.xml"), settings);
        writer.WriteStartElement("param");
        writer.WriteStartElement("rows");
        foreach (var row in param.Rows)
        {
            writer.WriteStartElement("row");
            writer.WriteAttributeString("id", row.ID.ToString(CultureInfo.InvariantCulture));
            foreach (var cell in row.Cells)
            {
                if (cell.Def.DisplayType == PARAMDEF.DefType.dummy8 || cell.Value is byte[])
                    continue;
                var value = Convert.ToString(cell.Value, CultureInfo.InvariantCulture) ?? "";
                writer.WriteAttributeString(cell.Def.InternalName, value);
            }
            writer.WriteEndElement();
        }
        writer.WriteEndElement();
        writer.WriteEndElement();
        written++;
    }
    return written;
}

string? gameDir = null, outDir = null, regulationPath = null;
var includes = new List<string>();
bool skipExisting = false, dryRun = false, exportParams = false;
for (var i = 0; i < args.Length; i++)
{
    switch (args[i].ToLowerInvariant())
    {
        case "--game" when i + 1 < args.Length: gameDir = args[++i]; break;
        case "--out" when i + 1 < args.Length: outDir = args[++i]; break;
        case "--include" when i + 1 < args.Length: includes.Add(NormalizeVfs(args[++i])); break;
        case "--skip-existing": skipExisting = true; break;
        case "--dry-run": dryRun = true; break;  // only print TOTAL and BYTES (still to write), e.g. for a disk check
        case "--params": exportParams = true; break;  // also write regulation-bin/*.param.xml
        case "--regulation" when i + 1 < args.Length: regulationPath = args[++i]; break;
        default: return Usage();
    }
}
if (regulationPath is not null)
{
    if (outDir is null || gameDir is not null || includes.Count > 0)
        return Usage();
    if (!File.Exists(regulationPath))
    {
        Console.Error.WriteLine($"regulation.bin not found: {regulationPath}");
        return 2;
    }
    var paramsWorkDir = Path.Combine(Path.GetTempPath(), "NrUnpack");
    Directory.CreateDirectory(paramsWorkDir);
    try
    {
        Console.WriteLine($"PARAMS {ExportParams(Path.GetFullPath(regulationPath), Path.GetFullPath(outDir), paramsWorkDir)}");
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"ERROR regulation.bin: {ex.Message}");
        return 3;
    }
    Console.WriteLine("DONE 0 0 0");
    return 0;
}
if (gameDir is null || outDir is null || includes.Count == 0)
    return Usage();
if (!Directory.Exists(gameDir))
{
    Console.Error.WriteLine($"Game folder not found: {gameDir}");
    return 2;
}

// Andre.IO reads the file-name dictionary from "Assets/UXM Dictionaries" relative to the working directory.
var workDir = Path.Combine(Path.GetTempPath(), "NrUnpack");
var dictionaryDir = Path.Combine(workDir, "Assets", "UXM Dictionaries");
Directory.CreateDirectory(dictionaryDir);
using (var resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("EldenRingNightreignDictionary.txt")!)
using (var file = File.Create(Path.Combine(dictionaryDir, "EldenRingNightreignDictionary.txt")))
    resource.CopyTo(file);
gameDir = Path.GetFullPath(gameDir);
outDir = Path.GetFullPath(outDir);
Directory.SetCurrentDirectory(workDir);

int written = 0, skipped = 0, errors = 0;
using (var vfs = ArchiveBinderVirtualFileSystem.FromGameFolder(gameDir, Game.NR))
{
    var matched = vfs.FileHeaders
        .Where(h => includes.Any(inc => NormalizeVfs(h.Item1).StartsWith(inc, StringComparison.Ordinal)))
        .ToList();
    string DestPath(string vfsPath) =>
        Path.Combine(outDir, vfsPath.TrimStart('/', '\\').Replace('/', Path.DirectorySeparatorChar));
    var bytesToWrite = matched
        .Where(h => !(skipExisting && File.Exists(DestPath(h.Item1))))
        .Sum(h => (long)h.Item2.PaddedFileSize);
    Console.WriteLine($"TOTAL {matched.Count}");
    Console.WriteLine($"BYTES {bytesToWrite}");
    if (dryRun)
        return 0;
    var done = 0;
    foreach (var (vfsPath, _) in matched)
    {
        var destPath = DestPath(vfsPath);
        try
        {
            if (skipExisting && File.Exists(destPath))
                skipped++;
            else
            {
                Directory.CreateDirectory(Path.GetDirectoryName(destPath)!);
                // Nightreign BHD5 UnpaddedFileSize is 0, so keep the padded size the reader returns.
                File.WriteAllBytes(destPath, vfs.ReadFileOrThrow(vfsPath).ToArray());
                written++;
            }
        }
        catch (Exception ex)
        {
            errors++;
            Console.Error.WriteLine($"ERROR {vfsPath}: {ex.Message}");
            if (errors > 50)
            {
                Console.Error.WriteLine("Too many errors; stopping.");
                break;
            }
        }
        if (++done % 25 == 0 || done == matched.Count)
            Console.WriteLine($"PROGRESS {done} {matched.Count}");
    }
}
if (exportParams)
{
    try
    {
        Console.WriteLine($"PARAMS {ExportParams(Path.Combine(gameDir, "regulation.bin"), outDir, workDir)}");
    }
    catch (Exception ex)
    {
        errors++;
        Console.Error.WriteLine($"ERROR regulation.bin: {ex.Message}");
    }
}
Console.WriteLine($"DONE {written} {skipped} {errors}");
return errors > 0 ? 3 : 0;
