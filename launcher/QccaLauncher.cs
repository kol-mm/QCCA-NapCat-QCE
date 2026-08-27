using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class QccaLauncher
{
    private const int SwHide = 0;

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr windowHandle, int command);

    [STAThread]
    private static int Main()
    {
        var packageDirectory = AppDomain.CurrentDomain.BaseDirectory;
        var batchFile = Path.Combine(packageDirectory, "launcher-user.bat");
        if (!File.Exists(batchFile))
        {
            MessageBox.Show(
                "找不到 launcher-user.bat。请确认 QCCA-NapCat-QCE.exe 位于完整发行包的根目录。",
                "QCCA-NapCat-QCE",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
                Arguments = "/d /c \"\"" + batchFile + "\"\"",
                WorkingDirectory = packageDirectory,
                CreateNoWindow = false,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Normal,
            };
            startInfo.EnvironmentVariables["QCCA_HEADLESS"] = "1";

            var consoleProcess = Process.Start(startInfo);
            if (consoleProcess == null)
            {
                throw new Win32Exception("启动器进程未能创建。");
            }

            HideConsoleAfterLogin(consoleProcess);
            return 0;
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                "无法启动 QCCA-NapCat-QCE：\n" + exception.Message,
                "QCCA-NapCat-QCE",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 1;
        }
    }

    private static void HideConsoleAfterLogin(Process consoleProcess)
    {
        while (!consoleProcess.HasExited)
        {
            if (IsNapCatLoggedIn())
            {
                consoleProcess.Refresh();
                if (consoleProcess.MainWindowHandle != IntPtr.Zero)
                {
                    ShowWindow(consoleProcess.MainWindowHandle, SwHide);
                }
                return;
            }
            Thread.Sleep(1500);
        }
    }

    private static bool IsNapCatLoggedIn()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:3000/get_login_info");
            request.Timeout = 1500;
            request.ReadWriteTimeout = 1500;

            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            using (var reader = new StreamReader(stream))
            {
                var serializer = new JavaScriptSerializer();
                var root = serializer.DeserializeObject(reader.ReadToEnd()) as Dictionary<string, object>;
                if (root == null || !root.ContainsKey("data"))
                {
                    return false;
                }

                var data = root["data"] as Dictionary<string, object>;
                if (data == null || !data.ContainsKey("user_id"))
                {
                    return false;
                }

                long userId;
                return long.TryParse(Convert.ToString(data["user_id"]), out userId) && userId > 0;
            }
        }
        catch (WebException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }
}
