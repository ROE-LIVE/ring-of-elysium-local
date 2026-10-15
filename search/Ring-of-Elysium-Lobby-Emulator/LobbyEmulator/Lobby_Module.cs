using LobbyEmulator.Logic;
using LobbyEmulator.Utils;
using System;
using System.Net;
using System.Net.Sockets;
using System.Threading.Tasks;

namespace LobbyEmulator
{
  public class Lobby_Module<T> where T : IPacketReader, new()
  {
    T _logic = new T();

    public Lobby_Module()
    {
      TcpListener server = new TcpListener(IPAddress.Loopback, _logic.Port);
      server.Start();

      ConsoleLogger.LogEvent($"[LobbyLoader]", $"Started on port {_logic.Port}");

      while (true)
      {
        TcpClient client = server.AcceptTcpClient();
        ConsoleLogger.LogEvent($"[LobbyLoader]", "Client connected");

        Task clientTask = Task.Run(() => HandleClient(client));
        clientTask.Wait();

        ConsoleLogger.LogEvent($"[LobbyLoader]", "Awaiting client..");
      }
    }

    private void HandleClient(TcpClient client)
    {
      try
      {
        using (client)
        using (NetworkStream stream = client.GetStream())
        {
          byte[] reqData = new byte[1024];
          byte[] resData = new byte[0];
          int bytesRead;

          while ((bytesRead = stream.Read(reqData, 0, reqData.Length)) != 0)
          {

            byte[] receivedData = new byte[bytesRead];
            Array.Copy(reqData, 0, receivedData, 0, bytesRead);

            try
            {
              foreach (byte[] data in _logic.HandlePacket(receivedData))
                stream.Write(data, 0, data.Length);
            }
            catch (Exception ex)
            {
              ConsoleLogger.LogError($"[LobbyLoader]", ex.Message);
            }
          }
        }
      }
      catch (Exception ex)
      {
        ConsoleLogger.LogError($"[LobbyLoader]", ex.Message);
      }
      finally
      {
        _logic.Init = false;
        ConsoleLogger.LogEvent($"[LobbyLoader]", "Client disconnected");
      }
    }
  }
}
