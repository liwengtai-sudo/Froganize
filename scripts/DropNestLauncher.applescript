on run
    set resourceRoot to (POSIX path of (path to me)) & "Contents/Resources/"
    set launcherPath to resourceRoot & "launch_dropnest_web.sh"
    set configPath to resourceRoot & "launcher.conf"

    set configText to read (POSIX file configPath) as «class utf8»
    set configLines to paragraphs of configText
    if (count of configLines) is less than 2 then
        error "The launcher configuration is incomplete."
    end if

    set projectRoot to item 1 of configLines
    set workspacePath to item 2 of configLines
    set shellCommand to (quoted form of launcherPath) & " " & ¬
        (quoted form of workspacePath) & " " & ¬
        (quoted form of projectRoot)
    -- This is the Standard Additions "do shell script" event.
    «event sysoexec» shellCommand
end run
