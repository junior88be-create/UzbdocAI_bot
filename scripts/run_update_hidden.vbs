' update.ps1 ni oynasiz ishga tushirish - Task Scheduler har 5 daqiqada chaqiradi
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & dir & "\update.ps1""", 0, True
