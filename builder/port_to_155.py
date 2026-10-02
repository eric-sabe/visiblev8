#!/usr/bin/env python3
import os
import sys

def patch_v8(v8_dir):
    print("Patching V8 in", v8_dir)
    
    # 1. BUILD.bazel
    bazel_path = os.path.join(v8_dir, "BUILD.bazel")
    with open(bazel_path, "r") as f:
        content = f.read()
    if '"src/runtime/runtime-utils.cc",' not in content:
        content = content.replace(
            '"src/runtime/runtime-utils.h",',
            '"src/runtime/runtime-utils.cc",\n        "src/runtime/runtime-utils.h",'
        )
        with open(bazel_path, "w") as f:
            f.write(content)
        print("  Patched BUILD.bazel")

    # 2. BUILD.gn
    gn_path = os.path.join(v8_dir, "BUILD.gn")
    with open(gn_path, "r") as f:
        content = f.read()
    if "v8_enable_lazy_source_positions = false" not in content:
        content = content.replace(
            "v8_enable_lazy_source_positions = true",
            "v8_enable_lazy_source_positions = false"
        )
    if "vv8_trace_properties = true" not in content:
        content = content.replace(
            'v8_jitless = v8_enable_lite_mode',
            'v8_jitless = v8_enable_lite_mode\n\n  # VisibleV8: sets VV8_TRACE_PROPERTIES\n  vv8_trace_properties = true'
        )
    if 'defines += [ "VV8_TRACE_PROPERTIES" ]' not in content:
        content = content.replace(
            'defines = enabled_external_cppgc_defines\n  }',
            'defines = enabled_external_cppgc_defines\n  }\n\n  # VisibleV8: create define\n  if (vv8_trace_properties) {\n    defines += [ "VV8_TRACE_PROPERTIES" ]\n  }'
        )
    if '"src/runtime/runtime-utils.cc",' not in content:
        content = content.replace(
            '"src/runtime/runtime-trace.cc",',
            '"src/runtime/runtime-trace.cc",\n    "src/runtime/runtime-utils.cc",'
        )
    with open(gn_path, "w") as f:
        f.write(content)
    print("  Patched BUILD.gn")

    # 3. src/init/v8.cc
    v8_cc = os.path.join(v8_dir, "src/init/v8.cc")
    with open(v8_cc, "r") as f:
        content = f.read()
    if "visv8_tls_init" not in content:
        target = "AdvanceStartupState(V8StartupState::kV8Initialized);"
        replacement = target + "\n  extern void visv8_tls_init();\n  visv8_tls_init();"
        content = content.replace(target, replacement, 1)
        with open(v8_cc, "w") as f:
            f.write(content)
        print("  Patched src/init/v8.cc")

    # 4. src/ic/accessor-assembler.cc
    acc_cc = os.path.join(v8_dir, "src/ic/accessor-assembler.cc")
    with open(acc_cc, "r") as f:
        content = f.read()
    if "Runtime::kVV8TraceKeyedHasIC" not in content:
        target = "void AccessorAssembler::GenerateKeyedHasIC() {"
        replacement = target + "\n  auto vector = Parameter<HeapObject>(Descriptor::kVector);\n  auto context = Parameter<Context>(Descriptor::kContext);\n\n  CallRuntime(Runtime::kVV8TraceKeyedHasIC, context, receiver, name);\n"
        # We need to see what GenerateKeyedHasIC starts with
        if "CallRuntime(Runtime::kVV8TraceKeyedHasIC" not in content:
            pos = content.find("void AccessorAssembler::GenerateKeyedHasIC() {")
            if pos != -1:
                end_brace = content.find("\n", pos)
                # insert after opening line
                call = "\n  auto context_param = Parameter<Context>(Descriptor::kContext);\n  CallRuntime(Runtime::kVV8TraceKeyedHasIC, context_param, receiver, name);\n"
                # check existing parameters
                content = content[:end_brace] + call + content[end_brace:]
                with open(acc_cc, "w") as f:
                    f.write(content)
                print("  Patched src/ic/accessor-assembler.cc")

    # 5. src/builtins/builtins-reflect.cc
    ref_cc = os.path.join(v8_dir, "src/builtins/builtins-reflect.cc")
    with open(ref_cc, "r") as f:
        content = f.read()
    if "visv8_log_property_set" not in content:
        target = "ASSIGN_RETURN_FAILURE_ON_EXCEPTION(isolate, name,\n                                     Object::ToName(isolate, key));"
        hook = """\n
#ifdef VV8_TRACE_PROPERTIES
  // VisibleV8: log reflected property sets
  extern void visv8_log_property_set(Isolate*, int, Tagged<Object>,
                                     Tagged<Object>, Tagged<Object>);
  visv8_log_property_set(isolate, -1, *target, *key, *value);
#endif\n"""
        content = content.replace(target, target + hook, 1)
        with open(ref_cc, "w") as f:
            f.write(content)
        print("  Patched src/builtins/builtins-reflect.cc")

    # 6. src/builtins/reflect.tq
    ref_tq = os.path.join(v8_dir, "src/builtins/reflect.tq")
    with open(ref_tq, "r") as f:
        content = f.read()
    if "TracePropertyLoad" not in content:
        decl = "// VisibleV8: defining external trace-property-load runtime function\nextern transitioning runtime TracePropertyLoad(implicit context: Context)(Smi, JSAny, JSAny): void;\n\n"
        target_fn = "transitioning javascript builtin ReflectGet("
        content = content.replace(target_fn, decl + target_fn, 1)
        
        hook = "\n    // VisibleV8: call-out to property-load tracer runtime function\n    TracePropertyLoad(-1, object, propertyKey);\n"
        target_ret = "  return GetPropertyWithReceiver("
        content = content.replace(target_ret, hook + target_ret, 1)
        with open(ref_tq, "w") as f:
            f.write(content)
        print("  Patched src/builtins/reflect.tq")

    # 7. src/builtins/builtins-global.cc
    glob_cc = os.path.join(v8_dir, "src/builtins/builtins-global.cc")
    with open(glob_cc, "r") as f:
        content = f.read()
    if "visv8_log_api_call" not in content:
        decl = "\n// VisibleV8\nextern void visv8_log_api_call(Isolate*, bool, Tagged<HeapObject>,\n                               Tagged<Object>, Address*, int);\n// VisibleV8\n"
        content = content.replace("namespace internal {", "namespace internal {" + decl, 1)
        
        target = "DirectHandle<JSObject> target_global_proxy(target->global_proxy(), isolate);"
        hook = """\n  // VisibleV8
  v8::internal::visv8_log_api_call(isolate, false, *target, *args.receiver(),
                                   args.address_of_first_argument(),
                                   args.length() - 1);
  // VisibleV8"""
        content = content.replace(target, target + hook, 1)
        with open(glob_cc, "w") as f:
            f.write(content)
        print("  Patched src/builtins/builtins-global.cc")

    # 8. src/builtins/builtins-function.cc
    func_cc = os.path.join(v8_dir, "src/builtins/builtins-function.cc")
    with open(func_cc, "r") as f:
        content = f.read()
    if "visv8_log_api_call" not in content:
        decl = "\n// VisibleV8\nextern void visv8_log_api_call(Isolate*, bool, Tagged<HeapObject>,\n                               Tagged<Object>, Address*, int);\n// VisibleV8\n"
        content = content.replace("namespace internal {", "namespace internal {" + decl, 1)
        
        target = "int const argc = args.length() - 1;"
        hook = """\n
  // VisibleV8
  // passing undefined into the reciever since no reciever exists
  visv8_log_api_call(isolate, false, *args.target(),
                     ReadOnlyRoots(isolate).undefined_value(),
                     args.address_of_first_argument(), argc);
  // VisibleV8"""
        content = content.replace(target, target + hook, 1)
        with open(func_cc, "w") as f:
            f.write(content)
        print("  Patched src/builtins/builtins-function.cc")

    # 9. src/builtins/builtins-api.cc
    api_cc = os.path.join(v8_dir, "src/builtins/builtins-api.cc")
    with open(api_cc, "r") as f:
        content = f.read()
    if "visv8_log_api_call" not in content:
        decl = "\n// VisibleV8\nextern void visv8_log_api_call(Isolate*, bool, Tagged<HeapObject>,\n                               Tagged<Object>, Address*, int);\n"
        content = content.replace("namespace internal {", "namespace internal {" + decl, 1)
        
        target = "DirectHandle<FunctionTemplateInfo> fun_data(\n      args.target()->shared()->api_func_data(), isolate);"
        hook = """\n
  // VisibleV8
  Handle<HeapObject> function = args.target();
  v8::internal::visv8_log_api_call(
      isolate, true, *function, *receiver,
      args.address_of_first_argument(),
      args.argc_without_receiver());"""
        content = content.replace(target, target + hook, 1)
        with open(api_cc, "w") as f:
            f.write(content)
        print("  Patched src/builtins/builtins-api.cc")

    # 10. src/builtins/builtins-call-gen.cc
    call_cc = os.path.join(v8_dir, "src/builtins/builtins-call-gen.cc")
    with open(call_cc, "r") as f:
        content = f.read()
    if "Runtime::kVV8TraceFunctionCall" not in content:
        pos = content.find("TF_BUILTIN(HandleApiCallOrConstruct, CallOrConstructBuiltinsAssembler) {")
        if pos != -1:
            target = "auto dispatch_handle = InvalidDispatchHandleConstant();\n#endif"
            hook = """
  CodeStubArguments args(this, argc);
  auto args_ptr = args.AtIndexPtr(IntPtrConstant(0));

  // This splits the pointer in 16-bit Smi chunks, and passes the resulting
  // array to the runtime
  TNode<Smi> chunks[4];
  for (int i = 0; i < 4; ++i) {
    chunks[i] = SmiFromUint32(ReinterpretCast<Uint32T>(Word32And(
        TruncateIntPtrToInt32(ReinterpretCast<IntPtrT>(args_ptr)), 0xFFFF)));
    args_ptr = ReinterpretCast<RawPtrT>(WordShr(args_ptr, IntPtrConstant(16)));
  }"""
            content = content.replace(target, target + hook, 1)
            
            target2 = "CAST(LoadSharedFunctionInfoUntrustedFunctionData(shared));"
            hook2 = """\n
    CallRuntime(Runtime::kVV8TraceFunctionCall, context, target,
                SmiFromInt32(argc), chunks[3], chunks[2], chunks[1], chunks[0]);"""
            content = content.replace(target2, target2 + hook2, 1)
            with open(call_cc, "w") as f:
                f.write(content)
            print("  Patched src/builtins/builtins-call-gen.cc")

    # 11. src/compiler/js-call-reducer.cc
    red_cc = os.path.join(v8_dir, "src/compiler/js-call-reducer.cc")
    with open(red_cc, "r") as f:
        content = f.read()
    start_sig = "Reduction JSCallReducer::ReduceCallApiFunction(Node* node,\n                                               SharedFunctionInfoRef shared) {"
    if start_sig in content and "// VisibleV8" not in content[content.find(start_sig):content.find(start_sig)+200]:
        pos = content.find(start_sig)
        end_brace = content.find("\n}\n", pos)
        new_fn = start_sig + "\n  // VisibleV8\n  return NoChange();\n}"
        content = content[:pos] + new_fn + content[end_brace+2:]
        with open(red_cc, "w") as f:
            f.write(content)
        print("  Patched src/compiler/js-call-reducer.cc")

    # 12. src/runtime/runtime.h
    rt_h = os.path.join(v8_dir, "src/runtime/runtime.h")
    with open(rt_h, "r") as f:
        content = f.read()
    if "VV8TraceFunctionCall" not in content:
        content = content.replace(
            "  F(DebugPrintWord, 5, 1)                                                \\",
            "  F(DebugPrintWord, 5, 1)                                                \\\n  F(VV8TraceFunctionCall, -1, 1)                                         \\\n  F(VV8TraceKeyedHasIC, -1, 1)                                           \\"
        )
        content = content.replace(
            "  F(TraceExit, 1, 1)                                                     \\",
            "  F(TraceExit, 1, 1)                                                     \\\n  F(TraceFunctionCall, 0, 1)                                             \\\n  F(TracePropertyLoad, 3, 1)                                             \\\n  F(TracePropertyStore, 4, 1)                                            \\"
        )
        decl = """
V8_EXPORT extern void ext_visv8_log_java_api_call(
    Isolate* isolate, bool is_constructor, Tagged<String> local_func,
    Tagged<Object> local_receiver, Tagged<Object> local_result,
    std::vector<v8::internal::Tagged<v8::internal::Object>>* argv, int argc);

V8_EXPORT extern void ext_visv8_log_java_prop_set(Isolate* isolate,
                                                  int call_site,
                                                  Tagged<Object> local_obj,
                                                  Tagged<Object> local_prop,
                                                  Tagged<Object> local_value);

V8_EXPORT extern void ext_visv8_log_java_prop_get(Isolate* isolate,
                                                  int call_site,
                                                  Tagged<Object> local_obj,
                                                  Tagged<Object> local_prop,
                                                  Tagged<Object> local_value);

}  // namespace internal
}  // namespace v8"""
        content = content.replace("}  // namespace internal\n}  // namespace v8", decl, 1)
        with open(rt_h, "w") as f:
            f.write(content)
        print("  Patched src/runtime/runtime.h")

    # 13. src/runtime/runtime.cc
    rt_cc = os.path.join(v8_dir, "src/runtime/runtime.cc")
    with open(rt_cc, "r") as f:
        content = f.read()
    if "ext_visv8_log_java_api_call" not in content:
        impl = """
void ext_visv8_log_java_api_call(Isolate* isolate, bool is_constructor,
                                 Tagged<String> local_func,
                                 Tagged<Object> local_receiver,
                                 Tagged<Object> local_result,
                                 std::vector<Tagged<Object>>* argv, int argc) {
  visv8_log_java_api_call(isolate, is_constructor, local_func, local_receiver,
                          local_result, argv, argc);
}

void ext_visv8_log_java_prop_set(Isolate* isolate, int call_site,
                                 Tagged<Object> local_obj,
                                 Tagged<Object> local_prop,
                                 Tagged<Object> local_value) {
  visv8_log_java_prop_set(isolate, call_site, local_obj, local_prop,
                          local_value);
}

void ext_visv8_log_java_prop_get(Isolate* isolate, int call_site,
                                 Tagged<Object> local_obj,
                                 Tagged<Object> local_prop,
                                 Tagged<Object> local_value) {
  visv8_log_java_prop_get(isolate, call_site, local_obj, local_prop,
                          local_value);
}

}  // namespace internal
}  // namespace v8"""
        content = content.replace("}  // namespace internal\n}  // namespace v8", impl, 1)
        with open(rt_cc, "w") as f:
            f.write(content)
        print("  Patched src/runtime/runtime.cc")

    # 14. src/runtime/runtime-utils.h
    rtu_h = os.path.join(v8_dir, "src/runtime/runtime-utils.h")
    with open(rtu_h, "r") as f:
        content = f.read()
    if "visv8_log_property_get" not in content:
        includes = """#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <strstream>
#include <vector>
#include "build/build_config.h"
#include "include/v8-function.h"
#include "include/v8-profiler.h"
#include "src/api/api-inl.h"
#include "src/base/macros.h"
#include "src/base/numbers/double.h"
#include "src/builtins/builtins-utils.h"
#include "src/codegen/compiler.h"
#include "src/codegen/pending-optimization-table.h"
#include "src/compiler-dispatcher/lazy-compile-dispatcher.h"
#include "src/compiler-dispatcher/optimizing-compile-dispatcher.h"
#include "src/debug/debug-evaluate.h"
#include "src/deoptimizer/deoptimizer.h"
#include "src/execution/arguments-inl.h"
#include "src/execution/frames-inl.h"
#include "src/execution/frames.h"
#include "src/execution/isolate-inl.h"
#include "src/execution/protectors-inl.h"
#include "src/execution/tiering-manager.h"
#include "src/flags/flags.h"
#include "src/handles/handles.h"
#include "src/heap/heap-layout-inl.h"
#include "src/heap/heap-write-barrier-inl.h"
#include "src/heap/pretenuring-handler-inl.h"
#include "src/ic/stub-cache.h"
#include "src/objects/bytecode-array.h"
#include "src/objects/js-collection-inl.h"
#include "src/objects/objects.h"
#include "src/profiler/heap-profiler.h"
#include "src/utils/utils.h"
#ifdef V8_ENABLE_MAGLEV
#include "src/maglev/maglev-concurrent-dispatcher.h"
#endif
#include "src/objects/js-atomics-synchronization-inl.h"
#include "src/objects/js-function-inl.h"
#include "src/objects/js-regexp-inl.h"
#include "src/objects/keys.h"
#include "src/objects/smi.h"
#include "src/profiler/heap-snapshot-generator.h"
#include "src/regexp/regexp.h"
#include "src/snapshot/snapshot.h"
#include "v8-local-handle.h"
#include "v8-primitive.h"
#include "v8config.h"
#if BUILDFLAG(IS_ANDROID)
#include <sys/prctl.h>
#endif
#ifdef V8_ENABLE_MAGLEV
#include "src/maglev/maglev.h"
#endif
#if V8_ENABLE_WEBASSEMBLY
#include "src/wasm/wasm-engine.h"
#endif

"""
        content = content.replace('#include "src/objects/objects.h"', includes + '#include "src/objects/objects.h"', 1)
        decls = """
void visv8_log_property_get(Isolate* isolate, int call_site, Tagged<Object> obj,
                            Tagged<Object> prop);

void visv8_log_api_call(Isolate* isolate, bool is_constructor,
                        Tagged<HeapObject> func, Tagged<Object> receiver,
                        Address* argv, int argc);

void visv8_log_property_set(Isolate* isolate, int call_site, Tagged<Object> obj,
                            Tagged<Object> prop, Tagged<Object> value);

void visv8_log_java_api_call(Isolate* isolate, bool is_constructor,
                             Tagged<String> local_func,
                             Tagged<Object> local_receiver,
                             Tagged<Object> local_result,
                             std::vector<Tagged<Object>>* argv, int argc);

void visv8_log_java_prop_set(Isolate* isolate, int call_site,
                             Tagged<Object> local_obj,
                             Tagged<Object> local_prop,
                             Tagged<Object> local_value);

void visv8_log_java_prop_get(Isolate* isolate, int call_site,
                             Tagged<Object> local_obj,
                             Tagged<Object> local_prop,
                             Tagged<Object> local_value);

}  // namespace internal
}  // namespace v8"""
        content = content.replace("}  // namespace internal\n}  // namespace v8", decls, 1)
        with open(rtu_h, "w") as f:
            f.write(content)
        print("  Patched src/runtime/runtime-utils.h")

    # 15. src/runtime/runtime-compiler.cc
    rtc_cc = os.path.join(v8_dir, "src/runtime/runtime-compiler.cc")
    with open(rtc_cc, "r") as f:
        content = f.read()
    if "visv8_log_api_call" not in content:
        decl = "\n// VisibleV8\nextern void visv8_log_api_call(Isolate*, bool, Tagged<HeapObject>,\n                               Tagged<Object>, Address*, int);\n// VisibleV8\n"
        content = content.replace("namespace v8::internal {", "namespace v8::internal {" + decl, 1)
        target = "  if (*callee != isolate->native_context()->global_eval_fun()) {\n    return *callee;\n  }"
        hook = """\n\n  // VisibleV8
  // passing undefined into the reciever since no reciever exists
  visv8_log_api_call(isolate, false, *args.at<HeapObject>(0),
                     ReadOnlyRoots(isolate).undefined_value(),
                     args.address_of_arg_at(1), 1);
  // VisibleV8"""
        content = content.replace(target, target + hook, 1)
        with open(rtc_cc, "w") as f:
            f.write(content)
        print("  Patched src/runtime/runtime-compiler.cc")

    # 16. src/runtime/runtime-test.cc
    rtt_cc = os.path.join(v8_dir, "src/runtime/runtime-test.cc")
    with open(rtt_cc, "r") as f:
        content = f.read()
    if "Runtime_TracePropertyLoad" not in content:
        top_inc = """#include "src/runtime/runtime.h"

#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <strstream>
#include <vector>
#include "build/build_config.h"
#include "src/builtins/builtins-utils.h"
#include "src/objects/keys.h"
#include "src/runtime/runtime-utils.h"
#include "v8-local-handle.h"
#include "v8-primitive.h"
#include "v8config.h"
#if BUILDFLAG(IS_ANDROID)
#include <sys/prctl.h>
#endif
"""
        content = content.replace('#include "src/runtime/runtime.h"\n', top_inc, 1)
        target = "RUNTIME_FUNCTION(Runtime_HaveSameMap) {"
        hook = """RUNTIME_FUNCTION(Runtime_TracePropertyLoad) {
  HandleScope hs(isolate);
  DCHECK_EQ(3, args.length());

  Tagged<Object> call_site = args[0];
  Tagged<Object> obj = args[1];
  Tagged<Object> prop = args[2];

  v8::internal::visv8_log_property_get(isolate, Smi::ToInt(call_site), obj,
                                       prop);

  return ReadOnlyRoots(isolate).undefined_value();
}

RUNTIME_FUNCTION(Runtime_TracePropertyStore) {
  HandleScope hs(isolate);

  Tagged<Object> call_site = args[0];
  Tagged<Object> obj = args[1];
  Tagged<Object> prop = args[2];
  Tagged<Object> value = args[3];

  v8::internal::visv8_log_property_set(isolate, Smi::ToInt(call_site), obj,
                                       prop, value);

  return ReadOnlyRoots(isolate).undefined_value();
}

// Hack to log almost all scripts that have any kind of function call
RUNTIME_FUNCTION(Runtime_TraceFunctionCall) {
  return ReadOnlyRoots(isolate).undefined_value();
}

RUNTIME_FUNCTION(Runtime_VV8TraceKeyedHasIC) {
  HandleScope shs(isolate);
  Tagged<Object> obj = Cast<Object>(args[0]);
  Tagged<Object> prop = Cast<Object>(args[1]);

  v8::internal::visv8_log_property_get(isolate, -1, obj, prop);
  return ReadOnlyRoots(isolate).undefined_value();
}

RUNTIME_FUNCTION(Runtime_VV8TraceFunctionCall) {
  HandleScope shs(isolate);
  Tagged<JSFunction> target = Cast<JSFunction>(args[0]);
  Tagged<Smi> argc = Cast<Smi>(args[1]);

  Address argv_ptr_val = 0;
  for (int i = 2; i < 2 + 4; ++i) {
    argv_ptr_val <<= 16;
    CHECK(IsSmi(args[i]));
    uint32_t chunk = Cast<Smi>(args[i]).value();
    CHECK_EQ(chunk & 0xFFFF0000, 0);
    argv_ptr_val |= chunk;
  }

  int argc_integer = Smi::ToInt(argc) - 1;
  Tagged<JSReceiver> reciever =
      (Tagged<JSReceiver>)((Tagged<JSReceiver>*)argv_ptr_val)[-1];

  v8::internal::visv8_log_api_call(isolate, false, target, reciever,
                                   (Address*)argv_ptr_val,
                                   argc_integer >= 0 ? argc_integer : 0);
  return ReadOnlyRoots(isolate).undefined_value();
}

//------------------------------
// END VisibleV8

RUNTIME_FUNCTION(Runtime_HaveSameMap) {"""
        content = content.replace(target, hook, 1)
        with open(rtt_cc, "w") as f:
            f.write(content)
        print("  Patched src/runtime/runtime-test.cc")

    # 17. src/api/api.cc
    api_impl = os.path.join(v8_dir, "src/api/api.cc")
    with open(api_impl, "r") as f:
        content = f.read()
    if "visv8_log_java_api_call" not in content:
        funcs = """
v8::internal::Isolate* ConvertToInternalIsolate(v8::Isolate* public_isolate) {
  return reinterpret_cast<v8::internal::Isolate*>(public_isolate);
}

std::vector<v8::internal::Tagged<v8::internal::Object>>* ConvertArrayToTagged(
    const std::vector<v8::Local<v8::Value>>& argv, int argc) {
  auto* tagged_values =
      new std::vector<v8::internal::Tagged<v8::internal::Object>>();
  tagged_values->reserve(argc);

  for (const auto& local_value : argv) {
    internal::DirectHandle<internal::Object> val =
        Utils::OpenDirectHandle(*local_value);
    tagged_values->push_back(*val);
  }

  return tagged_values;
}

void visv8_log_java_api_call(Isolate* isolate, bool is_constructor,
                             v8::Local<String> local_func,
                             v8::Local<Object> local_receiver,
                             v8::Local<Value> local_result,
                             const std::vector<v8::Local<v8::Value>>& argv,
                             int argc) {
  v8::internal::Isolate* internal_isolate = ConvertToInternalIsolate(isolate);
  std::vector<v8::internal::Tagged<v8::internal::Object>>* args =
      ConvertArrayToTagged(argv, argc);
  internal::DirectHandle<v8::internal::String> func =
      Utils::OpenDirectHandle(*local_func);
  internal::DirectHandle<v8::internal::Object> receiver =
      Utils::OpenDirectHandle(*local_receiver);
  internal::DirectHandle<v8::internal::Object> result =
      Utils::OpenDirectHandle(*local_result);
  internal::ext_visv8_log_java_api_call(internal_isolate, is_constructor, *func,
                                        *receiver, *result, args, argc);
}

void visv8_log_java_prop_set(Isolate* isolate, int call_site,
                             v8::Local<v8::Object> local_obj,
                             v8::Local<v8::Object> local_prop,
                             v8::Local<v8::Object> local_value) {
  v8::internal::Isolate* internal_isolate = ConvertToInternalIsolate(isolate);
  internal::DirectHandle<v8::internal::Object> obj =
      Utils::OpenDirectHandle(*local_obj);
  internal::DirectHandle<v8::internal::Object> prop =
      Utils::OpenDirectHandle(*local_prop);
  internal::DirectHandle<v8::internal::Object> value =
      Utils::OpenDirectHandle(*local_value);
  internal::ext_visv8_log_java_prop_set(internal_isolate, call_site, *obj,
                                        *prop, *value);
}

void visv8_log_java_prop_get(Isolate* isolate, int call_site,
                             v8::Local<v8::Object> local_obj,
                             v8::Local<v8::Object> local_prop,
                             v8::Local<v8::Object> local_value) {
  v8::internal::Isolate* internal_isolate = ConvertToInternalIsolate(isolate);
  internal::DirectHandle<v8::internal::Object> obj =
      Utils::OpenDirectHandle(*local_obj);
  internal::DirectHandle<v8::internal::Object> prop =
      Utils::OpenDirectHandle(*local_prop);
  internal::DirectHandle<v8::internal::Object> value =
      Utils::OpenDirectHandle(*local_value);
  internal::ext_visv8_log_java_prop_get(internal_isolate, call_site, *obj,
                                        *prop, *value);
}

}  // namespace v8
"""
        content = content.replace("}  // namespace v8\n\n#ifdef ENABLE_SLOW_DCHECKS", funcs + "\n#ifdef ENABLE_SLOW_DCHECKS", 1)
        with open(api_impl, "w") as f:
            f.write(content)
        print("  Patched src/api/api.cc")

    # 18. src/objects/objects.h
    obj_h = os.path.join(v8_dir, "src/objects/objects.h")
    with open(obj_h, "r") as f:
        content = f.read()
    if "VV8GetPropertyNoSideEffects" not in content:
        target1 = "  V8_EXPORT_PRIVATE V8_WARN_UNUSED_RESULT static MaybeHandle<Object>\n  GetProperty(LookupIterator* it, bool is_global_reference = false);"
        hook1 = target1 + """\n
  // VisibleV8
  V8_EXPORT_PRIVATE V8_WARN_UNUSED_RESULT static MaybeHandle<Object>
  VV8GetPropertyNoSideEffects(LookupIterator* it,
                              bool is_global_reference = false);"""
        content = content.replace(target1, hook1, 1)
        
        target2 = "  V8_WARN_UNUSED_RESULT static inline MaybeHandle<Object> GetPropertyOrElement(\n      Isolate* isolate, DirectHandle<JSAny> object, DirectHandle<Name> name);"
        hook2 = """  // VisibleV8
  V8_WARN_UNUSED_RESULT static inline MaybeHandle<Object>
  VV8GetPropertyOrElementWithNoSideEffects(Isolate* isolate,
                                           DirectHandle<JSAny> object,
                                           DirectHandle<Name> name);
""" + target2
        content = content.replace(target2, hook2, 1)
        with open(obj_h, "w") as f:
            f.write(content)
        print("  Patched src/objects/objects.h")

    # 19. src/objects/lookup-inl.h (was objects-inl.h)
    lookup_inl = os.path.join(v8_dir, "src/objects/lookup-inl.h")
    with open(lookup_inl, "r") as f:
        content = f.read()
    if "VV8GetPropertyOrElementWithNoSideEffects" not in content:
        target = "MaybeHandle<Object> Object::GetPropertyOrElement(Isolate* isolate,\n                                                 DirectHandle<JSAny> object,\n                                                 DirectHandle<Name> name) {"
        hook = """// VisibleV8
MaybeHandle<Object> Object::VV8GetPropertyOrElementWithNoSideEffects(
    Isolate* isolate, DirectHandle<JSAny> object, DirectHandle<Name> name) {
  PropertyKey key(isolate, name);
  LookupIterator it(isolate, object, key);
  return VV8GetPropertyNoSideEffects(&it);
}

""" + target
        content = content.replace(target, hook, 1)
        with open(lookup_inl, "w") as f:
            f.write(content)
        print("  Patched src/objects/lookup-inl.h")

    # 20. src/objects/objects.cc
    obj_cc = os.path.join(v8_dir, "src/objects/objects.cc")
    with open(obj_cc, "r") as f:
        content = f.read()
    if "VV8GetPropertyNoSideEffects" not in content:
        target = "// static\nMaybeHandle<Object> Object::GetProperty(LookupIterator* it,\n                                        bool is_global_reference) {"
        hook = """// VisibleV8
// static
MaybeHandle<Object> Object::VV8GetPropertyNoSideEffects(
    LookupIterator* it, bool is_global_reference) {
  for (;; it->Next()) {
    switch (it->state()) {
      case LookupIterator::TRANSITION:
        UNREACHABLE();
      case LookupIterator::JSPROXY: {
        bool was_found;
        DirectHandle<JSAny> receiver = it->GetReceiver();
        // In case of global IC, the receiver is the global object. Replace by
        // the global proxy.
        if (IsJSGlobalObject(*receiver)) {
          receiver = direct_handle(
              Cast<JSGlobalObject>(*receiver)->global_proxy(), it->isolate());
        }
        if (is_global_reference) {
          Maybe<bool> maybe = JSProxy::HasProperty(
              it->isolate(), it->GetHolder<JSProxy>(), it->GetName());
          if (maybe.IsNothing()) return {};
          if (!maybe.FromJust()) {
            it->NotFound();
            return it->isolate()->factory()->undefined_value();
          }
        }
        MaybeHandle<JSAny> result =
            JSProxy::GetProperty(it->isolate(), it->GetHolder<JSProxy>(),
                                 it->GetName(), receiver, &was_found);
        if (!was_found && !is_global_reference) it->NotFound();
        return result;
      }
      case LookupIterator::WASM_OBJECT:
        return it->isolate()->factory()->undefined_value();
      case LookupIterator::INTERCEPTOR: {
        bool done;
        Handle<JSAny> result;
        ASSIGN_RETURN_ON_EXCEPTION(
            it->isolate(), result,
            JSObject::GetPropertyWithInterceptor(it, &done));
        if (done) return result;
        continue;
      }
      case LookupIterator::ACCESS_CHECK:
        if (it->HasAccess()) continue;
        return JSObject::GetPropertyWithFailedAccessCheck(it);
      case LookupIterator::MODULE_NAMESPACE:
        return it->isolate()->factory()->undefined_value();
      case LookupIterator::ACCESSOR:
        return it->isolate()->factory()->undefined_value();
      case LookupIterator::TYPED_ARRAY_INDEX_NOT_FOUND:
        return it->isolate()->factory()->undefined_value();
      case LookupIterator::DATA:
        return it->GetDataValue();
      case LookupIterator::STRING_LOOKUP_START_OBJECT:
        return it->GetStringPropertyValue();
      case LookupIterator::NOT_FOUND:
        if (it->IsAnyPrivateName()) {
          auto private_symbol = Cast<Symbol>(it->name());
          DirectHandle<String> name_string(
              Cast<String>(private_symbol->description()), it->isolate());
          if (private_symbol->is_private_brand()) {
            DirectHandle<String> class_name =
                (name_string->length() == 0)
                    ? it->isolate()->factory()->anonymous_string()
                    : name_string;
            THROW_NEW_ERROR(
                it->isolate(),
                NewTypeError(MessageTemplate::kInvalidPrivateBrandInstance,
                             class_name));
          }
          THROW_NEW_ERROR(
              it->isolate(),
              NewTypeError(MessageTemplate::kInvalidPrivateMemberRead,
                           name_string));
        }

        return it->isolate()->factory()->undefined_value();
    }
    UNREACHABLE();
  }
}
// end VisibleV8

""" + target
        content = content.replace(target, hook, 1)
        with open(obj_cc, "w") as f:
            f.write(content)
        print("  Patched src/objects/objects.cc")

    # 21. src/interpreter/bytecode-generator.cc
    bcg_cc = os.path.join(v8_dir, "src/interpreter/bytecode-generator.cc")
    with open(bcg_cc, "r") as f:
        content = f.read()
    if "Runtime::kTracePropertyLoad" not in content:
        # VisitAssignment
        t1 = "void BytecodeGenerator::VisitAssignment(Assignment* expr) {\n  AssignmentLhsData lhs_data = PrepareAssignmentLhs(expr->target());\n\n  VisitForAccumulatorValue(expr->value());"
        h1 = t1 + """\n
#ifdef VV8_TRACE_PROPERTIES
  // VisibleV8 (trace assignments to named/keyed properties only)
  if ((lhs_data.assign_type() == NAMED_PROPERTY) ||
      (lhs_data.assign_type() == KEYED_PROPERTY)) {
    // Save accumulator for later restoration
    Register saved_acc = register_allocator()->NewRegister();
    builder()->StoreAccumulatorInRegister(saved_acc);

    // Trace object/property/new-value for this assignment
    RegisterList trace_args = register_allocator()->NewRegisterList(4);
    builder()
        ->LoadLiteral(Smi::FromInt(expr->position()))
        .StoreAccumulatorInRegister(trace_args[0])
        .MoveRegister(lhs_data.object(), trace_args[1])
        .MoveRegister(saved_acc, trace_args[3]);
    if (lhs_data.assign_type() == NAMED_PROPERTY) {
      builder()
          ->LoadLiteral(lhs_data.name())
          .StoreAccumulatorInRegister(trace_args[2]);
    } else {
      builder()->MoveRegister(lhs_data.key(), trace_args[2]);
    }
    builder()->CallRuntime(Runtime::kTracePropertyStore,
                           trace_args);  // args: (call-site, this, key, value)

    // Restore accumulator
    builder()->LoadAccumulatorWithRegister(saved_acc);
  }
#endif"""
        content = content.replace(t1, h1, 1)

        # VisitCompoundAssignment
        t2 = "builder()->BinaryOperation(binop->op(), old_value, feedback_index(slot));\n  }"
        h2 = t2 + """\n#ifdef VV8_TRACE_PROPERTIES
  // VisibleV8 (trace assignments to named/keyed properties only)
  if ((lhs_data.assign_type() == NAMED_PROPERTY) ||
      (lhs_data.assign_type() == KEYED_PROPERTY)) {
    // Save accumulator for later restoration
    Register saved_acc = register_allocator()->NewRegister();
    builder()->StoreAccumulatorInRegister(saved_acc);

    // Trace object/property/new-value for this assignment
    RegisterList trace_args = register_allocator()->NewRegisterList(4);
    builder()
        ->LoadLiteral(Smi::FromInt(expr->position()))
        .StoreAccumulatorInRegister(trace_args[0])
        .MoveRegister(lhs_data.object(), trace_args[1])
        .MoveRegister(saved_acc, trace_args[3]);
    if (lhs_data.assign_type() == NAMED_PROPERTY) {
      builder()
          ->LoadLiteral(lhs_data.name())
          .StoreAccumulatorInRegister(trace_args[2]);
    } else {
      builder()->MoveRegister(lhs_data.key(), trace_args[2]);
    }
    builder()->CallRuntime(Runtime::kTracePropertyStore,
                           trace_args);  // args: (call-site, this, key, value)

    // Restore accumulator
    builder()->LoadAccumulatorWithRegister(saved_acc);
  }
#endif"""
        content = content.replace(t2, h2, 1)

        # VisitPropertyLoad - NAMED_PROPERTY
        t3 = "case NAMED_PROPERTY: {"
        h3 = """case NAMED_PROPERTY: {
#ifdef VV8_TRACE_PROPERTIES
      // VisibleV8: generate code to trace named property loads
      {
        RegisterList trace_args = register_allocator()->NewRegisterList(3);
        builder()
            ->LoadLiteral(Smi::FromInt(property->position()))
            .StoreAccumulatorInRegister(trace_args[0])
            .MoveRegister(obj, trace_args[1])
            .LoadLiteral(property->key()->AsLiteral()->AsRawPropertyName())
            .StoreAccumulatorInRegister(trace_args[2])
            .CallRuntime(Runtime::kTracePropertyLoad,
                         trace_args);  // args: (call-site, this, key)
      }
#endif"""
        content = content.replace(t3, h3, 1)

        # VisitPropertyLoad - KEYED_PROPERTY
        t4 = "case KEYED_PROPERTY: {\n      VisitForAccumulatorValueAsPropertyKey(property->key());\n      builder()->SetExpressionPosition(property);\n      BuildLoadKeyedProperty(obj, feedback_spec()->AddKeyedLoadICSlot());\n      break;\n    }"
        h4 = """case KEYED_PROPERTY: {
#ifdef VV8_TRACE_PROPERTIES
      // RESHUFFLED for VisV8--evaluate property key value into a register, not
      // the accumulator:
      Register key_reg = VisitForRegisterValue(property->key());

      // VisibleV8: generate code to trace keyed property loads
      {
        RegisterList trace_args = register_allocator()->NewRegisterList(3);
        builder()
            ->LoadLiteral(Smi::FromInt(property->position()))
            .StoreAccumulatorInRegister(trace_args[0])
            .MoveRegister(obj, trace_args[1])
            .MoveRegister(key_reg, trace_args[2])
            .CallRuntime(Runtime::kTracePropertyLoad,
                         trace_args);  // args: (call-site, this, key)
      }

      // RESHUFFLED for VisV8--move the stashed key value into the accumulator
      builder()->LoadAccumulatorWithRegister(key_reg);
#else
      VisitForAccumulatorValueAsPropertyKey(property->key());
#endif
      builder()->SetExpressionPosition(property);
      BuildLoadKeyedProperty(obj, feedback_spec()->AddKeyedLoadICSlot());
      break;
    }"""
        content = content.replace(t4, h4, 1)

        # VisitCall
        t5 = "void BytecodeGenerator::VisitCall(Call* expr) {\n  Expression* callee_expr = expr->expression();\n  Call::CallType call_type = expr->GetCallType();"
        h5 = "void BytecodeGenerator::VisitCall(Call* expr) {\n  Expression* callee_expr = expr->expression();\n  Call::CallType call_type = expr->GetCallType();\n\n  builder()->CallRuntime(Runtime::kTraceFunctionCall);"
        content = content.replace(t5, h5, 1)

        # VisitCountOperation
        t6 = "  // Perform +1/-1 operation.\n  builder()->UnaryOperation(expr->op(), feedback_index(count_slot));\n\n  // Store the value."
        h6 = """  // Perform +1/-1 operation.
  builder()->UnaryOperation(expr->op(), feedback_index(count_slot));

#ifdef VV8_TRACE_PROPERTIES
  // VisibleV8 (trace assignments to named/keyed properties only)
  if ((assign_type == NAMED_PROPERTY) || (assign_type == KEYED_PROPERTY)) {
    // Save accumulator for later restoration
    Register saved_acc = register_allocator()->NewRegister();
    builder()->StoreAccumulatorInRegister(saved_acc);

    // Trace object/property/new-value for this assignment
    RegisterList trace_args = register_allocator()->NewRegisterList(4);
    builder()
        ->LoadLiteral(Smi::FromInt(expr->position()))
        .StoreAccumulatorInRegister(trace_args[0])
        .MoveRegister(object, trace_args[1])
        .MoveRegister(saved_acc, trace_args[3]);
    if (assign_type == NAMED_PROPERTY) {
      builder()->LoadLiteral(name).StoreAccumulatorInRegister(trace_args[2]);
    } else {
      builder()->MoveRegister(key, trace_args[2]);
    }
    builder()->CallRuntime(Runtime::kTracePropertyStore,
                           trace_args);  // args: (call-site, this, key, value)

    // Restore accumulator
    builder()->LoadAccumulatorWithRegister(saved_acc);
  }
#endif

  // Store the value."""
        content = content.replace(t6, h6, 1)
        with open(bcg_cc, "w") as f:
            f.write(content)
        print("  Patched src/interpreter/bytecode-generator.cc")

