Option Explicit

Dim shell, fileSystem, packageDir, launcher
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

packageDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
launcher = fileSystem.BuildPath(packageDir, "launcher-user.bat")

shell.CurrentDirectory = packageDir
shell.Environment("PROCESS")("QCCA_HEADLESS") = "1"
shell.Run "cmd.exe /d /c """ & launcher & """", 0, False
