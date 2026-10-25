// Hanami Sensors' setup: installs the service into Program Files, or removes it. Hanami runs it as
// administrator (Windows asks first) from Settings > Edge panel.
//
// Hanami's own folder is the user's to write in, and the service runs as the system: so every file
// is read once, checked against the SHA-256 built into this program (FileHashes, made by
// sensors\build.ps1 from the published service), and those same bytes - not the files again - go
// into Program Files, where only administrators may write. A file changed since the build stops
// the install.
//
//   HanamiSensorsSetup --install     install, or update in place (stopping the old one first)
//   HanamiSensorsSetup --uninstall   stop it, unregister it, delete its folder
//   HanamiSensorsSetup --verify      only check the files beside it (needs no administrator)
//
// Exit codes: 0 done; 1 unknown command; 2 needs administrator; 3 a file isn't as built;
// 4 the old service wouldn't stop; 5 the files couldn't be copied; 6 Windows wouldn't register it.

using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.ServiceProcess;

namespace HanamiSensorsSetup;

public static class Program
{
    const string ServiceName = "HanamiSensors";
    const string DisplayName = "Hanami Sensors";
    const string Description = "Reads the processor's temperature for Hanami's edge panel, through PawnIO. "
                               + "Started by Hanami while its stats page is in sight; stops itself after a minute unasked.";
    // SYSTEM and administrators as Windows gives them; signed-in users may also start it, and see
    // whether it runs - not stop it, nor change it.
    const string ServiceSddl = "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)"
                               + "(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)(A;;LCRPRC;;;AU)";

    static string Source => Path.Combine(AppContext.BaseDirectory, "service");
    static string Target => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                                         "Hanami Sensors");

    public static int Main(string[] args)
    {
        try
        {
            return args.FirstOrDefault() switch
            {
                "--verify" => Verified(Source) is null ? 3 : 0,
                "--install" => Install(),
                "--uninstall" => Uninstall(),
                _ => 1,
            };
        }
        catch (Exception)
        {
            return 5;
        }
    }

    static bool Administrator() =>
        new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);

    /// <summary>Every file the service is made of, read once - or null if any is missing or not as
    /// it was built.</summary>
    static Dictionary<string, byte[]>? Verified(string folder)
    {
        var files = new Dictionary<string, byte[]>();
        foreach (var (name, sha256) in FileHashes.Files)
        {
            string path = Path.Combine(folder, name);
            if (!File.Exists(path))
                return null;
            byte[] bytes = File.ReadAllBytes(path);
            if (!Convert.ToHexString(SHA256.HashData(bytes)).Equals(sha256, StringComparison.OrdinalIgnoreCase))
                return null;
            files[name] = bytes;
        }
        return files.Count > 0 ? files : null;
    }

    static int Install()
    {
        if (!Administrator())
            return 2;
        var files = Verified(Source);
        if (files is null)
            return 3;
        if (!StopService())
            return 4;
        try
        {
            if (Directory.Exists(Target))
                Directory.Delete(Target, recursive: true);
            Directory.CreateDirectory(Target);
            foreach (var (name, bytes) in files)
            {
                string path = Path.Combine(Target, name);
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllBytes(path, bytes);
            }
        }
        catch (Exception)
        {
            return 5;
        }
        return Register(Path.Combine(Target, "HanamiSensors.exe")) ? 0 : 6;
    }

    static int Uninstall()
    {
        if (!Administrator())
            return 2;
        if (!StopService())
            return 4;
        IntPtr manager = Native.OpenSCManagerW(null, null, Native.SC_MANAGER_ALL_ACCESS);
        if (manager != IntPtr.Zero)
        {
            IntPtr service = Native.OpenServiceW(manager, ServiceName, Native.DELETE);
            if (service != IntPtr.Zero)
            {
                Native.DeleteService(service);
                Native.CloseServiceHandle(service);
            }
            Native.CloseServiceHandle(manager);
        }
        for (int attempt = 0; attempt < 10 && Directory.Exists(Target); attempt++)
        {
            try
            {
                Directory.Delete(Target, recursive: true);
            }
            catch (IOException)
            {
                Thread.Sleep(500);                  // its process may still be on its way out
            }
            catch (UnauthorizedAccessException)
            {
                Thread.Sleep(500);
            }
        }
        return Directory.Exists(Target) ? 5 : 0;
    }

    /// <summary>The service stopped, if it is installed and running.</summary>
    static bool StopService()
    {
        try
        {
            using var controller = new ServiceController(ServiceName);
            if (controller.Status != ServiceControllerStatus.Stopped)
            {
                if (controller.Status != ServiceControllerStatus.StopPending)
                    controller.Stop();
                controller.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(15));
            }
            return true;
        }
        catch (InvalidOperationException)
        {
            return true;                            // not installed
        }
        catch (System.ServiceProcess.TimeoutException)
        {
            return false;
        }
    }

    /// <summary>The service registered - or its registration brought up to date: run as the
    /// system, started only when asked, signed-in users allowed to start it.</summary>
    static bool Register(string exe)
    {
        IntPtr manager = Native.OpenSCManagerW(null, null, Native.SC_MANAGER_ALL_ACCESS);
        if (manager == IntPtr.Zero)
            return false;
        try
        {
            string command = $"\"{exe}\"";
            IntPtr service = Native.CreateServiceW(manager, ServiceName, DisplayName, Native.SERVICE_ALL_ACCESS,
                Native.SERVICE_WIN32_OWN_PROCESS, Native.SERVICE_DEMAND_START, Native.SERVICE_ERROR_NORMAL, command,
                null, IntPtr.Zero, null, null, null);
            if (service == IntPtr.Zero)
            {
                if (Marshal.GetLastWin32Error() != Native.ERROR_SERVICE_EXISTS)
                    return false;
                service = Native.OpenServiceW(manager, ServiceName, Native.SERVICE_ALL_ACCESS);
                if (service == IntPtr.Zero)
                    return false;
                if (!Native.ChangeServiceConfigW(service, Native.SERVICE_WIN32_OWN_PROCESS, Native.SERVICE_DEMAND_START,
                        Native.SERVICE_ERROR_NORMAL, command, null, IntPtr.Zero, null, "LocalSystem", null, DisplayName))
                {
                    Native.CloseServiceHandle(service);
                    return false;
                }
            }
            try
            {
                var about = new Native.SERVICE_DESCRIPTION { Description = Description };
                Native.ChangeServiceConfig2W(service, Native.SERVICE_CONFIG_DESCRIPTION, ref about);
                return SetSecurity(service);
            }
            finally
            {
                Native.CloseServiceHandle(service);
            }
        }
        finally
        {
            Native.CloseServiceHandle(manager);
        }
    }

    static bool SetSecurity(IntPtr service)
    {
        if (!Native.ConvertStringSecurityDescriptorToSecurityDescriptorW(ServiceSddl, 1, out IntPtr descriptor,
                IntPtr.Zero))
            return false;
        try
        {
            return Native.SetServiceObjectSecurity(service, Native.DACL_SECURITY_INFORMATION, descriptor);
        }
        finally
        {
            Native.LocalFree(descriptor);
        }
    }
}