def patch_chromium(cr_dir):
    print("Patching Chromium in", cr_dir)
    # 1. content/renderer/renderer_main.cc
    rm_cc = os.path.join(cr_dir, "content/renderer/renderer_main.cc")
    with open(rm_cc, "r") as f:
        content = f.read()
    if "bool need_sandbox = false; // VisibleV8" not in content:
        content = content.replace(
            "bool need_sandbox =\n        !command_line.HasSwitch(sandbox::policy::switches::kNoSandbox);",
            "bool need_sandbox = false; // VisibleV8 disable sandbox for desktop"
        )
        with open(rm_cc, "w") as f:
            f.write(content)
        print("  Patched content/renderer/renderer_main.cc")

    # 2. base/android/java/src/org/chromium/base/process_launcher/BindService.java
    bs_java = os.path.join(cr_dir, "base/android/java/src/org/chromium/base/process_launcher/BindService.java")
    with open(bs_java, "r") as f:
        content = f.read()
    if "!true;  // VisibleV8" not in content:
        content = content.replace(
            "&& !BuildConfig.IS_INCREMENTAL_INSTALL;",
            "&& !true;  // VisibleV8 android change required disabling renderer isolation."
        )
        with open(bs_java, "w") as f:
            f.write(content)
        print("  Patched BindService.java")

    # 3. chrome/android/java/AndroidManifest.xml
    am_xml = os.path.join(cr_dir, "chrome/android/java/AndroidManifest.xml")
    with open(am_xml, "r") as f:
        content = f.read()
    if 'android:name="org.chromium.content.app.SandboxedProcessService{{ i }}"\n          android:process=":sandboxed_process{{ i }}"\n          android:permission="{{ manifest_package }}.permission.CHILD_SERVICE"\n          android:isolatedProcess="false"' not in content:
        content = content.replace(
            'android:name="org.chromium.content.app.SandboxedProcessService{{ i }}"\n          android:process=":sandboxed_process{{ i }}"\n          android:permission="{{ manifest_package }}.permission.CHILD_SERVICE"\n          android:isolatedProcess="true"',
            'android:name="org.chromium.content.app.SandboxedProcessService{{ i }}"\n          android:process=":sandboxed_process{{ i }}"\n          android:permission="{{ manifest_package }}.permission.CHILD_SERVICE"\n          android:isolatedProcess="false"'
        )
        with open(am_xml, "w") as f:
            f.write(content)
        print("  Patched AndroidManifest.xml")

    # 4. third_party/blink/renderer/platform/bindings/v8_binding.h
    v8b_h = os.path.join(cr_dir, "third_party/blink/renderer/platform/bindings/v8_binding.h")
    with open(v8b_h, "r") as f:
        content = f.read()
    if "v8/include/v8-visiblev8.h" not in content:
        content = content.replace(
            '#include "v8/include/v8-value.h"',
            '#include "v8/include/v8-visiblev8.h"\n#include "v8/include/v8-value.h"'
        )
        with open(v8b_h, "w") as f:
            f.write(content)
        print("  Patched v8_binding.h")

    # 5. third_party/blink/renderer/modules/remote_objects/remote_object.cc
    ro_cc = os.path.join(cr_dir, "third_party/blink/renderer/modules/remote_objects/remote_object.cc")
    with open(ro_cc, "r") as f:
        content = f.read()
    if '"base/logging.h"' not in content:
        content = content.replace(
            '#include <tuple>',
            '#include <tuple>\n\n#include "base/logging.h"'
        )
        with open(ro_cc, "w") as f:
            f.write(content)
        print("  Patched remote_object.cc")

    # 6. content/renderer/java/gin_java_function_invocation_helper.cc
    gj_cc = os.path.join(cr_dir, "content/renderer/java/gin_java_function_invocation_helper.cc")
    with open(gj_cc, "r") as f:
        content = f.read()
    if "v8/include/v8-visiblev8.h" not in content:
        content = content.replace(
            '#include "v8/include/v8-exception.h"',
            '#include "v8/include/v8-exception.h"\n#include "v8/include/v8-visiblev8.h"'
        )
        target_invoke = "  mojom::GinJavaBridgeError error =\n      mojom::GinJavaBridgeError::kGinJavaBridgeNoError;"
        hook_invoke = """  std::vector<v8::Local<v8::Value>> visv8_args;

  v8::Local<v8::Value> val;
  while (args->GetNext(&val)) {
    visv8_args.push_back(val);
  }

  mojom::GinJavaBridgeError error =
      mojom::GinJavaBridgeError::kGinJavaBridgeNoError;"""
        content = content.replace(target_invoke, hook_invoke, 1)

        t_err = "  if (!result.get()) {"
        h_err = """  if (!result.get()) {
    auto* functionCallbackInfo = args->GetFunctionCallbackInfo();
    v8::visv8_log_java_api_call(
        args->isolate(), false, functionCallbackInfo->Data().As<v8::String>(),
        functionCallbackInfo->This().As<v8::Object>(),
        v8::Undefined(args->isolate()), visv8_args, visv8_args.size());"""
        content = content.replace(t_err, h_err, 1)

        t_blob = "  if (!result->is_blob()) {\n    return converter_->ToV8Value(result.get(),\n                                 args->isolate()->GetCurrentContext());\n  }"
        h_blob = """  if (!result->is_blob()) {
    auto* functionCallbackInfo = args->GetFunctionCallbackInfo();
    v8::visv8_log_java_api_call(
        args->isolate(), false, functionCallbackInfo->Data().As<v8::String>(),
        functionCallbackInfo->This().As<v8::Object>(),
        converter_->ToV8Value(result.get(),
                              args->isolate()->GetCurrentContext()),
        visv8_args, visv8_args.size());
    return converter_->ToV8Value(result.get(),
                                 args->isolate()->GetCurrentContext());
  }"""
        content = content.replace(t_blob, h_blob, 1)

        t_obj = "      if (!object_result->GetWrapper(args->isolate()).ToLocal(&controller)) {\n        return v8::Undefined(args->isolate());\n      }\n      return controller;"
        h_obj = """      if (!object_result->GetWrapper(args->isolate()).ToLocal(&controller)) {
        auto* functionCallbackInfo = args->GetFunctionCallbackInfo();
        v8::visv8_log_java_api_call(
            args->isolate(), false,
            functionCallbackInfo->Data().As<v8::String>(),
            functionCallbackInfo->This().As<v8::Object>(),
            v8::Undefined(args->isolate()), visv8_args, visv8_args.size());
        return v8::Undefined(args->isolate());
      }
      auto* functionCallbackInfo = args->GetFunctionCallbackInfo();
      v8::visv8_log_java_api_call(args->isolate(), false,
                                  functionCallbackInfo->Data().As<v8::String>(),
                                  functionCallbackInfo->This().As<v8::Object>(),
                                  controller, visv8_args, visv8_args.size());
      return controller;"""
        content = content.replace(t_obj, h_obj, 1)

        t_nf = "    gin_value->GetAsNonFinite(&float_value);\n    return v8::Number::New(args->isolate(), float_value);"
        h_nf = """    gin_value->GetAsNonFinite(&float_value);
    auto* functionCallbackInfo = args->GetFunctionCallbackInfo();
    v8::visv8_log_java_api_call(args->isolate(), false,
                                functionCallbackInfo->Data().As<v8::String>(),
                                functionCallbackInfo->This().As<v8::Object>(),
                                v8::Number::New(args->isolate(), float_value),
                                visv8_args, visv8_args.size());
    return v8::Number::New(args->isolate(), float_value);"""
        content = content.replace(t_nf, h_nf, 1)

        t_end = "  return v8::Undefined(args->isolate());\n}"
        h_end = """  auto* functionCallbackInfo = args->GetFunctionCallbackInfo();
  v8::visv8_log_java_api_call(
      args->isolate(), false, functionCallbackInfo->Data().As<v8::String>(),
      functionCallbackInfo->This().As<v8::Object>(),
      v8::Undefined(args->isolate()), visv8_args, visv8_args.size());
  return v8::Undefined(args->isolate());
}"""
        content = content.replace(t_end, h_end, 1)
        with open(gj_cc, "w") as f:
            f.write(content)
        print("  Patched gin_java_function_invocation_helper.cc")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "chromium":
        patch_chromium("/work/chromium")
    else:
        patch_v8("/work/v8")
