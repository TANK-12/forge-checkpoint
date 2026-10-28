@TITLE@

Forge is one window for many small local apps: games, creative tools,
readers and research helpers. Each app is its own little web server on this
computer; Forge starts an app the first time you open it and stops them all
when you close Forge. Nothing is sent anywhere unless an app says so (a few
can look things up on the web when you ask them to).

Forge brings its own Python, so there is nothing else to install, and it
never needs administrator rights.


Install
-------

@linux@
Open a terminal and paste this one line (it expects the download in your
Downloads folder; if your browser saved it somewhere else, put that folder
after cd instead):

    cd ~/Downloads && tar xzf forge-@VERSION@-linux-x64.tar.gz && ./Forge/forge --install

It copies Forge into your home folder, adds it to your apps menu with its
icon, and starts it. From then on, open Forge from the apps menu (search
for "Forge"). The download and the unpacked Forge folder are no longer
needed and can go.

To try Forge without installing it, run ./Forge/forge instead of the
--install part; it then runs from the unpacked folder.

Forge opens in a GTK window when the system Python has GTK and WebKit
(Arch: python-gobject and webkit2gtk-4.1; Debian and Ubuntu: python3-gi and
gir1.2-webkit2-4.1), otherwise in Chrome, Chromium, Edge or Brave without
tabs, otherwise in your browser.
@end@
@windows-setup@
The easy way, with Forge-Setup-@VERSION@.exe:

  1. Double-click Forge-Setup-@VERSION@.exe.
  2. Windows says "Windows protected your PC", because this test release
     is not signed: click "More info", then "Run anyway".
  3. Click Next, then Install, then Finish. Forge starts, and it is in
     your Start menu from then on.

It installs for you only, in %LOCALAPPDATA%\Programs\Forge.

@end@
@windows@
From the zip (no setup program):

  1. Right-click the zip, choose "Extract All" and click "Extract". The
     folder it makes beside the zip (in Downloads) is fine; keep it, Forge
     runs from there. Avoid a folder OneDrive keeps in sync, which on many
     computers includes Documents and Desktop.
  2. Open the Forge folder and double-click Forge.cmd.
  3. Windows warns that this test release is not signed. If it says
     "Windows protected your PC", click "More info", then "Run anyway". If
     it asks "Do you want to run this file?", click "Run".

Forge opens in a Microsoft Edge window with no tabs. To open it again
later, double-click Forge.cmd again.

If Windows 11 says Smart App Control blocked Forge, there is no way past it
for an unsigned program: this test release cannot run on that computer.
@end@
@macos@
  1. Double-click the download to unpack it, then drag Forge.app into
     Applications.
  2. This release is not signed by Apple, so macOS stops it the first time
     (it may even call it damaged). Open Terminal and run this once:
       xattr -dr com.apple.quarantine /Applications/Forge.app
     (Or open System Settings, Privacy & Security, and choose "Open Anyway"
     next to Forge after the first try.)
  3. Open Forge from Applications. It opens in its own window.
@end@


Where your things are kept
--------------------------

The first time Forge starts it asks where to keep your settings, saves and
each app's data. They stay apart from the program, so installing a newer
Forge keeps them. Unless you choose another place they are in:

@linux@
  ~/.local/share/forge-release/Forge data
  (and Forge's own small files: ~/.config/forge-release, ~/.cache/forge-release,
  ~/.local/state/forge-release)
@end@
@windows@
  %APPDATA%\Forge\Forge data
  (and Forge's own small files: %APPDATA%\Forge, %LOCALAPPDATA%\Forge)
@end@
@macos@
  ~/Library/Application Support/Forge/Forge data
  (and Forge's own small files: ~/Library/Caches/Forge, ~/Library/Logs/Forge)
@end@

Arcade's best scores and a few small remembered choices (such as the last
page you had open) are kept by Forge's window itself, on this computer:
moving your things to another place does not take them along.


Remove Forge
------------

@linux@
In a terminal:

    ~/.local/share/forge-release/app/forge --uninstall

This takes Forge and its menu entry out and keeps your things. To remove
your things as well, add --remove-data: it lists the folders and asks
before it removes anything, and it never touches a place you chose
yourself. If you never installed Forge, delete the unpacked Forge folder.
@end@
@windows-setup@
If you used the setup program: Settings, Apps, Installed apps, find Forge,
choose Uninstall. It keeps your things unless you say yes when it asks
about them (a place you chose yourself is never touched).

@end@
@windows@
If you used the zip: close Forge and delete the Forge folder. Your things
stay; delete the folders above too if you want them gone.
@end@
@macos@
Drag Forge.app to the Bin. Your things stay; delete the folders above too
if you want them gone.
@end@


Options
-------

  forge --window browser     open in a browser tab instead
  forge --window app         open in Edge, Chrome, Chromium or Brave without tabs
  forge --port 8500          the home screen's port (the apps keep theirs)
  forge --port-offset 1000   move every port, to run beside another Forge
  forge --apps cosmos,mint   only these apps
  forge --smoke              start every app, check each answers, then stop

@linux@
  Run them as ./Forge/forge --smoke and so on from where you unpacked it,
  or, once installed, ~/.local/share/forge-release/app/forge --smoke.
@end@
@windows@
  On Windows run them as forge-console.cmd --window browser and so on, in
  the Forge folder (Forge.cmd starts Forge without a console window).
@end@
@macos@
  On macOS run them as Forge.app/Contents/MacOS/Forge --smoke.
@end@


Apps that need another program
------------------------------

@NEEDS@

Jan (https://jan.ai) is a free app that runs AI models on this computer.
Install it, download a model in it and turn on its local API server (port
1337); the apps above use it for their AI parts and run without it.


What works differently on this system
-------------------------------------

@SYSTEM_NOTES@


If something goes wrong
-----------------------

Each app writes a log in Forge's logs folder (forge.log is the launcher's
own):

@linux@
  ~/.local/state/forge-release/logs
@end@
@windows@
  %LOCALAPPDATA%\Forge\Logs
@end@
@macos@
  ~/Library/Logs/Forge
@end@

"forge --smoke" checks every app and says which one failed. If another
program already uses the home screen's port, Forge moves to a free one by
itself. Each app has a fixed port (8401 to 8499): if another program
already uses one, that app says it did not start. Close the other program,
or start Forge with --port-offset 1000 to move every port.

THIRD-PARTY.txt lists the Python and the packages bundled here and their
licences.
