' Avvia il server senza finestra (da mettere in shell:startup per l'avvio automatico con Windows)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw server.py", 0, False
