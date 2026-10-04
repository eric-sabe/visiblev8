#!/bin/bash
set -e

export PATH="/work/depot_tools:$PATH"
export DEPOT_TOOLS_UPDATE=0

cd /work/v8

echo "=== Step 1: Checking git branch and status ==="
git checkout vv8-155
git status

echo "=== Step 2: Generating build files with GN ==="
mkdir -p out/Release
cat > out/Release/args.gn << 'EOF'
is_debug = false
dcheck_always_on = false
symbol_level = 0
v8_enable_lazy_source_positions = false
vv8_trace_properties = true
EOF

/work/v8/buildtools/linux64/gn gen out/Release

echo "=== Step 3: Compiling v8_shell ==="
/usr/bin/ninja -C out/Release v8_shell

echo "=== Step 4: Setting up artifacts for tests ==="
VERSION="155.0.8059.30"
mkdir -p /artifacts/$VERSION
cp out/Release/v8_shell /artifacts/$VERSION/vv8-shell-$VERSION
if [ -f out/Release/snapshot_blob.bin ]; then
    cp out/Release/snapshot_blob.bin /artifacts/$VERSION/
fi
if [ -f out/Release/icudtl.dat ]; then
    cp out/Release/icudtl.dat /artifacts/$VERSION/
fi
chmod +x /artifacts/$VERSION/vv8-shell-$VERSION

echo "=== Step 5: Testing basic v8_shell invocation ==="
cd /tmp
rm -f vv8-*.log
/artifacts/$VERSION/vv8-shell-$VERSION -e "console.log('VisibleV8 standalone test execution');"
ls -la vv8*

echo "=== Step 6: Running VisibleV8 regression suite (10 tests) ==="
rm -rf /testsrc
cp -r /build/visiblev8/tests/src /testsrc
sed -i 's/\r$//' /testsrc/*

TEST_SRC="/testsrc"
EXPECTED_LOGS="/build/visiblev8/tests/logs/trace-apis-obj"
TOOLS="/build/visiblev8/tests/logs"
SCRATCH_DIR=$(mktemp -d)
V8_SHELL="/artifacts/$VERSION/vv8-shell-$VERSION"

exitstatus=0
for script in "$TEST_SRC"/*.js; do
    sbase=$(basename "$script")
    sbase=${sbase%.js}

    echo -n "  Testing $sbase.js: "
    rm -f vv8-*.log
    "$V8_SHELL" --no-maglev --no-turbofan "$script" >/dev/null

    expected="$EXPECTED_LOGS/$sbase.log"
    actual="$SCRATCH_DIR/$sbase.actual.log"
    mv vv8-*-vv8-shell-*.0.log "$actual"

    python3 "$TOOLS/relabel.py" <"$actual" >"$SCRATCH_DIR/filtered_actual.log"
    python3 "$TOOLS/relabel.py" <"$expected" >"$SCRATCH_DIR/filtered_expected.log"
    if DIFFS=$(diff -u "$SCRATCH_DIR/filtered_actual.log" "$SCRATCH_DIR/filtered_expected.log"); then
        echo "OK"
    else
        echo "FAIL"
        echo "-----------------------"
        echo "$DIFFS"
        echo "-----------------------"
        exitstatus=1
    fi
done

if [ $exitstatus -eq 0 ]; then
    echo "=========================================="
    echo "SUCCESS: ALL 10 TESTS PASSED WITH 0 DIFFS!"
    echo "=========================================="
else
    echo "=========================================="
    echo "FAILURE: ONE OR MORE TESTS FAILED!"
    echo "=========================================="
    exit $exitstatus
fi
