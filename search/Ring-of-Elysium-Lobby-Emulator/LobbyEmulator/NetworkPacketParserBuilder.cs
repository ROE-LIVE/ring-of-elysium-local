using System;
using System.IO;
using System.Linq;

namespace LobbyEmulator
{
  public enum EF : byte
  {
    F0 = 0x00,
    F4 = 0x04
  }

  public enum CMD : byte
  {
    DT = 0x00,
    CK = 0x01,
    ID = 0x04,
    IT = 0x03,
    SN = 0x08,
    SA = 0x09,
    DC = 0x0D
  }

  public enum PComplet
  {
    Complete,
    CompleteWithRemainder,
    Incomplete
  }

  public abstract class Packet
  {
    public const byte Magic0 = 0x55;
    public const byte Magic1 = 0x0E;

    public CMD Command { get; protected set; }
    public EF Flag { get; set; }

    public PComplet Completeness { get; set; }
    public byte[] RemainderData { get; set; }

    public abstract byte[] ToBytes();

    public static Packet Parse(byte[] buffer)
    {
      Packet parsed;

      using (var ms = new MemoryStream(buffer))
      using (var br = new BinaryReader(ms))
      {
        if (buffer.Length < 4)
          return new IncompletePacket { Completeness = PComplet.Incomplete, RemainderData = buffer };

        byte m0 = br.ReadByte();
        byte m1 = br.ReadByte();
        if (m0 != Magic0 || m1 != Magic1) throw new InvalidDataException("Invalid magic");

        if (ms.Position >= ms.Length) throw new InvalidDataException("No command byte");
        CMD cmd = (CMD)br.ReadByte();
        br.ReadByte();

        uint expectedSize;

        switch (cmd)
        {
          case CMD.DT:
          case CMD.DC:
            if (br.BaseStream.Length < 10)
              return new IncompletePacket { Completeness = PComplet.Incomplete, RemainderData = buffer };
            uint header = ReadUInt32BE(br);
            uint block = ReadUInt32BE(br);
            expectedSize = header + block;
            break;
          case CMD.SA:
            if (br.BaseStream.Length < 10)
              return new IncompletePacket { Completeness = PComplet.Incomplete, RemainderData = buffer };
            uint full = ReadUInt32BE(br);
            uint extra = ReadUInt32BE(br);
            expectedSize = full + extra;
            break;

          default:
            if (br.BaseStream.Length < 8)
              return new IncompletePacket { Completeness = PComplet.Incomplete, RemainderData = buffer };
            expectedSize = ReadUInt32BE(br);
            break;
        }

        if (br.BaseStream.Length < expectedSize)
          return new IncompletePacket { Completeness = PComplet.Incomplete, RemainderData = buffer };

        parsed = ParseInternal(br);

        if (br.BaseStream.Length > expectedSize)
        {
          parsed.Completeness = PComplet.CompleteWithRemainder;
          parsed.RemainderData = new byte[br.BaseStream.Length - expectedSize];
          Array.Copy(buffer, expectedSize, parsed.RemainderData, 0, parsed.RemainderData.Length);
        }
        else
        {
          parsed.Completeness = PComplet.Complete;
        }
      }

      return parsed;
    }

    private static Packet ParseInternal(BinaryReader br)
    {
      br.BaseStream.Position = 0;
      br.ReadByte();
      br.ReadByte();
      CMD cmd = (CMD)br.ReadByte();
      br.ReadByte();
      br.BaseStream.Position = 2;

      switch (cmd)
      {
        case CMD.IT:
          return IT_Pack.ParseFromStream(br);
        case CMD.SN:
          return SN_Pack.ParseFromStream(br);
        case CMD.SA:
          return SA_Pack.ParseFromStream(br);
        case CMD.ID:
          return ID_Pack.ParseFromStream(br);
        case CMD.CK:
          return CK_Pack.ParseFromStream(br);
        case CMD.DT:
          return DT_Pack.ParseFromStream(br);
        case CMD.DC:
          return DC_Pack.ParseFromStream(br);
        default:
          throw new NotSupportedException();
      }
    }

