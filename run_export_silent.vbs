Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run """C:\Program Files\Blackmagic Design\DaVinci Resolve\ResolvePython\ResolvePython.exe"" """ & ScriptDir & "\export_timeline.py""", 0, False
Set FSO = Nothing
Set WshShell = Nothing
