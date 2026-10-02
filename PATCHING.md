# VisibleV8 Porting & Patching Walk-Through Guide

This guide details the end-to-end process for updating VisibleV8 (VV8) patchsets to support new versions of Chromium and V8. It uses the transition from **Chrome 147** to **Chromium 155.0.8059.30** as a concrete reference walkthrough.

---

## 1. Overview & Architecture

VisibleV8 instruments the V8 JavaScript engine and Chromium content renderer to capture fine-grained execution traces (API calls, property accesses, property assignments, script loads, and security origin changes).

The repository maintains versioned patches under `patches/<20-char-commit-hash>/`:
- **`version.txt`**: Records the target Chrome version and full 40-character Chromium git commit SHA.
- **`chrome-sandbox.diff`**: Applied to the Chromium source tree (`src/`). Disables renderer process sandboxing and instruments Android Gin Java bridge bindings.
- **`trace-apis.diff`**: Applied to the V8 source tree (`src/v8/`). Implements bytecode generation hooks, builtin call interception, safe property inspection, and thread-local trace logging.

### Patch Directory Naming Convention
VisibleV8 names each version directory in `patches/` using the **first 20 characters of the Chromium release tag commit hash**.

For **Chromium 155.0.8059.30**:
- **Chromium Commit**: `a17dbb3e325efe798bb372f32370ee7f67093bc5`
- **V8 Commit**: `82b65fdd7b5847a41e76c9eeb04351ebec267785`
- **Target Directory**: `patches/a17dbb3e325efe798bb3/`

---

## 2. Anatomy of the Patches

### A. Chromium Root Patches (`chrome-sandbox.diff`)

| Target File | Purpose in VisibleV8 |
|---|---|
| `content/renderer/renderer_main.cc` | Sets `need_sandbox = false;` to allow renderer processes to create and write trace log files to disk without sandbox violations. |
| `base/android/java/src/org/chromium/base/process_launcher/BindService.java` | Disables Android renderer isolation in `supportVariableConnections()`. |
| `chrome/android/java/AndroidManifest.xml` | Configures `isolatedProcess="false"` and `externalService="false"` for sandboxed process services. |
| `content/renderer/java/gin_java_function_invocation_helper.cc` | Intercepts Java method/property invocations crossing the WebView Gin bridge and passes arguments to `v8::visv8_log_java_api_call`. |
| `third_party/blink/renderer/platform/bindings/v8_binding.h` | Includes public VisibleV8 header `v8/include/v8-visiblev8.h`. |

### B. V8 Patches (`trace-apis.diff`)

| Subsystem / File | Purpose in VisibleV8 |
|---|---|
| **Build Config** (`BUILD.gn`, `BUILD.bazel`) | Adds `src/runtime/runtime-utils.cc` to `v8_base_without_compiler`, disables lazy source positions (`v8_enable_lazy_source_positions = false`), and defines `VV8_TRACE_PROPERTIES`. |
| **Public API** (`include/v8-visiblev8.h`, `src/api/api.cc`) | Exports C++ logging APIs (`visv8_log_java_api_call`, `visv8_log_java_prop_get`, `visv8_log_java_prop_set`) and handles conversions between public `v8::Local` handles and internal `DirectHandle` / `Tagged` pointers. |
| **Initialization** (`src/init/v8.cc`) | Calls `visv8_tls_init()` during `V8::Initialize()` to allocate thread-local storage slots. |
| **Bytecode Generator** (`src/interpreter/bytecode-generator.cc`) | Injects runtime tracing calls during AST traversal: `Runtime::kTracePropertyLoad` for named/keyed reads, `Runtime::kTracePropertyStore` for assignments and count operations (`++`/`--`), and `Runtime::kTraceFunctionCall` for calls. |
| **Builtin Hooks** (`src/builtins/builtins-call-gen.cc`, `builtins-api.cc`, `builtins-function.cc`, `builtins-global.cc`, `builtins-reflect.cc`, `reflect.tq`) | Hooks `HandleApiCallOrConstruct`, `HandleApiConstruct`, `CreateDynamicFunction`, `GlobalEval`, and `Reflect.get`/`Reflect.set`. |
| **JIT Optimization Bypass** (`src/compiler/js-call-reducer.cc`) | Short-circuits `JSCallReducer::ReduceCallApiFunction` by returning `NoChange()`. This prevents TurboFan from inlining API callbacks, ensuring all calls pass through the instrumented builtin trampoline. |
| **Safe Property Access** (`src/objects/objects.cc`, `objects.h`, `objects-inl.h`) | Implements `Object::VV8GetPropertyNoSideEffects` to inspect object properties during trace formatting without triggering JavaScript getters or proxy traps. |
| **Logging Runtime** (`src/runtime/runtime-utils.cc`, `runtime-utils.h`, `runtime.cc`, `runtime.h`, `runtime-test.cc`) | Implements the thread-local logger (`VisV8TlsData`, `VisV8Logger`, `VisV8Context`), fast stringification (`visv8_to_string`), script origin tracking (`@`), script source genealogy (`$`), and log rotation at 1GB file boundaries. |

