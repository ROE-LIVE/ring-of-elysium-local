using LobbyEmulator.Logic;
using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace LobbyEmulator
{
  internal class Program
  {
    static async Task Main(string[] args)
    {
      var tasks = new List<Task>
      {
        Task.Run(() => new Lobby_Module<LobbyPreData>()),
      };

      Console.WriteLine("Ready...");

      await Task.WhenAll(tasks);
    }
  }
}
