using System.Data.SQLite;
using DaocProgress;

const string Usage = """
    Usage (from the server folder, with the server stopped):
      ./daoc-progress upgrade
          Move this server's saved progress into the world this build ships (defaults/world.sqlite):
          accounts (with their roles), characters, items, money, houses, guilds and bots. This
          install's settings (edition, population, options, XP rates) are kept.
      ./daoc-progress import <folder or .db> --replace-progress
          Replace this server's progress with the progress of another save: an older server folder,
          or a Windows Offline DAoC folder (the one containing runtime/). This server keeps its own
          world and settings. The source is only read.
      ./daoc-progress inspect <folder or .db>
          Show what a save contains. Changes nothing.

    Options:
      --leave-sluaghbinder-bots   when this server runs without the custom class: bring every other
                                  bot and leave Sluaghbinder bots (and the items they carry) behind.

    Every run backs up the current save to data/progress-backups/<time>/ first (with
    import-report.txt). To undo: stop the server, copy that folder's opendaoc.sqlite3.db back to data/.
    """;

string home = Environment.GetEnvironmentVariable("DAOC_HOME") is { Length: > 0 } configured
    ? Path.GetFullPath(configured)
    : Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, ".."));
string[] knownFlags = ["--leave-sluaghbinder-bots", "--replace-progress"];
var flags = args.Where(a => a.StartsWith("--", StringComparison.Ordinal)).ToHashSet();
var words = args.Where(a => !a.StartsWith("--", StringComparison.Ordinal)).ToList();
if (flags.Except(knownFlags).Any() || words.Count == 0)
    return Fail(2, Usage);
bool leaveBots = flags.Contains("--leave-sluaghbinder-bots");

try
{
    switch (words[0], words.Count)
    {
        case ("inspect", 2):
        {
            var s = ImportEngine.InspectCopy(ImportEngine.LocateSave(words[1]));
            Console.WriteLine($"{s.Database}\n  {s.Accounts} account(s), {s.Characters} character(s), {s.Bots} bot(s), {s.InventoryItems} inventory entries" +
                (s.SluaghbinderCharacters + s.SluaghbinderBots > 0 ? $"\n  Sluaghbinder: {s.SluaghbinderCharacters} character(s), {s.SluaghbinderBots} bot(s)" : ""));
            return 0;
        }
        case ("upgrade", 1):
            return Report(ImportEngine.Run(home, Path.Combine(home, "data", ImportEngine.SaveFile), upgrade: true, Console.WriteLine, leaveBots));
        case ("import", 2):
            if (!flags.Contains("--replace-progress"))
                return Fail(2, "import replaces this server's saved progress. Add --replace-progress to confirm (a backup is made first).");
            return Report(ImportEngine.Run(home, ImportEngine.LocateSave(words[1]), upgrade: false, Console.WriteLine, leaveBots));
        default:
            return Fail(2, Usage);
    }
}
catch (Exception e) when (e is InvalidOperationException or InvalidDataException or IOException or UnauthorizedAccessException or SQLiteException)
{
    return Fail(1, "daoc-progress: " + e.Message);
}

static int Report(ImportResult result)
{
    foreach (string note in result.Notes) Console.WriteLine("  " + note);
    Console.WriteLine($"Done. Report: {Path.Combine(result.BackupFolder, "import-report.txt")}");
    return 0;
}

static int Fail(int code, string message)
{
    Console.Error.WriteLine(message);
    return code;
}
