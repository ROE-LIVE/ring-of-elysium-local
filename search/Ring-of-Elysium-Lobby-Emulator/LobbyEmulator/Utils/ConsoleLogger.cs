using System;

namespace LobbyEmulator.Utils
{
  public static class ConsoleLogger
  {
    private static readonly object _consoleLock = new object();

    public static void LogError(string name, string message, string serverName = "")
    {
      lock (_consoleLock)
      {
        WriteColored($"[{DateTime.Now:HH:mm:ss}] ", ConsoleColor.Gray);
        WriteColored(name + " ERROR: ", ConsoleColor.Red);
        WriteColored(message, ConsoleColor.White);
        Console.WriteLine();
      }
    }

    public static void LogEvent(string name, string message, string serverName = "")
    {
      lock (_consoleLock)
      {
        WriteColored($"[{DateTime.Now:HH:mm:ss}] ", ConsoleColor.Gray);
        WriteColored(name + " EVENT: ", ConsoleColor.Yellow);
        WriteColored(message, ConsoleColor.White);
        Console.WriteLine();
      }
    }

    private static void WriteColored(string text, ConsoleColor color)
    {
      ConsoleColor originalColor = Console.ForegroundColor;
      Console.ForegroundColor = color;
      Console.Write(text);
      Console.ForegroundColor = originalColor;
    }
  }
}
