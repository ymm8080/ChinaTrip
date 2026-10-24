$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Threading;

public static class Loopback {
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
  class MMDeviceEnumeratorComObject {}

  [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int f, int m, out IntPtr c);
    [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice dev);
    [PreserveSig] int GetDevice(string id, out IMMDevice dev);
    int RegisterEndpointNotificationCallback(IntPtr cb);
    int UnregisterEndpointNotificationCallback(IntPtr cb);
  }

  [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice {
    [PreserveSig] int Activate(ref Guid iid, int ctx, IntPtr p, out IAudioClient client);
  }

  [ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioClient {
    int Initialize(int shareMode, int flags, long buffer, long periodicity, IntPtr format, IntPtr guid);
    int GetBufferSize(out uint frames);
    int GetStreamLatency(out long latency);
    int GetCurrentPadding(out uint padding);
    int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closest);
    int GetMixFormat(out IntPtr format);
    int GetDevicePeriod(out long def, out long min);
    int Start();
    int Stop();
    int Reset();
    int SetEventHandle(IntPtr handle);
    int GetService(ref Guid iid, out IAudioCaptureClient svc);
  }

  [ComImport, Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioCaptureClient {
    int GetBuffer(out IntPtr data, out uint frames, out uint flags, out long dp, out long qp);
    int ReleaseBuffer(uint frames);
    int GetNextPacketSize(out uint frames);
  }

  public static string Run() {
    var en = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
    IMMDevice dev;
    int hr = en.GetDefaultAudioEndpoint(0, 0, out dev);
    if (hr != 0) return "no render default";
    Guid iidAc = new Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2");
    IAudioClient ac;
    if (dev.Activate(ref iidAc, 1, IntPtr.Zero, out ac) != 0) return "activate-fail";
    IntPtr fmt; ac.GetMixFormat(out fmt);
    short chans = Marshal.ReadInt16(fmt, 2);
    hr = ac.Initialize(0, 0x00020000 /*LOOPBACK*/, 2000000, 0, fmt, IntPtr.Zero);
    if (hr != 0) return "init-fail 0x" + hr.ToString("X");
    var t = new Thread(() => {
      try {
        var sp = new System.Speech.Synthesis.SpeechSynthesizer();
        sp.SetOutputToDefaultAudioDevice();
        sp.Volume = 100;
        sp.Speak("speaker verification, speaker verification, one two three");
      } catch (Exception) {}
    });
    t.IsBackground = true;
    float peak = 0; long framesTotal = 0;
    ac.Start(); t.Start();
    Guid iidCap = new Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317");
    IAudioCaptureClient cap;
    ac.GetService(ref iidCap, out cap);
    var sw = System.Diagnostics.Stopwatch.StartNew();
    while (sw.ElapsedMilliseconds < 5000) {
      uint pkt; cap.GetNextPacketSize(out pkt);
      if (pkt == 0) { Thread.Sleep(40); continue; }
      IntPtr data; uint frames; uint flags; long dp, qp;
      cap.GetBuffer(out data, out frames, out flags, out dp, out qp);
      if ((flags & 0x2) == 0 && data != IntPtr.Zero) {
        for (uint i = 0; i < frames * chans; i++) {
          float s = Marshal.PtrToStructure<float>(new IntPtr(data.ToInt64() + i * 4));
          float a = Math.Abs(s);
          if (a > peak) peak = a;
        }
      }
      framesTotal += frames;
      cap.ReleaseBuffer(frames);
    }
    ac.Stop(); t.Join(500);
    return string.Format("SPEAKER_LOOPBACK_PEAK={0:F4} frames={1}", peak, framesTotal);
  }
}
'@ -ReferencedAssemblies System.Speech

[Loopback]::Run()
