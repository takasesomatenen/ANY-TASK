' KSD案件 柱状図PDF → .ai 一括変換（任意・コマンドから起動したい場合のみ）
'
'   cscript //nologo run_on_windows.vbs
'
' Illustrator を COM 経由で起動し、同じフォルダの pdf_to_ai.jsx を実行する。
' ※このVBScriptはIllustrator実機で未検証。うまく動かない場合は、Illustratorの
'   「ファイル > スクリプト > その他のスクリプト...」から pdf_to_ai.jsx を直接
'   実行すれば同じ処理になる（そちらが本来の手順）。
'
' 変換対象フォルダは pdf_to_ai.jsx 側の CONFIG.SRC_FOLDER で指定する。
' 空のままだとフォルダ選択ダイアログが出る。

Option Explicit

Dim fso, scriptPath, illustrator
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "pdf_to_ai.jsx")

If Not fso.FileExists(scriptPath) Then
    WScript.Echo "pdf_to_ai.jsx が見つからない: " & scriptPath
    WScript.Quit 1
End If

On Error Resume Next
Set illustrator = CreateObject("Illustrator.Application")
If Err.Number <> 0 Then
    WScript.Echo "Illustrator を起動できない（インストール状況とCOM登録を確認）: " & Err.Description
    WScript.Quit 1
End If

illustrator.DoJavaScriptFile scriptPath
If Err.Number <> 0 Then
    WScript.Echo "スクリプトの実行に失敗: " & Err.Description
    WScript.Echo "Illustratorの「ファイル > スクリプト > その他のスクリプト...」から手動実行してください。"
    WScript.Quit 1
End If
On Error Goto 0

WScript.Echo "変換処理を実行した。詳細は出力フォルダの conversion_log_*.txt を確認すること。"
