using System;

namespace LobbyEmulator.Utils
{
  public static class StringExtensions
  {
    public static byte[] ToArr(this string hex)
    {
      hex = hex?.Trim().Replace("0x", "").Replace(" ", "").Replace("-", "").Replace("\r", "").Replace("\n", "") ?? "";
      if (hex.Length % 2 != 0) throw new ArgumentException("Hex string must have even length");
      byte[] result = new byte[hex.Length / 2];

      for (int i = 0; i < result.Length; i++)
        result[i] = Convert.ToByte(hex.Substring(i * 2, 2), 16);

      return result;
    }
  }
}
