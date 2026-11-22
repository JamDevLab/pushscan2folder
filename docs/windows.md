# Running on Windows

pushscan2folder runs natively on Windows 10 and 11 as a single program, as an alternative to Canon's own scan software. It registers a name on the printer panel, polls the printer, and saves scans into a folder. Nothing needs to be installed.

Linux and Docker are described in the README. macOS is covered at the end of this page.

## Download

1. Open the Releases page of the project on GitHub and download `pushscan2folder.exe` (and, if you like, `SHA256SUMS.txt`).
2. Put it in a folder of your own, for example `C:\Tools\pushscan2folder\`.
3. To check the download, run `Get-FileHash pushscan2folder.exe` in PowerShell and compare it with `SHA256SUMS.txt`.

The exe is built by GitHub Actions from the tagged source. It is not code signed.

## First run and SmartScreen

Because the exe is unsigned, Windows SmartScreen shows "Windows protected your PC" the first time. Click "More info", then "Run anyway". If you downloaded it in a browser, you can also right click the file, open Properties, and tick "Unblock".

Open PowerShell or a Command Prompt in the folder and start it with the IP address of the printer:

```
.\pushscan2folder.exe --printer 192.168.1.50 run
```

The log shows the registration. On the printer panel, "Scan" then "Computer" lists a name like `USER  PCNAME`. Pick it and press Start. Scans are saved to `Documents\Scans` in your user folder. Stop the program with Ctrl+C, it releases the name on the printer before it exits.

To see all options: `.\pushscan2folder.exe --help`.

## Firewall

The program only makes outgoing connections to the printer, so Windows Firewall needs no rule for the scanning itself.

The optional web page is different. With `--web` it listens on a port (8080 by default) and binds to all addresses unless you say otherwise. Windows then asks once whether to allow the program on private or public networks. To keep the page on this PC only, use:

```
.\pushscan2folder.exe --printer 192.168.1.50 run --web --web-bind 127.0.0.1
```

Nothing is exposed to other devices then, and no firewall rule is needed. Open http://127.0.0.1:8080 in a browser. The web page needs a password; set it before the start, for example:

```
$env:PUSHSCAN_WEB_PASSWORD = "a long password of your own"
```

For autostart, put the password in a file and set `PUSHSCAN_WEB_PASSWORD_FILE` to its path (see the web page documentation).

## Where files go

| What | Location |
| --- | --- |
| Config file (optional) | `%APPDATA%\pushscan2folder\config.toml` |
| Scans | `Documents\Scans` in your user folder (`C:\Users\NAME\Documents\Scans`), one subfolder per target |
| Log file | only with `--log-file PATH` |

The program looks for the config file automatically. Use `--config PATH` to use another one. If your Documents folder is moved (for example by OneDrive), set `output` in the config file to the real path, because the default is `Documents` below your user folder.

A new config file written by the web page is meant to be private. On Windows the "private" file mode (0600) cannot be applied; the file is protected by your user profile folder, which other standard users cannot read.

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

Then `.\pushscan2folder.exe run` is enough. The other keys are described in `config.example.toml`.

## Start at logon

```
.\pushscan2folder.exe --config "%APPDATA%\pushscan2folder\config.toml" --log-file "%APPDATA%\pushscan2folder\pushscan2folder.log" --install-autostart
```

(In PowerShell write `$env:APPDATA` instead of `%APPDATA%`.)

This adds the entry `pushscan2folder` to your per-user Run list (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`). It needs no administrator rights. At every logon the program starts minimised in a console window, with exactly the options you gave next to `--install-autostart`. Paths are stored as absolute paths. A Task Scheduler logon task would need administrator rights on most systems, which is why the Run list is used.

Keep a log with `--log-file`; a started-at-logon program has no visible console otherwise. The file rotates at 1 MB and keeps 3 old files.

Do not move or rename the exe afterwards. If you do, install again from the new place.

To remove it:

```
.\pushscan2folder.exe --remove-autostart
```

You can also look at it in Task Manager, tab "Startup apps", or in Settings, Apps, Startup.

## Uninstall

1. Run `pushscan2folder.exe --remove-autostart`.
2. Delete the exe.
3. Delete `%APPDATA%\pushscan2folder\` if you want to remove the config and the log.
4. Your scans in `Documents\Scans` stay until you delete them.

## Using it next to Canon IJ Scan Utility

Both can be installed at the same time. Each registers its own entry on the printer panel, so you see both names in the list and choose which one receives the scan. Only run one program per name.

## Running from source

If you prefer not to use the exe, install Python 3.11 or newer from python.org and use the source of a release (or `git clone`):

```
cd pushscan2folder
$env:PYTHONPATH = "src"
python -m pushscan2folder --printer 192.168.1.50 run
```

The same command line options apply. Use `python -m pushscan2folder --install-autostart ...` to register autostart for the Python variant. Run the tests with `python -m unittest discover -s tests`.

## Limits and notes

- The tool is tested by GitHub Actions on Windows (unit tests and the exe build). The author does not run it on a real Windows machine every day; please open an issue if something fails.
- Ctrl+C and Ctrl+Break stop it cleanly. Closing the console window also stops it, but Windows gives the program only a few seconds then; if the name is not released in time, the printer drops it after about a minute.
- Console output replaces characters your console code page cannot show with `?`. The log file is UTF-8.

## macOS

Not packaged and not tested on real hardware; the unit tests run on macOS in GitHub Actions. Install Python 3.11 or newer and run from source:

```
cd pushscan2folder
PYTHONPATH=src python3 -m pushscan2folder --printer 192.168.1.50 run
```

The config file is `~/.config/pushscan2folder/config.toml` (or `$XDG_CONFIG_HOME`), and scans go to `~/Documents/Scans` unless you set `output`. `--install-autostart` is Windows only; on macOS use a launchd agent if you want a background service. Reports from Mac users are welcome.