static class Native
{
    public const uint SC_MANAGER_ALL_ACCESS = 0xF003F;
    public const uint SERVICE_ALL_ACCESS = 0xF01FF;
    public const uint DELETE = 0x10000;
    public const uint SERVICE_WIN32_OWN_PROCESS = 0x10;
    public const uint SERVICE_DEMAND_START = 3;
    public const uint SERVICE_ERROR_NORMAL = 1;
    public const uint SERVICE_CONFIG_DESCRIPTION = 1;
    public const uint DACL_SECURITY_INFORMATION = 4;
    public const int ERROR_SERVICE_EXISTS = 1073;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct SERVICE_DESCRIPTION
    {
        [MarshalAs(UnmanagedType.LPWStr)] public string Description;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr OpenSCManagerW(string? machine, string? database, uint access);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateServiceW(IntPtr manager, string name, string display, uint access, uint type,
        uint start, uint error, string path, string? group, IntPtr tag, string? dependencies, string? account,
        string? password);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr OpenServiceW(IntPtr manager, string name, uint access);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool ChangeServiceConfigW(IntPtr service, uint type, uint start, uint error, string? path,
        string? group, IntPtr tag, string? dependencies, string? account, string? password, string? display);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool ChangeServiceConfig2W(IntPtr service, uint level, ref SERVICE_DESCRIPTION info);

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern bool SetServiceObjectSecurity(IntPtr service, uint information, IntPtr descriptor);

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern bool DeleteService(IntPtr service);

    [DllImport("advapi32.dll")]
    public static extern bool CloseServiceHandle(IntPtr handle);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string sddl, uint revision,
        out IntPtr descriptor, IntPtr size);

    [DllImport("kernel32.dll")]
    public static extern IntPtr LocalFree(IntPtr memory);
}
