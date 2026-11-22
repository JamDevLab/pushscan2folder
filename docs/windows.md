# Running on Windows

pushscan2folder runs natively on Windows 10 and 11 as a single program, as an alternative to Canon's own scan software. It registers a name on the printer panel, polls the printer, and saves scans into a folder. It comes with an installer that needs no administrator rights.

Linux and Docker are described in the README. macOS is covered at the end of this page.

## Install

1. Open the Releases page of the project on GitHub and download `pushscan2folder-VERSION-windows-setup.exe` (and, if you like, `SHA256SUMS.txt`).
2. To check the download, run `Get-FileHash pushscan2folder-VERSION-windows-setup.exe` in PowerShell and compare it with `SHA256SUMS.txt`.
3. Run the installer. It asks for its language (English or German). It installs for your user only, needs no administrator rights, and puts the program into `%LOCALAPPDATA%\Programs\pushscan2folder`.

The installer creates a Start menu folder "pushscan2folder" with three entries:

- "pushscan2folder" starts the program normally,
- "pushscan2folder setup" runs the setup questions (`setup`),
- "Stop pushscan2folder" stops the background instance (`stop`).

A desktop icon is optional and unchecked by default. At the end the installer offers "Set up and start pushscan2folder". It opens the console window with the setup questions (see below).

The installer and the program are built by GitHub Actions from the tagged source. The installer is built with Inno Setup around a PyInstaller folder build. It is not code signed.

To update, run the newer installer. If the background instance runs, the installer stops it (with `stop`, so it waits for a running scan), replaces the files and starts it again. Your settings stay.

### Virus scanner warnings

Programs packed with PyInstaller are sometimes flagged by virus scanners, for example by Microsoft Defender as `Trojan:Win32/Bearfoos.A!ml`. The `!ml` means a machine learning guess, not a known signature. To make this rare, the installed program is a folder build (nothing is unpacked at start) with a bootloader compiled by the build itself. If it still happens, check the checksum of the installer, restore the file from the protection history and, if you like, report the false positive at https://www.microsoft.com/wdsi/filesubmission. Please open an issue too, so it can be reported for the release.

## First run and SmartScreen

Because the installer is unsigned, Windows SmartScreen may show "Windows protected your PC" when you run it. Click "More info", then "Run anyway". If you downloaded it in a browser, you can also right click the file, open Properties, and tick "Unblock".

Start "pushscan2folder" from the Start menu (or the desktop icon, or `pushscan2folder.exe` in the program folder). A console window opens. When there is no config file yet, the program says hello and asks a few questions (this is the `setup` command):

