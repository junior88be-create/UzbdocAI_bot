' run_bot.bat ni oynasiz (orqa fonda) ishga tushirish - Task Scheduler shuni chaqiradi
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run """" & dir & "\run_bot.bat""", 0, False