---

## 3. Breaking Changes & Churn to Expect (Chrome 147 → 155)

When jumping across 8 major versions, automated patch application will encounter conflicts. Focus on the following areas:

### 1. `src/interpreter/bytecode-generator.cc`
- Line numbers shift heavily as new JavaScript language proposals, bytecode optimizations, and AST node types are added upstream.
- Verify evaluation order in `VisitPropertyLoad(Register obj, Property* property)`:
  - In VisibleV8, keyed property lookups evaluate the key into a temporary register (`key_reg`) to trace `(call-site, this, key)` before loading into the accumulator.
- Ensure temporary registers allocated via `register_allocator()->NewRegisterList(...)` do not conflict with upstream changes to register allocation.

### 2. V8 Handle Migration (`DirectHandle`, `Handle`, `Tagged`)
- V8 has been actively converting methods from `Handle<T>` to `DirectHandle<T>` for stack-allocated references that do not escape across GC safepoints.
- Ensure calls in `src/runtime/runtime-utils.cc` and `src/objects/objects.cc` use the exact handle types expected by the target V8 version.
- In Chrome 147, `contents->length()` changed to `(contents->length()).value()` because the length became a `SafeHeapObjectSize`. Always inspect the return type of length and size getters.

### 3. `LookupIterator` Exhaustiveness in `Object::VV8GetPropertyNoSideEffects`
- In `src/objects/objects.cc`, `VV8GetPropertyNoSideEffects` switches over `LookupIterator::state()`.
- Chrome 147 introduced `LookupIterator::MODULE_NAMESPACE`.
- If upstream introduces any new states in `src/objects/lookup.h`, the compiler will fail with `-Werror=switch` unless all enum variants are explicitly handled.

### 4. Compiler Optimization Pipelines (TurboFan, Turboshaft, Maglev)
- Check whether API call lowering or fast API calls have moved to Turboshaft or Maglev.
- If Maglev or Turboshaft inlines API calls directly into machine code, ensure the reducer in those tiers is also disabled or properly stubbed so calls do not bypass logging.

---

## 5. Step-by-Step Patching Walk-Through

### Prerequisites
- Linux host or Docker (AMD64 / x86_64).
- 100+ GB free disk space.
- Multi-core CPU (16–32+ cores recommended).

### Step 1: Look Up Upstream Commit Hashes
Use the Chromium Dash API to fetch release metadata:
```bash
curl -s "https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Android&num=1&offset=0" | jq .
```
Identify:
- `version`: `155.0.8059.30`
- `hashes.chromium`: `a17dbb3e325efe798bb372f32370ee7f67093bc5`
- `hashes.v8`: `82b65fdd7b5847a41e76c9eeb04351ebec267785`

### Step 2: Launch the Builder Container
From the VisibleV8 repository root:
```bash
cd builder
# Build the builder image
docker build --platform linux/amd64 -t build-direct -f build-direct.dockerfile .

# Launch interactive shell
docker run --platform linux/amd64 -it \
  -v $(pwd)/artifacts:/artifacts \
  -v $(pwd)/build:/build \
  -v $(dirname `pwd`):/build/visiblev8 \
  --entrypoint /bin/bash build-direct
```

### Step 3: Check Out Target Chromium Source
Inside the build container:
```bash
VERSION="155.0.8059.30"
WD="/build/$VERSION"
mkdir -p "$WD" && cd "$WD"

# Clone depot_tools if needed
[ ! -d /tmp/depot_tools ] && git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git /tmp/depot_tools
export PATH="$PATH:/tmp/depot_tools"

# Clone Chromium src at target release tag
[ ! -d "$WD/src" ] && git clone --depth 4 --branch "$VERSION" https://chromium.googlesource.com/chromium/src "$WD/src"

cd "$WD/src"
# Sync dependencies
gclient sync -D --force --reset --with_branch_heads
```

### Step 4: Apply Baseline Patches & Resolve Rejects
Baseline patches from Chrome 147:
- Chromium sandbox: `/build/visiblev8/patches/5a40bc538bcbf1b9f4010/chrome-sandbox.diff`
- V8 engine: `/build/visiblev8/patches/5a40bc538bcbf1b9f4010/trace-apis.diff`

