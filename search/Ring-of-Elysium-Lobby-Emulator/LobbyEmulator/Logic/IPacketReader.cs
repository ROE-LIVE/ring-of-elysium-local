using System.Collections.Generic;

namespace LobbyEmulator.Logic
{
  public interface IPacketReader
  {
    int Port { get; }
    bool Init { get; set; }
    List<byte[]> HandlePacket(byte[] pack);
  }
}
