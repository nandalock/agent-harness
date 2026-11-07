"""Host-native folder chooser for local deployments.

The browser's directory APIs never expose an absolute path, so a project picked
there can only be recreated by name under the sandbox root. This service opens
the OS folder dialog on the machine running the backend and returns the real
path. It is only offered to loopback clients with the local sandbox backend.

On Windows the dialog is owned by a tiny **topmost offscreen form**. Without an
owner the FolderBrowserDialog can sit behind the browser when the backend runs
as a background process (the Alt-key foreground trick alone did not help in our
tests); the topmost owner reliably makes the dialog the foreground window.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

_PICK_TIMEOUT_SECONDS = 30 * 60
_dialog_lock = threading.Lock()


class FolderPickerError(RuntimeError):
    pass


class FolderPickerBusy(FolderPickerError):
    pass


class FolderPickerUnavailable(FolderPickerError):
    pass


class FolderPickerFailed(FolderPickerError):
    pass


def available() -> bool:
    if os.environ.get("SANDBOX_BACKEND", "local").strip().lower() != "local":
        return False
    if sys.platform in ("win32", "darwin"):
        return True
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and bool(
            shutil.which("zenity") or shutil.which("kdialog")
        )
    return False


def _windows_command() -> list[str]:
    """Modern IFileOpenDialog (FOS_PICKFOLDERS), like DSH's native backend.

    The legacy ``FolderBrowserDialog`` is not used: it renders as the old tree
    picker, while DSH opens the Explorer-style ``IFileOpenDialog``. The COM
    dialog is owned by a tiny topmost offscreen form so it comes to the
    foreground even when the backend is a background process.
    """
    shell = shutil.which("powershell") or "powershell.exe"
    script = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Drawing;

[ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellItem
{
    [PreserveSig] int BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    [PreserveSig] int GetParent(out IShellItem ppsi);
    [PreserveSig] int GetDisplayName(uint sigdnName, out IntPtr ppszName);
    [PreserveSig] int GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    [PreserveSig] int Compare(IShellItem psi, uint hint, out int piOrder);
}

[ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IFileOpenDialog
{
    [PreserveSig] int Show(IntPtr parent);
    [PreserveSig] int SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
    [PreserveSig] int SetFileTypeIndex(uint iFileType);
    [PreserveSig] int GetFileTypeIndex(out uint piFileType);
    [PreserveSig] int Advise(IntPtr pfde, out uint pdwCookie);
    [PreserveSig] int Unadvise(uint dwCookie);
    [PreserveSig] int SetOptions(uint fos);
    [PreserveSig] int GetOptions(out uint pfos);
    [PreserveSig] int SetDefaultFolder(IShellItem psi);
    [PreserveSig] int SetFolder(IShellItem psi);
    [PreserveSig] int GetFolder(out IShellItem ppsi);
    [PreserveSig] int GetCurrentSelection(out IShellItem ppsi);
    [PreserveSig] int SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    [PreserveSig] int GetFileName(out IntPtr pszName);
    [PreserveSig] int SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
    [PreserveSig] int SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
    [PreserveSig] int SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
    [PreserveSig] int GetResult(out IShellItem ppsi);
}

[ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
public class FileOpenDialogCoClass { }

public static class MinidshFilePicker
{
    [DllImport("ole32.dll")]
    private static extern int CoInitializeEx(IntPtr pvReserved, uint dwCoInit);
    [DllImport("ole32.dll")]
    private static extern void CoUninitialize();
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    private const uint FOS_NOCHANGEDIR = 0x8;
    private const uint FOS_PICKFOLDERS = 0x20;
    private const uint FOS_FORCEFILESYSTEM = 0x40;
    private const uint SIGDN_FILESYSPATH = 0x80058000;
    private const int ERROR_CANCELLED_HR = unchecked((int)0x800704C7);

    public static string Pick(string title)
    {
        int init = CoInitializeEx(IntPtr.Zero, 2);
        if (init < 0) Marshal.ThrowExceptionForHR(init);
        Form owner = new Form();
        IFileOpenDialog dialog = null;
        try
        {
            owner.FormBorderStyle = FormBorderStyle.None;
            owner.ShowInTaskbar = false;
            owner.StartPosition = FormStartPosition.Manual;
            owner.Location = new Point(-32000, -32000);
            owner.Size = new Size(1, 1);
            owner.TopMost = true;
            owner.Show();

            dialog = (IFileOpenDialog)new FileOpenDialogCoClass();
            uint options;
            int hr = dialog.GetOptions(out options);
            if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            hr = dialog.SetOptions(options | FOS_NOCHANGEDIR | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
            if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            if (!String.IsNullOrEmpty(title))
            {
                hr = dialog.SetTitle(title);
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            }

            // The hidden topmost owner plus a synthesized Alt press lets a
            // background host process activate the dialog as foreground.
            SetForegroundWindow(owner.Handle);
            keybd_event(0x12, 0, 0, UIntPtr.Zero);
            keybd_event(0x12, 0, 2, UIntPtr.Zero);

            hr = dialog.Show(owner.Handle);
            if (hr == ERROR_CANCELLED_HR) return null;
            if (hr < 0) Marshal.ThrowExceptionForHR(hr);

            IShellItem item;
            hr = dialog.GetResult(out item);
            if (hr < 0) Marshal.ThrowExceptionForHR(hr);
            try
            {
                IntPtr ptr;
                hr = item.GetDisplayName(SIGDN_FILESYSPATH, out ptr);
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);
                try { return Marshal.PtrToStringUni(ptr); }
                finally { Marshal.FreeCoTaskMem(ptr); }
            }
            finally { Marshal.ReleaseComObject(item); }
        }
        finally
        {
            if (dialog != null) Marshal.ReleaseComObject(dialog);
            owner.Close();
            owner.Dispose();
            CoUninitialize();
        }
    }
}
'@
$path = [MinidshFilePicker]::Pick($env:MINIDSH_PICKER_TITLE)
if ($null -ne $path) { [Console]::Out.Write($path) }
"""
    return [shell, "-NoProfile", "-STA", "-NonInteractive", "-Command", script]