#### 4.1 Apply Sandbox Patch (Chromium root `src/`)
```bash
cd "$WD/src"
git apply --reject --whitespace=fix /build/visiblev8/patches/5a40bc538bcbf1b9f4010/chrome-sandbox.diff
```
If `.rej` files are created:
1. Open the target file alongside the `.rej` file.
2. Locate the modified block (e.g., `content/renderer/renderer_main.cc` where `need_sandbox` is set).
3. Apply the edit manually and delete the `.rej` file.

#### 4.2 Apply V8 Patch (`src/v8/`)
```bash
cd "$WD/src/v8"
git apply --reject --whitespace=fix /build/visiblev8/patches/5a40bc538bcbf1b9f4010/trace-apis.diff
```
Inspect any rejected hunks:
```bash
find . -name "*.rej"
```
Common files needing manual resolution:
- **`src/interpreter/bytecode-generator.cc`**: Match the methods `VisitPropertyLoad`, `VisitAssignment`, `VisitCompoundAssignment`, `VisitCountOperation`, and `VisitCall` to their updated line locations in 155.
- **`src/builtins/builtins-call-gen.cc`**: Ensure CodeStubAssembler argument extraction in `HandleApiCallOrConstruct` matches current 155 conventions.
- **`src/objects/objects.cc`**: Ensure `VV8GetPropertyNoSideEffects` has a case for all `LookupIterator::State` values.

### Step 5: Test Compile V8 and Chromium Targets
Generate GN release args:
```bash
cd "$WD/src"
mkdir -p out/Release

cat > out/Release/args.gn << 'EOF'
dcheck_always_on=false
is_debug=false
disable_fieldtrial_testing_config=true
is_official_build=true
enable_linux_installer=true
is_component_build=false
use_thin_lto=false
is_cfi=false
chrome_pgo_phase=0
v8_use_external_startup_data=true
EOF

gn gen out/Release

# Build V8 shell first for rapid syntax & linking verification
autoninja -C out/Release v8_shell

# Build browser and unit tests
autoninja -C out/Release chrome d8 v8_unittests
```

Fix any compilation errors under `-Werror` (e.g., handle types, missing includes, or unhandled enum switches).

### Step 6: Create the Version Snapshot
Once the build compiles cleanly:

```bash
# Export the clean diffs
cd "$WD/src/v8"
git diff > /tmp/trace-apis.diff

cd "$WD/src"
# Exclude v8 submodule from the Chromium diff
git diff ':!v8' > /tmp/chrome-sandbox.diff

# Create snapshot directory in visiblev8 repository
COMMIT_PREFIX="a17dbb3e325efe798bb3"
PATCH_DIR="/build/visiblev8/patches/$COMMIT_PREFIX"
mkdir -p "$PATCH_DIR"

cp /tmp/chrome-sandbox.diff "$PATCH_DIR/chrome-sandbox.diff"
cp /tmp/trace-apis.diff "$PATCH_DIR/trace-apis.diff"

cat > "$PATCH_DIR/version.txt" << 'EOF'
Chrome 155.0.8059.30
Commit a17dbb3e325efe798bb372f32370ee7f67093bc5
EOF

# Update development head diff
cp /tmp/trace-apis.diff /build/visiblev8/patches/trace-apis.diff
```

### Step 7: Run Regression Tests
Verify that the output format adheres to the VisibleV8 trace specifications:
```bash
cd /build/visiblev8/builder
# Test against the newly built container
../tests/run.sh -x <docker-image-name> trace-apis-obj
```

Verify that the generated logs produce:
- `c<call_site>:<target>:<receiver>:<args...>` for API function calls.
- `g<call_site>:<receiver>:<property>` for property gets.
- `s<call_site>:<receiver>:<property>:<value>` for property sets.
- `$<script_id>:<parent_id>:<name>:<source>` for script genealogy.
- `@<url>:<security_token>` for context origin transitions.

---

## 6. Build Automation & Release Verification

VisibleV8's automated build script (`builder/build-direct.sh`) automatically locates the new patchset using:
```bash
grep Chrome $VV8/patches/*/version.txt | grep 155.0.8059.30
```
When this matches, `build-direct.sh` picks up `patches/a17dbb3e325efe798bb3/` as the active patchset.

You can trigger a full artifact build via:
```bash
cd builder
make build VERSION=155.0.8059.30 ANDROID=1 ARM=1 WEBVIEW=1 IDLDATA=1
```
The resulting Debian packages (`.deb`) and Android APKs (`SystemWebView.apk`, `Chrome.apk`) will be placed into `builder/artifacts/155.0.8059.30/`.