    protected static uint ReadUInt32LE(BinaryReader br)
    {
      if (br.BaseStream.Length - br.BaseStream.Position < 4) throw new EndOfStreamException();
      var b = br.ReadBytes(4);
      return (uint)(b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24));
    }

    protected static int ReadInt32LE(BinaryReader br)
    {
      return (int)ReadUInt32LE(br);
    }

    protected static uint ReadUInt32BE(BinaryReader br)
    {
      if (br.BaseStream.Length - br.BaseStream.Position  < 4) throw new EndOfStreamException();
      var b = br.ReadBytes(4);
      return (uint)((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]);
    }

    protected static int ReadInt32BE(BinaryReader br)
    {
      return (int)ReadUInt32BE(br);
    }

    protected static ushort ReadUInt16LE(BinaryReader br)
    {
      if (br.BaseStream.Length - br.BaseStream.Position < 2) throw new EndOfStreamException();
      var b = br.ReadBytes(2);
      return (ushort)(b[0] | (b[1] << 8));
    }

    protected static short ReadInt16LE(BinaryReader br)
    {
      return (short)ReadUInt16LE(br);
    }

    protected static ushort ReadUInt16BE(BinaryReader br)
    {
      if (br.BaseStream.Length - br.BaseStream.Position < 2) throw new EndOfStreamException();
      var b = br.ReadBytes(2);
      return (ushort)((b[0] << 8) | b[1]);
    }

    protected static short ReadInt16BE(BinaryReader br)
    {
      return (short)ReadUInt16BE(br);
    }

    protected static void WriteUInt32LE(BinaryWriter bw, uint v)
    {
      bw.Write((byte)(v & 0xFF));
      bw.Write((byte)((v >> 8) & 0xFF));
      bw.Write((byte)((v >> 16) & 0xFF));
      bw.Write((byte)((v >> 24) & 0xFF));
    }

    protected static void WriteInt32LE(BinaryWriter bw, int v)
    {
      WriteUInt32LE(bw, (uint)v);
    }

    protected static void WriteUInt32BE(BinaryWriter bw, uint v)
    {
      bw.Write((byte)((v >> 24) & 0xFF));
      bw.Write((byte)((v >> 16) & 0xFF));
      bw.Write((byte)((v >> 8) & 0xFF));
      bw.Write((byte)(v & 0xFF));
    }

    protected static void WriteInt32BE(BinaryWriter bw, int v)
    {
      WriteUInt32BE(bw, (uint)v);
    }

    protected static void WriteUInt16LE(BinaryWriter bw, ushort v)
    {
      bw.Write((byte)(v & 0xFF));
      bw.Write((byte)((v >> 8) & 0xFF));
    }

    protected static void WriteInt16LE(BinaryWriter bw, short v)
    {
      WriteUInt16LE(bw, (ushort)v);
    }

    protected static void WriteUInt16BE(BinaryWriter bw, ushort v)
    {
      bw.Write((byte)((v >> 8) & 0xFF));
      bw.Write((byte)(v & 0xFF));
    }