def _macos_command(title: str) -> list[str]:
    safe = title.replace("\\", "\\\\").replace('"', '\\"')
    return ["osascript", "-e", f'POSIX path of (choose folder with prompt "{safe}")']


def _linux_command(title: str) -> list[str] | None:
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", "--directory", "--title", title]
    if shutil.which("kdialog"):
        return ["kdialog", "--getexistingdirectory", str(os.path.expanduser("~")), "--title", title]
    return None


def pick_folder(title: str = "选择项目文件夹") -> str | None:
    """Open one native directory chooser; return its absolute path or None."""
    if not available():
        raise FolderPickerUnavailable("当前部署不支持本机文件夹选择器")
    if not _dialog_lock.acquire(blocking=False):
        raise FolderPickerBusy("已有一个文件夹选择窗口")
    try:
        env = os.environ.copy()
        env["MINIDSH_PICKER_TITLE"] = title
        if sys.platform == "win32":
            argv = _windows_command()
        elif sys.platform == "darwin":
            argv = _macos_command(title)
        else:
            argv = _linux_command(title)
            if argv is None:
                raise FolderPickerUnavailable("Linux 需要 zenity 或 kdialog")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=_PICK_TIMEOUT_SECONDS, env=env,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FolderPickerFailed(f"无法启动文件夹选择器: {exc}") from exc
        chosen = (result.stdout or "").strip()
        if sys.platform == "win32":
            if result.returncode == 0 and not chosen:
                return None
            if result.returncode != 0:
                raise FolderPickerFailed((result.stderr or "").strip() or f"退出码 {result.returncode}")
        else:
            if result.returncode == 1:
                return None
            if result.returncode != 0 or not chosen:
                raise FolderPickerFailed((result.stderr or "").strip() or f"退出码 {result.returncode}")
        return chosen
    finally:
        _dialog_lock.release()
