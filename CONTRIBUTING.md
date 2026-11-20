# Contributing

## Hardware reports

The most useful contribution is a report from hardware or a system that has not
been tried yet. The README has a table of what has been tested. If you use a
MINI MK2, CR-mode firmware, Linux, Windows, or one of the release downloads,
please open a "Hardware report" issue and say what worked and what did not.

## Reporting a problem

Open a "Bug report" issue. Run the failing command with `-v` in front (for
example `axon -v set left=120`) and include what it prints. For problems with
`axon flash`, include only the last 30 lines, because the full log contains the
contents of the firmware file.

If the programmer stops answering completely, unplug its USB cable for a few
seconds and plug it back in before trying again.

## Working on the code

```
git clone https://github.com/normalday843812/axon-servo-programmer
cd axon-servo-programmer
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests
```

- The whole tool is one module, `axon.py`. [PROTOCOL.md](PROTOCOL.md) describes
  what it sends to the programmer and why.
- The tests need no hardware. Add one for anything you change that can be
  checked without a programmer.
- Anything that changes what is sent to the programmer needs a test on real
  hardware before it is merged. Say in the pull request which servo and
  operating system you used.
- Do not add Axon's software, firmware files, or decompiled code to the
  repository. `.gitignore` already excludes the usual file types.

## Making a release

1. Update the version in both `axon.py` (`__version__`) and `pyproject.toml`.
2. Add a section to [CHANGELOG.md](CHANGELOG.md).
3. Commit, then tag and push:

   ```
   git tag -a v0.3.0 -m "axon 0.3.0"
   git push origin main v0.3.0
   ```

GitHub Actions builds the downloads and publishes the release. The build fails
if the tag does not match the version in the code.
