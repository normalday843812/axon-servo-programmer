#!/bin/sh
# Re-run the deobfuscation + decompilation of the official app.
#   ./redo.sh path/to/Axon_Software_MK2_vX.exe [output-dir]
# Needs ./toolchain (see README.md in this folder). Output goes to ./redo-output
# unless a second argument is given. Use this when Axon ships a new app version.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
export DOTNET_ROOT="$HERE/toolchain/dotnet"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
EXE="${1:-$HERE/../official/Axon_Software_MK2_v1.1.2.exe}"
OUT="${2:-$HERE/redo-output}"
if [ ! -f "$EXE" ]; then
    echo "usage: $0 path/to/Axon_Software_MK2.exe [output-dir]" >&2
    exit 1
fi
if [ ! -x "$HERE/toolchain/de4dot/de4dot" ] || [ ! -x "$HERE/toolchain/ilspycmd/ilspycmd" ]; then
    echo "toolchain not found in $HERE/toolchain - see README.md in this folder" >&2
    exit 1
fi
mkdir -p "$OUT/source"
# 1. de4dot undoes the Dotfuscator obfuscation (names, strings, control flow)
"$HERE/toolchain/de4dot/de4dot" "$EXE" -o "$OUT/deobfuscated.exe"
# 2. ILSpy turns the cleaned .NET assembly back into a C# project
"$HERE/toolchain/ilspycmd/ilspycmd" -p -o "$OUT/source" "$OUT/deobfuscated.exe"
echo "Readable C# is in $OUT/source  (main window: AGF.cs)"
