

### 1. Frida JavaScript API — most important

**Frida official JavaScript API**  
[https://frida.re/docs/javascript-api](https://frida.re/docs/javascript-api)

Ctrl+F these:

```text
Java.perform
Java.use
implementation
overload
enumerateLoadedClasses
enumerateClassLoaders
Java.classFactory.loader

Interceptor.attach
Process.getModuleByName
getExportByName
Memory
NativePointer
```

My basic Java-hook template:

```javascript
Java.perform(function () {
    const C = Java.use("com.foo.SomeClass");

    C.someMethod.implementation = function () {
        console.log("someMethod called");

        const ret = this.someMethod();
        console.log("ret =", ret);

        return ret;
    };
});
```

For bypassing something:

```javascript
Java.perform(function () {
    const C = Java.use("com.foo.Security");

    C.isRooted.implementation = function () {
        console.log("isRooted()");
        return false;
    };
});
```

And native:

```javascript
const m = Process.getModuleByName("libfoo.so");

console.log("base =", m.base);

const f = m.getExportByName("some_function");

Interceptor.attach(f, {
    onEnter(args) {
        console.log("arg0 =", args[0]);
    },
    onLeave(retval) {
        console.log("ret =", retval);
    }
});
```

The API page is broad enough that its table of contents includes Process, Module, Memory, Network, File/Stream and the Java runtime APIs.

---

### 2. OWASP MASTG — Frida on Android

**OWASP MASTG: Frida (Android)**  
[https://mas.owasp.org/MASTG/tools/android/MASTG-TOOL-0001](https://mas.owasp.org/MASTG/tools/android/MASTG-TOOL-0001)

**Android-specific Frida cookbook**

Useful commands to have immediately available:

```bash
frida-ps -U

frida-ps -Uai

frida -U -f com.foo.app

frida -U -f com.foo.app -l hook.js

frida -U -p <PID> -l hook.js
```


---

### 3. Android official `adb` reference

**Android Debug Bridge — Android Developers**  
[https://developer.android.com/tools/adb](https://developer.android.com/tools/adb)

This is my "I know Android can tell me this but forgot the exact command" tab.

```bash
adb devices

adb shell
```

Find package:

```bash
adb shell pm list packages | grep guardian
```

Find APK:

```bash
adb shell pm path com.foo.guardian
```

Something like:

```text
package:/data/app/~~XYZ/com.foo.guardian-ABC/base.apk
```

Pull it:

```bash
adb pull /data/app/.../base.apk
```

Find processes:

```bash
adb shell ps -A | grep guardian
```

or:

```bash
adb shell pidof com.foo.guardian
```

Inspect package:

```bash
adb shell dumpsys package com.foo.guardian
```

Activities/services:

```bash
adb shell dumpsys activity
adb shell dumpsys activity services
```

Logs:

```bash
adb logcat
```

or:

```bash
adb logcat --pid=$(adb shell pidof com.foo.guardian)
```

Android separately documents `dumpsys` as the mechanism for getting diagnostic information from Android system services.

---

# 4. Linux `/proc` — this may save the interview


[https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html](https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html)


Linux exposes every open FD under:

```text
/proc/<PID>/fd/
```

and sockets appear as links like:

```text
socket:[2248868]
```

That socket inode can then be correlated with `/proc/net/*`.

This gives me a systematic way of answering:

> Who has this file open?

```bash
adb shell su -c 'lsof | grep policy.db'
```

or:

```bash
adb shell su -c 'ls -l /proc/12345/fd'
```

For an unknown PID:

```bash
cat /proc/12345/cmdline
```

Identity/UID:

```bash
cat /proc/12345/status
```

Loaded libraries:

```bash
cat /proc/12345/maps
```

Then:

```bash
cat /proc/12345/maps | grep '\.so'
```

Executable:

```bash
readlink /proc/12345/exe
```

Current working directory:

```bash
readlink /proc/12345/cwd
```

Open files/sockets:

```bash
ls -l /proc/12345/fd
```

For networking:

```bash
ss -tunap
```

and:

```bash
cat /proc/net/tcp
cat /proc/net/tcp6
cat /proc/net/udp
cat /proc/net/unix
```

`/proc/<pid>/net/*` represents the process's **network namespace**, not simply "connections owned by this process." To prove socket ownership you can map:

```text
/proc/PID/fd
      ↓
socket:[INODE]
      ↓
/proc/net/tcp
      ↓
local/remote endpoint
```

The procfs documentation explicitly describes `/proc/.../net` entries including UNIX-domain sockets and their inode information.

---

# 5. Android JNI Tips

**Android NDK — JNI Tips**  
[https://developer.android.com/ndk/guides/jni-tips](https://developer.android.com/ndk/guides/jni-tips)

This is the page I'd open the moment the investigation crosses:

native methods can be found either through runtime symbol lookup or explicitly registered with `RegisterNatives()`, with Android recommending registration from `JNI_OnLoad()`.

So if JADX shows:

```java
native boolean verifyToken(byte[] x);
```

but:

```bash
nm -D libfoo.so
```

doesn't show:

```text
Java_com_foo_verifyToken
```

I look for:

```text
JNI_OnLoad
RegisterNatives
JNINativeMethod
FindClass
```

in IDA/Ghidra.


---

## One sixth tab I'd keep bookmarked

**AOSP — AIDL overview**  
[https://source.android.com/docs/core/architecture/aidl](https://source.android.com/docs/core/architecture/aidl)

I probably wouldn't keep it permanently visible, but I'd know where it is.

The useful mental picture is:

```text
caller
  ↓
proxy
  ↓
Parcel / Binder transaction
  ↓
Binder kernel driver
  ↓
remote Binder thread
  ↓
stub
  ↓
actual implementation
```

AOSP describes exactly this: arguments and method identifier are packed into a buffer, sent through Binder to another process, received by a Binder thread and unpacked by the server stub.

It also gives useful on-device commands:

```bash
adb shell dumpsys --help
adb shell service --help
```

for inspecting/interacting with Android services.

---

# cheat sheet


I'd have this mental decision tree.

```text
WHAT AM I LOOKING AT?
        │
        ├── application name
        │      ↓
        │   pm / dumpsys
        │
        ├── PID
        │      ↓
        │   /proc/PID
        │
        ├── file
        │      ↓
        │   lsof → /proc/*/fd → strace/Frida
        │
        ├── socket
        │      ↓
        │   ss → socket inode → PID → code
        │
        ├── Java behavior
        │      ↓
        │   JADX → Frida Java.use()
        │
        ├── class missing
        │      ↓
        │   ClassLoader / DexClassLoader
        │
        ├── native library
        │      ↓
        │   maps → IDA → JNI → Frida Interceptor
        │
        └── another process
               ↓
            socket?
            Binder?
            pipe?
            shared memory?
            file?
```

And for the exact **"this file changes — who's looking at it?"** question:

```bash
# 1. Is it currently open?
adb shell su -c 'lsof | grep policy.db'

# 2. Which process?
adb shell ps -A | grep <PID-or-name>

# 3. Who exactly is that process?
adb shell su -c 'cat /proc/<PID>/cmdline'
adb shell su -c 'cat /proc/<PID>/status'

# 4. What does it have open?
adb shell su -c 'ls -l /proc/<PID>/fd'

# 5. What code is loaded?
adb shell su -c 'cat /proc/<PID>/maps'

# 6. Observe syscalls if available
adb shell su -c 'strace -f -p <PID> -e trace=openat,read,write,close'

# 7. Then move upward to Frida/JADX if necessary.
```

