// Hanami Sensors: the processor's temperature, for Hanami's edge panel.
//
// Windows gives no program a processor's temperature on PCs like this one: it takes a driver to
// read. This small service reads it through PawnIO - the driver FanControl and LibreHardwareMonitor
// use - with LibreHardwareMonitor's library, and lays it in a block of shared memory
// (Global\HanamiSensors) that signed-in users may read but not write. Nothing listens: no port, no
// pipe. Hanami asks for a reading by setting an event (Global\HanamiSensorsWanted) while its stats
// page is in sight; the service reads at most twice a second, whoever asks, and stops itself after
// a minute without being asked. Hanami starts it again when it next wants a reading: signed-in
// users may start it and see whether it runs, nothing more (the setup gives it that).
//
// Only the processor is opened: nothing here can set a fan, or touch any other hardware.
//
//   HanamiSensors.exe                       as the service (started by Windows)
//   HanamiSensors.exe --console NAME [--fake °C] [--idle S]
//                                           for tests: as the user, with Local\NAME and
//                                           Local\NAMEWanted, a made-up reading if --fake

using System.ComponentModel;
using System.Globalization;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using LibreHardwareMonitor.Hardware;

namespace HanamiSensors;

public static class Program
{
    public const string ServiceName = "HanamiSensors";
    public const string Memory = @"Global\HanamiSensors";
    public const string Wanted = @"Global\HanamiSensorsWanted";
    public const int IdleMs = 60_000;          // stops after this long without being asked
    public const int ReadEveryMs = 500;        // reads no more often than this, however often asked

    public static int Main(string[] args)
    {
        if (args.Length >= 2 && args[0] == "--console")
            return RunAsUser(args);
        ServiceBase.Run(new SensorsService());
        return 0;
    }

    static int RunAsUser(string[] args)
    {
        string name = args[1];
        double? fake = null;
        int idle = IdleMs;
        for (int i = 2; i + 1 < args.Length; i += 2)
        {
            if (args[i] == "--fake")
                fake = double.Parse(args[i + 1], CultureInfo.InvariantCulture);
            else if (args[i] == "--idle")
                idle = (int)(double.Parse(args[i + 1], CultureInfo.InvariantCulture) * 1000);
        }
        using var block = new Block($@"Local\{name}", $@"Local\{name}Wanted", forEveryone: false);
        using var reader = new Reader();
        Func<Reading> read = fake is double degrees ? () => new Reading(Status.Reading, degrees, "Made up") : reader.Read;
        Loop.Run(block, read, idle, () => false);
        return 0;
    }
}

public enum Status
{
    Reading = 0,        // the temperature is there
    NoSensor = 1,       // the processor has no temperature to read (or PawnIO isn't there to read it)
    Failed = 2,         // reading the hardware failed
    Starting = 3,       // not read yet
}

public readonly record struct Reading(Status Status, double Celsius, string Sensor);

/// <summary>Asked, it reads; not asked for idleMs, it returns - and the service stops.</summary>
public static class Loop
{
    public static void Run(Block block, Func<Reading> read, int idleMs, Func<bool> stopping)
    {
        block.Write(new Reading(Status.Starting, double.NaN, ""));
        long last = Environment.TickCount64;
        block.Write(read());                        // it was started because a reading was wanted
        while (!stopping())
        {
            if (!block.WaitWanted(idleMs) || stopping())
                return;
            long wait = Program.ReadEveryMs - (Environment.TickCount64 - last);
            if (wait > 0)
                Thread.Sleep((int)wait);
            last = Environment.TickCount64;
            block.Write(read());
        }
    }
}

/// <summary>The processor's temperature, through LibreHardwareMonitor's library: AMD's "Core
/// (Tctl/Tdie)" or Intel's "CPU Package" - else the hottest of the processor's temperatures.</summary>
public sealed class Reader : IDisposable
{
    Computer? _computer;
    IHardware? _cpu;
    ISensor? _sensor;

    public Reading Read()
    {
        try
        {
            if (_computer is null)
            {
                _computer = new Computer { IsCpuEnabled = true };
                _computer.Open();
            }
            _cpu ??= _computer.Hardware.FirstOrDefault(h => h.HardwareType == HardwareType.Cpu);
            if (_cpu is null)
                return new Reading(Status.NoSensor, double.NaN, "");
            _cpu.Update();
            _sensor ??= Pick(_cpu.Sensors);
            if (_sensor?.Value is float value && !float.IsNaN(value))
                return new Reading(Status.Reading, value, _sensor.Name);
            _sensor = null;
            return new Reading(Status.NoSensor, double.NaN, "");
        }
        catch (Exception)
        {
            Dispose();
            return new Reading(Status.Failed, double.NaN, "");
        }
    }

    static ISensor? Pick(IEnumerable<ISensor> sensors)
    {
        var temperatures = sensors.Where(s => s.SensorType == SensorType.Temperature && s.Value is float).ToList();
        return temperatures.FirstOrDefault(s => s.Name.Contains("Tctl", StringComparison.OrdinalIgnoreCase)
                                                || s.Name.Contains("Package", StringComparison.OrdinalIgnoreCase))
               ?? temperatures.OrderByDescending(s => s.Value).FirstOrDefault();
    }

    public void Dispose()
    {
        try { _computer?.Close(); } catch (Exception) { }
        _computer = null;
        _cpu = null;
        _sensor = null;
    }
}

