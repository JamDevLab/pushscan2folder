# Contributing

## Development

- Python >= 3.11, standard library only. Please do not add dependencies.
- Run the tests before every commit:

  ```sh
  PYTHONPATH=src python3 -m unittest discover -s tests
  ```

- Code, comments, commit messages and issues are in English.
- Keep commits small, with a clear message each.
- Core logic changes need a test.

## Clean-room rules

This project is an independent implementation made for interoperability
(compare Section 69e UrhG and Art. 6 of EU Directive 2009/24/EC). This is not
legal advice. To keep the project clear of Canon code:

- Never commit Canon binaries, installers, DLLs, disassembly, decompiled code
  or memory addresses taken from Canon software. Do not paste them into
  issues or pull requests either.
- Issues and PRs may only contain protocol observations: hex dumps of the
  network traffic between your own PC and your own printer, and the panel
  settings you chose.

## Reporting a new printer model

1. Run the tool with verbose logging:
   `PYTHONPATH=src python3 -m pushscan2folder -v --printer <ip> run`
2. Start one scan from the panel per changed setting (document type, colour,
   size, format, resolution, ...), changing only one setting at a time.
3. Open an issue with the `scan requested ... interrupt=` log lines, each with
   the setting you changed, plus the model name and the firmware version if
   known. Say whether scanning from the platen and the ADF worked.

Verified models are listed in the "Tested models" table in the README.