    protected static void WriteInt16BE(BinaryWriter bw, short v)
    {
      WriteUInt16BE(bw, (ushort)v);
    }
  }

  public class IncompletePacket : Packet
  {
    public override byte[] ToBytes() => new byte[0];
  }

  public class IT_Pack : Packet
  {
    public uint FullSize { get; set; }
    public uint SysFlag1 { get; set; }
    public uint SysFlag2 { get; set; }
    public uint SysFlag3 { get; set; }
    public uint SysFlag4 { get; set; }
    public uint SysFlag5 { get; set; }
    public byte[] SysFlag6 { get; set; }
    public uint Time { get; set; }
    public short DataBlockSize { get; set; }
    public byte[] Data { get; set; }

    public IT_Pack()
    {
      Command = CMD.IT;
    }

    internal static IT_Pack ParseFromStream(BinaryReader br)
    {
      var p = new IT_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.FullSize = ReadUInt32BE(br);
      p.SysFlag1 = ReadUInt32BE(br);
      p.SysFlag2 = ReadUInt32BE(br);
      p.SysFlag3 = ReadUInt32BE(br);
      p.SysFlag4 = ReadUInt32BE(br);
      p.SysFlag5 = ReadUInt32BE(br);
      
      var constBytes = br.ReadBytes(3);
      p.SysFlag6 = constBytes;
      
      p.Time = ReadUInt32LE(br);
      p.DataBlockSize = (short)ReadUInt16BE(br);
      p.Data = br.ReadBytes(p.DataBlockSize);
      return p;
    }

    public override byte[] ToBytes()
    {
      using (var ms = new MemoryStream())
      using (var bw = new BinaryWriter(ms))
      {

        bw.Write(Magic0);
        bw.Write(Magic1);
        bw.Write((byte)Command);
        bw.Write((byte)Flag);
        WriteUInt32BE(bw, FullSize);
        WriteUInt32BE(bw, SysFlag1);
        WriteUInt32BE(bw, SysFlag2);
        WriteUInt32BE(bw, SysFlag3);
        WriteUInt32BE(bw, SysFlag4);
        WriteUInt32BE(bw, SysFlag5);
        if (SysFlag6 != null) bw.Write(SysFlag6);
        else bw.Write(new byte[] { 0x48, 0x00, 0x01 });
        
        WriteUInt32LE(bw, Time);
        WriteInt16BE(bw, DataBlockSize);
        if (Data != null) bw.Write(Data);
        return ms.ToArray();
      }
    }
  }

  public class SN_Pack : Packet
  {
    public uint FullSize { get; set; }
    public uint Extra { get; set; }
    public byte DataSize { get; set; }
    public byte[] Data { get; set; }
    public byte[] ExtraOffset { get; set; }

    public SN_Pack()
    {
      Command = CMD.SN;
      Flag = EF.F0;
    }

    internal static SN_Pack ParseFromStream(BinaryReader br)
    {
      var p = new SN_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.FullSize = ReadUInt32BE(br);
      p.Extra = ReadUInt32BE(br);
      p.DataSize = br.ReadByte();
      p.Data = br.ReadBytes(p.DataSize);
      if (p.Extra > 0)
        p.ExtraOffset = br.ReadBytes((int)p.Extra);
      else
        p.ExtraOffset = new byte[0];
      return p;
    }

    public override byte[] ToBytes()
    {
      using (var ms = new MemoryStream())
      using (var bw = new BinaryWriter(ms))
      {
        bw.Write(Magic0);
        bw.Write(Magic1);
        bw.Write((byte)Command);
        bw.Write((byte)Flag);

        WriteUInt32LE(bw, 0);
        WriteUInt32LE(bw, Extra);
        bw.Write(DataSize);
        if (Data != null) bw.Write(Data);
        if (ExtraOffset != null) bw.Write(ExtraOffset);

        bw.BaseStream.Seek(4, SeekOrigin.Begin);
        bw.Write(BitConverter.GetBytes((uint)bw.BaseStream.Length).Reverse().ToArray(), 0, 4);

        return ms.ToArray();
      }
    }
  }

  public class SA_Pack : SN_Pack
  {
    public SA_Pack()
    {
      Command = CMD.SA;
      Flag = EF.F4;
    }

    internal new static SA_Pack ParseFromStream(BinaryReader br)
    {
      var p = new SA_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.FullSize = ReadUInt32BE(br);
      p.Extra = ReadUInt32BE(br);
      p.DataSize = br.ReadByte();
      p.Data = br.ReadBytes(p.DataSize);
      if (p.Extra > 0)
        p.ExtraOffset = br.ReadBytes((int)p.Extra);
      else
        p.ExtraOffset = new byte[0];
      return p;
    }
  }

  public class ID_Pack : Packet
  {
    private byte[] _Data;

    public uint FullSize { get; set; }
    public uint Sys { get; set; }
    public uint DataSize { get; set; }
    public byte[] Data {
      get {
        return _Data;
      }
      set {
        _Data = value;
        DataSize = (uint)value.Length;
      }
    }

    public ID_Pack()
    {
      Command = CMD.ID;
      Flag = EF.F0;
    }

    internal static ID_Pack ParseFromStream(BinaryReader br)
    {
      var p = new ID_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.FullSize = ReadUInt32BE(br);
      p.Sys = ReadUInt32BE(br);
      p.DataSize = ReadUInt32BE(br);
      p.Data = br.ReadBytes((int)p.DataSize);
      return p;
    }

    public override byte[] ToBytes()
    {
      using (var ms = new MemoryStream())
      using (var bw = new BinaryWriter(ms))
      {
        bw.Write(Magic0);
        bw.Write(Magic1);
        bw.Write((byte)Command);
        bw.Write((byte)Flag);

        WriteUInt32BE(bw, 0);
        WriteUInt32BE(bw, Sys);
        WriteUInt32BE(bw, DataSize);
        if (Data != null) bw.Write(Data);

        bw.BaseStream.Seek(4, SeekOrigin.Begin);
        bw.Write(BitConverter.GetBytes((uint)bw.BaseStream.Length).Reverse().ToArray(), 0, 4);

        return ms.ToArray();
      }
    }
  }

  public class CK_Pack : ID_Pack
  {
    public CK_Pack()
    {
      Command = CMD.CK;
      Flag = EF.F0;
    }

    internal new static CK_Pack ParseFromStream(BinaryReader br)
    {
      var p = new CK_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.FullSize = ReadUInt32BE(br);
      p.Sys = ReadUInt32BE(br);
      p.DataSize = ReadUInt32BE(br);
      p.Data = br.ReadBytes((int)p.DataSize);
      return p;
    }
  }

  public class DT_Pack : Packet
  {
    private byte[] _Data;

    public uint HeaderSize { get; set; }
    public uint DataBlockSize { get; protected set; }
    public byte[] Data {
      get {
        return _Data;
      }
      set {
        _Data = value;
        DataBlockSize = (uint)value.Length;
      }
    }

    public DT_Pack()
    {
      Command = CMD.DT;
      HeaderSize = 12;
    }

    internal static DT_Pack ParseFromStream(BinaryReader br)
    {
      var p = new DT_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.HeaderSize = ReadUInt32BE(br);
      p.DataBlockSize = ReadUInt32BE(br);
      p.Data = br.ReadBytes((int)p.DataBlockSize);
      return p;
    }

    public override byte[] ToBytes()
    {
      using (var ms = new MemoryStream())
      using (var bw = new BinaryWriter(ms))
      {
        bw.Write(Magic0);
        bw.Write(Magic1);
        bw.Write((byte)Command);
        bw.Write((byte)Flag);
        if (Command == CMD.DT)
          WriteUInt32BE(bw, HeaderSize);
        else
          WriteUInt32BE(bw, (uint)bw.BaseStream.Length + (uint)Data.Length);

        WriteUInt32BE(bw, DataBlockSize);

        if (Data != null) bw.Write(Data);
        return ms.ToArray();
      }
    }
  }

  public class DC_Pack : DT_Pack
  {
    public DC_Pack()
    {
      Command = CMD.DC;
      Flag = EF.F4;
    }

    internal new static DC_Pack ParseFromStream(BinaryReader br)
    {
      var p = new DC_Pack();
      p.Command = (CMD)br.ReadByte();
      p.Flag = (EF)br.ReadByte();
      p.HeaderSize = ReadUInt32BE(br);
      p.DataBlockSize = ReadUInt32BE(br);
      p.Data = br.ReadBytes((int)p.DataBlockSize);
      return p;
    }
  }
}