/// <summary>The shared memory the reading is laid in, and the event that asks for one.
///
/// Its layout (little-endian), version 1:
///   0  uint32  magic, "HNSN"
///   4  uint32  layout version
///   8  uint32  sequence - odd while being written, so a reader can tell a torn read
///  12  int32   status (Status)
///  16  int64   when it was read: ms since 1970, UTC
///  24  double  °C (NaN without a reading)
///  32  char16[64]  the sensor's name, NUL-ended
/// </summary>
public sealed unsafe class Block : IDisposable
{
    public const uint Magic = 0x4E534E48;
    public const int Size = 4096;
    // SYSTEM and administrators: everything; signed-in users: read the memory, set the event.
    const string MemorySddl = "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GR;;;AU)";
    const string WantedSddl = "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x00100002;;;AU)";

    readonly IntPtr _mapping, _wanted;
    readonly byte* _view;
    uint _sequence;

    public Block(string memory, string wanted, bool forEveryone)
    {
        _mapping = Native.Create(forEveryone ? MemorySddl : null,
            sa => Native.CreateFileMappingW(new IntPtr(-1), sa, Native.PAGE_READWRITE, 0, Size, memory));
        _view = (byte*)Native.MapViewOfFile(_mapping, Native.FILE_MAP_WRITE, 0, 0, Size);
        if (_view == null)
            throw new Win32Exception();
        _wanted = Native.Create(forEveryone ? WantedSddl : null, sa => Native.CreateEventW(sa, false, false, wanted));
        _sequence = *(uint*)(_view + 8) & ~1u;
        *(uint*)_view = Magic;
        *(uint*)(_view + 4) = 1;
    }

    public bool WaitWanted(int ms) => Native.WaitForSingleObject(_wanted, (uint)ms) == 0;

    public void Wake() => Native.SetEvent(_wanted);

    public void Write(Reading reading)
    {
        Volatile.Write(ref *(uint*)(_view + 8), ++_sequence);           // odd: being written
        Thread.MemoryBarrier();
        *(int*)(_view + 12) = (int)reading.Status;
        *(long*)(_view + 16) = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        *(double*)(_view + 24) = reading.Celsius;
        char* name = (char*)(_view + 32);
        int length = Math.Min(reading.Sensor.Length, 63);
        for (int i = 0; i < length; i++)
            name[i] = reading.Sensor[i];
        name[length] = '\0';
        Thread.MemoryBarrier();
        Volatile.Write(ref *(uint*)(_view + 8), ++_sequence);           // even: done
    }

    public void Dispose()
    {
        if (_view != null)
            Native.UnmapViewOfFile((IntPtr)_view);
        Native.CloseHandle(_mapping);
        Native.CloseHandle(_wanted);
    }
}

sealed class SensorsService : ServiceBase
{
    Thread? _worker;
    Block? _block;
    volatile bool _stopping;

    public SensorsService()
    {
        ServiceName = Program.ServiceName;
        CanStop = true;
        CanShutdown = true;
    }

    protected override void OnStart(string[] args)
    {
        _block = new Block(Program.Memory, Program.Wanted, forEveryone: true);
        var block = _block;
        _worker = new Thread(() =>
        {
            using var reader = new Reader();
            Loop.Run(block, reader.Read, Program.IdleMs, () => _stopping);
            if (!_stopping)
                Stop();                             // a minute without being asked
        }) { IsBackground = true, Name = "sensors" };
        _worker.Start();
    }

    protected override void OnStop()
    {
        _stopping = true;
        _block?.Wake();
        if (_worker is not null && _worker != Thread.CurrentThread)
            _worker.Join(5000);
        _block?.Dispose();
        _block = null;
    }

    protected override void OnShutdown() => OnStop();
}

static class Native
{
    public const uint PAGE_READWRITE = 0x04;
    public const uint FILE_MAP_WRITE = 0x02;

    [StructLayout(LayoutKind.Sequential)]
    public struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        public int bInheritHandle;
    }

    /// <summary>A named object made with a security descriptor from SDDL (none: the default).</summary>
    public static IntPtr Create(string? sddl, Func<IntPtr, IntPtr> make)
    {
        IntPtr descriptor = IntPtr.Zero, attributes = IntPtr.Zero;
        try
        {
            if (sddl is not null)
            {
                if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, out descriptor, IntPtr.Zero))
                    throw new Win32Exception();
                var sa = new SECURITY_ATTRIBUTES
                {
                    nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>(), lpSecurityDescriptor = descriptor,
                };
                attributes = Marshal.AllocHGlobal(sa.nLength);
                Marshal.StructureToPtr(sa, attributes, false);
            }
            IntPtr handle = make(attributes);
            if (handle == IntPtr.Zero)
                throw new Win32Exception();
            return handle;
        }
        finally
        {
            if (attributes != IntPtr.Zero)
                Marshal.FreeHGlobal(attributes);
            if (descriptor != IntPtr.Zero)
                LocalFree(descriptor);
        }
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string sddl, uint revision,
        out IntPtr descriptor, IntPtr size);

    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr memory);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateFileMappingW(IntPtr file, IntPtr attributes, uint protect, uint sizeHigh,
        uint sizeLow, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr MapViewOfFile(IntPtr mapping, uint access, uint offsetHigh, uint offsetLow,
        UIntPtr size);

    public static IntPtr MapViewOfFile(IntPtr mapping, uint access, uint offsetHigh, uint offsetLow, int size) =>
        MapViewOfFile(mapping, access, offsetHigh, offsetLow, (UIntPtr)size);

    [DllImport("kernel32.dll")]
    public static extern bool UnmapViewOfFile(IntPtr view);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateEventW(IntPtr attributes, bool manualReset, bool initialState, string name);

    [DllImport("kernel32.dll")]
    public static extern bool SetEvent(IntPtr handle);

    [DllImport("kernel32.dll")]
    public static extern uint WaitForSingleObject(IntPtr handle, uint ms);

    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr handle);
}