- the printer: setup first searches the network for eSCL scanners and lists the ones that answer with a number (see [Finding the printer](#finding-the-printer)); you pick a number or type the IP address or host name. The address is checked right away, and you can type it again or continue anyway,
- the name that appears on the printer panel (default `USER  PCNAME`),
- the folder for scans (default `Documents\Scans`; the scans go straight into this folder, not into a subfolder),
- whether to turn on the web page (default no; if yes: port, bind address and a password typed twice),
- whether to open the folder after each scan (default yes, see [Open the folder after a scan](#open-the-folder-after-a-scan)),
- whether to start the program automatically when you log in (default yes).

Then it writes `%APPDATA%\pushscan2folder\config.toml`, shows where everything is and asks "Run in the background now?" (default yes, see below). If you answer no, it asks "Start now?" and runs in the console window. The web password is not stored in `config.toml` but in `web_password.txt` next to it. `%APPDATA%` belongs to your user account only.

The next time you start it by double click or from the Start menu, the program finds the config file and shows the current settings: the printer, each panel name with its folder, and whether the web page is on. Then it asks:

- `1` use these settings (default),
- `2` change them (the setup questions, with your panel names and folders kept),
- `3` start over with a new configuration. The old file is kept as `config.toml.bak`. If you start over again, the older copy stays and the next one is named `config.toml.2.bak`, then `config.toml.3.bak`, and so on.

If the config file is broken, the program says so and offers to start over, also keeping the `.bak` copy. If the program already runs in the background, it says so and tells you to run `pushscan2folder stop` first to change the settings.

This question only appears on a double click. Typed in a command prompt with arguments, the program just runs, and so it does on Linux and macOS.

With `1` the program runs. It prints a short summary (version, printer, config file, panel name and folder, web page, log file) and "Press Ctrl+C to stop." Closing this window stops the program; the summary says so. The log shows the registration. On the printer panel, "Scan" then "Computer" lists a name like `USER  PCNAME`. Pick it and press Start. Stop the program with Ctrl+C; it releases the name on the printer before it exits.

If the console window was opened only for this program, it waits for Enter before it closes, so you can read the last message. This never happens in a window you opened yourself, when the input is not interactive, or when the program was started by the logon entry. `--no-pause` (or `PUSHSCAN_NO_PAUSE=1`) turns it off.

To change the settings later, edit the config file or run the questions again (also in the Start menu as "pushscan2folder setup"). Setup keeps your panel names and folders if the file already has `[[target]]` entries:

```
.\pushscan2folder.exe setup
```

You can also use the command line without any questions. The subcommand `run` is the default and can be left out:

```
.\pushscan2folder.exe --printer 192.168.1.50
```

To see all options: `.\pushscan2folder.exe --help`.

## Run in the background

A program started by double click lives in its console window, and closing the window ends it. To keep it running without a window:

```
.\pushscan2folder.exe start
```

`start` launches the program detached in the background with the current config and returns at once. It takes the same options as `run` (for example `--config PATH`, `--web`). The background process has no console window and keeps running after you close the window you started it from. Its log goes to `%LOCALAPPDATA%\pushscan2folder\pushscan2folder.log` unless you give `--log-file PATH`. If an instance is already running, `start` refuses and says so.

```
.\pushscan2folder.exe status
.\pushscan2folder.exe stop
```

- `status` says whether the background instance runs, its PID and log file, and shows the last lines of the log. The exit code is 0 when it runs and 1 when it does not.
- `stop` asks the instance to stop. It leaves its loop within a few seconds (a scan in progress finishes first) and releases its names on the printer, so they leave the panel. A detached process gets no Ctrl+C, so `stop` writes a stop request file that the instance checks about once per second. If the instance has not ended after 30 seconds, it is terminated, and the printer drops the names after about a minute. While a scan runs, `stop` waits up to 10 minutes instead and prints "A scan is running; it is finished and saved first ...". A multi-page platen scan that waits for the next page ends right away with the pages scanned so far, and they are saved.

The instance keeps a lock file, a PID file and the stop request file in `%LOCALAPPDATA%\pushscan2folder\`. The lock is held by the running process and dropped by Windows when it ends, so a leftover file after a crash or reboot never blocks the next `start`.

A foreground `run` does not use the lock, `stop` does not stop it, and `start` does not notice it. Both would register the same names on the printer, so a foreground `run` refuses to start while the background instance runs. It says so and points to `pushscan2folder stop`.

## Finding the printer

If no printer is configured yet, `pushscan2folder setup` (and the first double click) searches the local network for eSCL scanners with mDNS (Bonjour, service `_uscan._tcp`). This takes about 2 seconds. Each scanner that answers is listed with its address and model and a number:

```
Searching the network for scanners (eSCL, a few seconds) ...
  1  192.168.1.50  Canon TR8500 series
Number of your printer, or its IP address [1]:
```

Type the number, or type an IP address if your printer is not listed. If nothing answers, setup asks for the IP address as before. A firewall that blocks multicast, or a VPN, can be the reason. The IP address is shown in the network settings on the printer panel. Windows Firewall may ask once whether to allow the program for this search.

## Open the folder after a scan

With `open_after_scan = "folder"` in `[defaults]` (or `--open-after-scan folder`, `PUSHSCAN_OPEN_AFTER_SCAN=folder`), Explorer opens the folder with the new file selected after each scan. With `"file"` the scan itself opens in your PDF viewer. The default is `"off"`. Setup asks "Open the folder after each scan?" and writes `"folder"` for yes. A scan with several pages or files opens once. If opening fails, the log shows a warning and the scan is kept anyway. The option is also in the Settings page of the web interface. It needs a logged-in desktop user, so it is meant for a PC, not for a server.

## Firewall

The program only makes outgoing connections to the printer, so Windows Firewall needs no rule for the scanning itself.

The optional web page is different. With `--web` (or `enabled = true` in the `[web]` table of the config file) it listens on a port (8080 by default) and binds to all addresses unless you say otherwise. The setup questions suggest `127.0.0.1`. Windows then asks once whether to allow the program on private or public networks. To keep the page on this PC only, use:

```
.\pushscan2folder.exe --printer 192.168.1.50 --web --web-bind 127.0.0.1
```

Nothing is exposed to other devices then, and no firewall rule is needed. Open http://127.0.0.1:8080 in a browser. The web page needs a password; set it before the start, for example:

```
$env:PUSHSCAN_WEB_PASSWORD = "a long password of your own"
```

Setup stores the password in `web_password.txt` next to the config file and names it in `[web] password_file`, which is what autostart needs. By hand, use a file and set `PUSHSCAN_WEB_PASSWORD_FILE` or `password_file` (see the web page documentation).

## Where files go

| What | Location |
| --- | --- |
| Config file (written by setup) | `%APPDATA%\pushscan2folder\config.toml` |
| Web password (if the web page is on) | `%APPDATA%\pushscan2folder\web_password.txt` |
| Program | `%LOCALAPPDATA%\Programs\pushscan2folder` |
| Scans | `Documents\Scans` in your user folder (`C:\Users\NAME\Documents\Scans`). Setup creates one target that saves straight into it. |
| Log file | `%LOCALAPPDATA%\pushscan2folder\pushscan2folder.log` for the background instance and autostart; with `--log-file PATH` anywhere else |
| Background instance files (lock, PID, stop request) | `%LOCALAPPDATA%\pushscan2folder\` |

The program looks for the config file automatically. Use `--config PATH` to use another one. If your Documents folder is moved (for example by OneDrive), set `output` in the config file to the real path, because the default is `Documents` below your user folder.

A new config file written by the web page is meant to be private. On Windows the "private" file mode (0600) cannot be applied; the file is protected by your user profile folder, which other standard users cannot read.

A target with `output = "."` saves into the output directory itself, without a subfolder. That is what the setup questions write. Without `output`, a target saves into `<output>/<name>`.

Folder names for targets are made valid for Windows: characters such as `<>:"/\|?*` become `_`, names that end in a dot are trimmed, and reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9`, `LPT1` to `LPT9`) get a `_` in front. A target called `CON` therefore saves into `_CON`.

## Example config

Save this as `%APPDATA%\pushscan2folder\config.toml`. Use forward slashes or single quotes for Windows paths in TOML, because a backslash in a normal string is an escape character.

```toml
printer = "192.168.1.50"
output = 'D:\Scans'        # single quotes: backslashes are taken literally

[defaults]
resolution = 300
format = "pdf"

[[target]]
name = "Scan"

[[target]]
name = "Paperless"
output = "paperless/inbox"    # below the output folder
```

Then `.\pushscan2folder.exe` is enough. The other keys are described in `config.example.toml`.

## Start at logon

The setup questions offer this and run the command below for you. By hand:

```
.\pushscan2folder.exe --config "%APPDATA%\pushscan2folder\config.toml" --log-file "%APPDATA%\pushscan2folder\pushscan2folder.log" --install-autostart
```

(In PowerShell write `$env:APPDATA` instead of `%APPDATA%`.)

This adds the entry `pushscan2folder` to your per-user Run list (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). It needs no administrator rights. At every logon the entry runs `pushscan2folder start` with exactly the options you gave next to `--install-autostart` plus `--no-pause`. That starts the background instance (see above), so no window stays open. The console window of the short `start` call may flash for a moment. If an instance is already running, the entry does nothing. Paths are stored as absolute paths. A Task Scheduler logon task would need administrator rights on most systems, which is why the Run list is used.

Keep a log with `--log-file`; the background instance has no visible console. Without it the log goes to the default path above. The file rotates at 1 MB and keeps 3 old files.

Do not move or rename the exe afterwards. If you do, install again from the new place. The installer takes care of this when you update.

To remove it:

```
.\pushscan2folder.exe --remove-autostart
```

You can also look at it in Task Manager, tab "Startup apps", or in Settings, Apps, Startup.

## Uninstall

Use Windows Settings, Apps, pushscan2folder. The uninstaller stops the background instance with `stop` (it waits for a running scan, and the names leave the panel), removes the autostart entry and asks whether to delete the settings and the log too (default no). Your scans are never deleted.

`pushscan2folder uninstall` does the same cleanup from the command line. It stops the background instance (waiting for a running scan like `stop`), removes the autostart entry, and then lists the config folder (`%APPDATA%\pushscan2folder\`, with `config.toml` and `web_password.txt`) and the log and state folder (`%LOCALAPPDATA%\pushscan2folder\`). It asks whether to delete them, default no. Your scans are never deleted, and a folder that contains your scan folder is kept. On an installed copy it ends with the hint to remove the program under Settings, Apps. For a copy without the installer (for example from pip or the source) it reminds you to remove the program yourself, because Windows cannot delete a program while it runs.

For scripts, `uninstall --yes` does not ask and keeps the config and log folders; `uninstall --yes --purge` deletes them. Folders given with `--config PATH` are not touched.

On Linux and macOS the command does the same except for the autostart entry (the program file is removed the way it was installed, for example `pip uninstall pushscan2folder`). By hand on Windows: `--remove-autostart`, delete the program folder, delete the two data folders.

## Using it next to Canon IJ Scan Utility

Both can be installed at the same time. Each registers its own entry on the printer panel, so you see both names in the list and choose which one receives the scan. Only run one program per name.

## Running from source

If you prefer not to use the installer, install Python 3.11 or newer from python.org and use the source of a release (or `git clone`):

```
cd pushscan2folder
$env:PYTHONPATH = "src"
python -m pushscan2folder --printer 192.168.1.50
```

The same command line options apply. Use `python -m pushscan2folder --install-autostart ...` to register autostart for the Python variant. Run the tests with `python -m unittest discover -s tests`.

## Limits and notes

- The tool is tested by GitHub Actions on Windows (unit tests and the exe build). The author does not run it on a real Windows machine every day; please open an issue if something fails.
- Run with `start` to keep it going without a window. In a foreground window, Ctrl+C and Ctrl+Break stop it cleanly. Closing the console window also stops it, but Windows gives the program only a few seconds then; if the name is not released in time, the printer drops it after about a minute.
- Console output replaces characters your console code page cannot show with `?`. The log file is UTF-8.

## macOS

Not packaged and not tested on real hardware; the unit tests run on macOS in GitHub Actions. Install Python 3.11 or newer and run from source:

```
cd pushscan2folder
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50
```

The config file is `~/.config/pushscan2folder/config.toml` (or `$XDG_CONFIG_HOME`), and scans go to `~/Documents/Scans` unless you set `output`. `--install-autostart` is Windows only; on macOS use a launchd agent if you want a background service. Reports from Mac users are welcome.
