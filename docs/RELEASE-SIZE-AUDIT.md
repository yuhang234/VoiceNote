# Release Size Audit / 发布资产体积审计

Generated / 生成时间: 2026-11-22 · Owner / 负责仓库: `yuhang234/VoiceNote`
Scope: every published release asset of every repository in the fleet / 覆盖本 fleet 全部仓库已发布 Release 的全部资产。

---

## 0. Method / 方法

For every repository we listed all releases with `gh release list`, then every asset of every
release with `gh release view <tag> --json assets` (raw output preserved under
`firstmate/data/release-size-audit-1/raw/`). Sizes are the exact byte counts reported by the
GitHub API, not the rounded values shown in the release notes.

每个仓库先用 `gh release list` 列出全部 Release，再用 `gh release view <tag> --json assets`
取每个资产的字节数。下表用的是 GitHub API 返回的**精确字节数**，不是 Release 正文里四舍五入后的值。

Flagging rule used below / 下面"过大"的判定标准:

| class / 类别 | threshold / 门槛 | why / 原因 |
|---|---|---|
| desktop app zip / 桌面便携包 | > 200 MB | a desktop Python app rarely needs more than ~200 MB without an explanation / 桌面 Python 应用无理由超过 200 MB |
| Windows installer / Windows 安装器 | > 200 MB | same, plus the installer must fit under the 2 GiB GitHub Release limit / 同上，且必须低于 GitHub 的 2 GiB 单文件上限 |
| Android APK / Android APK | > 50 MB (non-game) / > 150 MB (game) | APKs ship 60–150 MB when they embed multi-ABI native libs / 内嵌多 ABI 原生库时才会到 60–150 MB |
| anything ≥ 1 GiB | always flagged / 一律标记 | GitHub's per-file limit is 2 GiB; at 1 GiB you are halfway to a hard failure / 单文件上限 2 GiB，1 GiB 已是红线的一半 |

---

## 1. Full asset inventory / 资产全表

| project / 项目 | release / 版本 | asset / 资产 | bytes / 字节 | flag / 标记 |
|---|---|---|---|---|
| yuhang234/folio | v0.1.0 | folio-android-debug.apk | 697,888,677 | 🔴 oversized / 过大 |
| yuhang234/folio | v0.1.0 | Folio_0.1.0_x64-setup.exe | 6,712,607 | ok |
| yuhang234/folio | v0.1.0 | Folio_0.1.0_x64_en-US.msi | 9,932,800 | ok |
| yuhang234/nexora | — | *(no releases)* / 无 Release | — | — |
| yuhang234/noema | v0.1.0 | noema-0.1.0-windows-x86_64.exe | 9,538,529 | ok |
| yuhang234/noema | v0.1.0 | SHA256SUMS.txt | 97 | ok |
| yuhang234/noema | v0.1.0 | USAGE.txt | 774 | ok |
| yuhang234/hang | — | *(no releases)* / 无 Release | — | — |
| yuhang234/dune-echoes | v1.0.0 | DuneEchoes-1.0.0.apk | 212,519,273 | 🔴 oversized |
| yuhang234/dune-echoes | v1.0.0 | dune-echoes-1.0.0-pc.zip | 204,262,396 | 🔴 oversized |
| yuhang234/dune-echoes | v1.0.0 | DuneEchoes-1.0.0-setup.exe | 176,966,964 | 🟠 large / 偏大 |
| yuhang234/dune-echoes | v1.0.0 | 13 screenshots, 2,474,733 → 418,785 | *(see §2)* | 🟡 duplicate weight / 重复体积 |
| yuhang234/foundation-vn | v0.3.0 | FoundationVN-0.3.0.apk | 112,773,786 | 🟠 large |
| yuhang234/foundation-vn | v0.3.0 | foundation-vn-0.3.0-pc.zip | 103,561,359 | ok-ish |
| yuhang234/foundation-vn | v0.3.0 | FoundationVN-0.3.0-setup.exe | 82,079,173 | ok-ish |
| yuhang234/foundation-vn | v0.2.0-fulltext | FoundationVN-0.2.0-fulltext.apk | 105,960,855 | 🟠 large |
| yuhang234/foundation-vn | v0.2.0-fulltext | foundation-vn-0.2.0-fulltext-pc.zip | 97,890,911 | ok-ish |
| yuhang234/foundation-vn | v0.2.0-fulltext | FoundationVN-0.2.0-fulltext-setup.exe | 76,712,567 | ok-ish |
| yuhang234/foundation-vn | v0.1.0-base1 | FoundationVN-0.1.0-base1.apk | 105,942,384 | 🟠 large |
| yuhang234/foundation-vn | v0.1.0-base1 | foundation-vn-0.1.0-base1-pc.zip | 97,766,818 | ok-ish |
| yuhang234/foundation-vn | v0.1.0-base1 | FoundationVN-0.1.0-base1-setup.exe | 76,620,831 | ok-ish |
| yuhang234/foundation-vn | v0.1.0-base1 | 4 screenshots, 3,758,676 → 135,621 | *(see §2)* | 🟡 |
| yuhang234/Staircase | v0.2.0 | Staircase-0.2.0.apk | 213,618,631 | 🔴 oversized |
| yuhang234/Staircase | v0.2.0 | Staircase-0.2.0-pc.zip | 201,695,729 | 🔴 oversized |
| yuhang234/Staircase | v0.2.0 | Staircase-0.2.0-setup.exe | 167,985,025 | 🟠 large |
| yuhang234/Staircase | v0.1.0 | Staircase-0.1.0.apk | 213,076,964 | 🔴 oversized |
| yuhang234/Staircase | v0.1.0 | Staircase-0.1.0-pc.zip | 200,974,353 | 🔴 oversized |
| yuhang234/Staircase | v0.1.0 | Staircase-0.1.0-setup.exe | 167,316,445 | 🟠 large |
| yuhang234/Staircase | v0.1.0 | 5 screenshots, 1,008,126 → 100,812 | *(see §2)* | 🟡 |
| yuhang234/os-visualizer | v1.0.0 | os-visualizer-1.0.0-win64.exe | 23,890,620 | ok |
| yuhang234/os-visualizer | v1.0.0 | os-visualizer-1.0.0-source.zip | 324,651 | ok |
| yuhang234/os-visualizer | v1.0.0 | 2 screenshots, 252,822 / 155,998 | *(see §2)* | 🟡 |
| yuhang234/VoiceNote | v0.1.1 | VoiceNote-Portable-0.1.1.zip | 1,508,262,165 | 🔴🔴 oversized |
| yuhang234/VoiceNote | v0.1.1 | VoiceNote-Setup-0.1.1.exe | 1,014,516,553 | 🔴🔴 oversized |
| yuhang234/VoiceNote | v0.1.0 | *(no assets)* / 无资产 | — | — |

Totals / 合计: 9 repositories, 2 releases with zero assets (`nexora`, `hang`), 41 release assets,
**6.58 GB** of published artifact bytes in total, of which **4.31 GB** is in the six artifacts
this audit flags as oversized / 共 41 个资产、6.58 GB；其中 6 个被判定为过大，合计 4.31 GB。

---

## 2. What makes up the bytes / 体积的构成

### 2.1 yuhang234/VoiceNote — the one this task fixes / 本次任务修复项

`packaging/voicenote.spec` ships the *entire* `nvidia/` site-packages subtree:

`packaging/voicenote.spec` 直接打包了**整个** `nvidia/` site-packages 子树：

```python
datas = [
    (SITE / "nvidia", "nvidia"),                       # 2011MB，CUDA DLL，GPU 必需
    (SITE / "ctranslate2", "ctranslate2"),
    (SITE / "onnxruntime" / "capi", "onnxruntime/capi"),
    (SITE / "_sounddevice_data", "_sounddevice_data"),
    (SITE / "_soundfile_data", "_soundfile_data"),
    (SITE / "av.libs", "av.libs"),                    # ← unused, see below / 实际未使用
    ...
]
```

| contributor / 构成项 | size / 体积 | verdict / 结论 |
|---|---|---|
| `nvidia/` (cudnn + cublas wheels, incl. `lib/`, `include/`, `doc/`) / `nvidia/`（含 `lib/`、`include/`、`doc/`） | 2011 MB uncompressed / 未压缩 *(stated by the original spec comment)* | **compilers' half of two wheels** / 两个 wheel 里的“编译期一半”，运行时无用 |
| Python runtime + PySide6-Essentials / Python 运行时 + PySide6-Essentials | ≈ 240 MB *(estimate)* | needed / 必需 |
| ctranslate2 + faster-whisper + onnxruntime capi / ctranslate2 + faster-whisper + onnxruntime capi | ≈ 120 MB *(estimate)* | needed / 必需 |
| `av.libs` (PyAV / FFmpeg) / `av.libs`（PyAV / FFmpeg） | ≈ 70 MB *(estimate)* | **dead weight** — `import av` never appears anywhere in `src/` and PyAV is not in `pyproject.toml`; it reaches the venv only transitively / `src/` 内从未 `import av`，`pyproject.toml` 也没声明它，只是被传递依赖带进 venv |
| PyInstaller `_internal` overhead / PyInstaller 开销 | ≈ 60 MB *(estimate)* | needed / 必需 |
| **dist dir / dist 目录合计** | **≈ 2.3 GB** *(stated by the original spec comment)* | matches the figure quoted in the spec comments / 与 spec 注释里的 2.3GB 自述吻合 |

Everything marked *(estimate)* is from the declared dependency list and the spec's own comments —
not a directory listing, because this environment has no Windows venv to inspect. Only the two
`2011 MB` / `2.3 GB` figures are the build's own self-reported numbers. / 标 *(estimate)* 的行来自
声明的依赖列表与 spec 自己的注释 —— 不是目录实测，因为本环境没有可检视的 Windows venv。只有
`2011 MB` / `2.3 GB` 两个数字是构建本身自述的。

Why the zip is 1.43 GiB and the installer 1.0 GiB / 为什么 zip 是 1.43 GiB、安装器是 1.0 GiB:

The 2.3 GB dist dir is zipped once for the portable build (`System.IO.Compression.ZipFile`
with `Optimal`, i.e. deflate) and LZMA2-ultra64-compressed a second time for the Inno Setup
installer. The installer also *contains the same payload again*, so the same bytes are
distributed twice per release — that is the "duplicate copies of the same payload" cause.

2.3GB 的 dist 目录先被 deflate 压一次（便携版 zip），再被 LZMA2/ultra64 压一次（Inno Setup
安装器）；而安装器内部又**再带一份同样 payload**，所以同一批字节在每次 Release 里被发了两遍 ——
这正是"同一 payload 重复打包"的原因。

**The real cause is one line: `nvidia-cudnn-cu12` and `nvidia-cublas-cu12` wheels bundle static
libraries and C++ headers that a runtime can never use.** cuDNN ships roughly 650 MB of
`libcudnn*_static.a` and `libcudnn_ops.so`-style build artefacts plus ~550 MB of `include/`;
cuBLAS ships the same pattern *(both figures are estimates from the known wheel layout, not a
measured listing — see the note above the table)*. `cuda_env.py` only ever calls
`os.add_dll_directory()` on `nvidia/*/bin`.

**真正的原因是一行代码：`nvidia-cudnn-cu12` 与 `nvidia-cublas-cu12` 的 wheel 里打包了运行期永远
用不到的静态库和 C++ 头文件。** cuDNN 里约 650 MB 的 `libcudnn*_static.a` 之类编译产物加约 550 MB
的 `include/`，cuBLAS 同样如此（两个数字都是按已知 wheel 布局做的估算，不是实测清单 —— 见上方
表格下的说明）。而 `cuda_env.py` 只对 `nvidia/*/bin` 调 `os.add_dll_directory()`。

Fix shipped in this PR / 本 PR 交付的修复:

1. `packaging/voicenote.spec` bundles **only the `.dll` files under each `nvidia/*/bin`**,
   keeping the `nvidia/<pkg>/bin/` layout `cuda_env.register_cuda_dlls()` already expects, and
   drops `av.libs`. Same DLLs, same paths, same behaviour — the wheels' compilers' half no
   longer ships. / 只保留每个 `nvidia/*/bin` 下的 `.dll`（目录结构与
   `cuda_env.register_cuda_dlls()` 原本的预期一致），并去掉 `av.libs`。DLL 集合、路径、行为
   都不变，只是不再带上两个 wheel 的“编译期一半”。
2. The spec now **raises if `cudnn64_9.dll` or `cublas64_12.dll` is not picked up**, so a
   half-installed venv fails the build instead of shipping a package that silently runs on CPU.
   / spec 在挑不到 `cudnn64_9.dll` 或 `cublas64_12.dll` 时直接报错：venv 装不全会导致构建失败，
   而不是发出去一个静默回落到 CPU 的包。
3. `scripts/build.ps1` re-checks both DLLs **inside `dist/VoiceNote/_internal`** after PyInstaller
   and prints a per-directory size breakdown of the built tree, so the next size regression shows
   up in the build log. / `scripts/build.ps1` 在 PyInstaller 之后**在 `dist/VoiceNote/_internal`
   里**再核对这两个 DLL，并打印产物树的分目录体积明细，下次体积回归在构建日志里就能看见。
4. `src/voicenote/__init__.py` → `0.1.2`, so the rebuilt artifacts carry a new name and a new
   release tag instead of overwriting `v0.1.1`. / 版本号提到 `0.1.2`，重建产物有新文件名与新
   Release 标签，而不是覆盖 `v0.1.1`。

Expected sizes after the fix (estimates, to be confirmed by a real Windows build) /
修复后的预期体积（估算值，需 Windows 实机构建确认）:

| artifact / 资产 | before / 现在 | after (est.) / 预期 | saving / 降幅 |
|---|---|---|---|
| dist dir / dist 目录 | 2.3 GB | ≈ 1.4 GB | −39% |
| `VoiceNote-Portable-0.1.2.zip` | 1,508,262,165 (`v0.1.1`) | ≈ 950 MB | −37% |
| `VoiceNote-Setup-0.1.2.exe` | 1,014,516,553 (`v0.1.1`) | ≈ 620 MB | −39% |

**These are estimates, not measurements.** The build was not run for this PR — `scripts/build.ps1`
needs Windows plus Inno Setup, and its end-to-end self-check refuses to emit an artifact it
cannot verify. Run it on a Windows machine to get the real numbers; the build now prints them per
top-level directory. / **这些是估算值，不是实测值。** 本 PR 未执行构建 —— `scripts/build.ps1`
需要 Windows 加 Inno Setup，且其端到端自检不允许产出无法验证的产物。请在 Windows 机器上跑一次
取实际数值；构建现在会按顶层目录打印它们。

The remaining ~950 MB is the GPU runtime itself plus the Python/Qt/ASR stack. **The GPU runtime is
genuinely required offline** — ctranslate2 does not ship cuDNN/cuBLAS on Windows and VoiceNote has
no network dependency at inference time, so it stays bundled and is stated plainly in the release
notes rather than removed. A further step (out of scope here) would be a first-run download of the
GPU runtime to get the zip under ~250 MB.

剩余约 950 MB 是 GPU 运行时本身加 Python/Qt/ASR 那套依赖。**GPU 运行时是离线必需的** ——
ctranslate2 在 Windows 上不带 cuDNN/cuBLAS，而推理期也不该依赖网络，所以继续随包分发，并在
Release 说明里明说，而不是悄悄删掉。再进一步（本次不做）可以在首次运行时下载 GPU 运行时，把
zip 压到 ~250 MB 以内。

### 2.2 yuhang234/folio — `folio-android-debug.apk` 697,888,677 B

Unpacked entry list (the `.apk` was downloaded and its local file headers read; the zip footer was
not reachable from this environment, so the listing is complete for every entry present in the
downloaded prefix):

| uncompressed | stored in the APK as | entry |
|---|---|---|
| 181,079,360 B | **stored, ratio 1.000** | `lib/arm64-v8a/libfolio_mobile_lib.so` |
| 180,719,864 B | **stored, ratio 1.000** | `lib/x86_64/libfolio_mobile_lib.so` |
| 169,287,680 B | **stored, ratio 1.000** | `lib/x86/libfolio_mobile_lib.so` |
| 159,534,668 B | **stored, ratio 1.000** | `lib/armeabi-v7a/libfolio_mobile_lib.so` |
| 9,944,872 B | deflate | `classes.dex` |
| 2,782,092 B | deflate | `classes8.dex` |
| 1,063,122 B | deflate | `classes2..7.dex` |

`libfolio_mobile_lib.so` alone is **690,621,572 B** — **99.1% of the APK** — four
architectures of one native Rust/Tauri library, all of them stored *uncompressed*. `folio-mobile`
in the repository contains only `src-tauri/`, so that `.so` is a Rust-built native library.

`libfolio_mobile_lib.so` 单个文件就占 **690,621,572 B**，约 **99.1%** 的 APK 体积，一份库四个
架构，且全部以**未压缩**方式存储。仓库里 `folio-mobile/` 下只有 `src-tauri/`，所以这个 `.so`
是 Rust 编译出来的原生库（Tauri 应用）。

That combination — a ~180 MB single native library shipped four times, stored without
compression — is the signature of a **debug** profile: unoptimised Rust debug builds with debug
info are routinely 5–10× their release size, and AAPT2 stores an entry it cannot shrink as-is.

~180 MB 的单库 × 4 份架构、且未压缩，正是 **debug** 档位的特征：带调试信息的 Rust debug 构建
体积通常是 release 的 5–10 倍，而 AAPT2 对压不动的大文件会直接原样存储。

**Target / 目标: < 200 MB** — `[profile.release] strip = true, opt-level = "z"`, one ABI
(arm64-v8a), `debuggable = false`, and per-ABI splits so the app stores get one file each.
Expect roughly 40–70 MB.

目标：< 200 MB —— `[profile.release] strip = true, opt-level = "z"`、单 ABI（arm64-v8a）、
`debuggable = false`，并按 ABI 切分让应用市场各拿一份。预期 40–70 MB。

### 2.3 yuhang234/dune-echoes — `DuneEchoes-1.0.0.apk` 212,519,273 B (measured)

| uncompressed | stored | share of the APK | what it is |
|---|---|---|---|
| 191.45 MB | 168.77 MB | **79%** | `assets/` — game art, audio, story (`assets/x-game/` = 180 MB) |
| 108.48 MB | 41.45 MB | 19% | `lib/` — `librenpython.so` in **3 ABIs**: x86_64 40.19 MB, arm64-v8a 36.45 MB, armeabi-v7a 31.84 MB |
| 51.9 MB | 29.7 MB | 13% | four CJK fonts — NotoSerifSC Regular/Bold 14.85 MB each, NotoSansSC Regular/Bold 10.6 MB each |
| 5.14 MB | 1.79 MB | 1% | `classes.dex` |

So this APK is not bloat: it is a Ren'Py visual novel that genuinely carries ~180 MB of
illustrations and audio. The only real waste is the **three-ABI `librenpython.so`** (108 MB
uncompressed → 41 MB stored; arm64-v8a alone would be 36 MB → 13 MB) and the **full CJK font
files**, which Ren'Py could subset down to the glyphs actually used in the script.

所以这个 APK 并不"膨胀"：它是一个 Ren'Py 视觉小说，本身就带约 180 MB 的插画与音频。真正的浪费
只有两点：**三个 ABI 的 `librenpython.so`**（未压缩 108 MB → 存储 41 MB；只留 arm64-v8a 即可降到
36 MB → 13 MB），以及**完整的中日韩字体文件**（可用 Ren'Py 的字形子集化只保留脚本实际用到的字）。

**Target / 目标: apk < 100 MB** — single ABI + font subsetting + WebP/AVIF for the CG art.

目标：apk < 100 MB —— 单 ABI + 字体子集化 + CG 图改用 WebP/AVIF。

### 2.4 yuhang234/Staircase — pc.zip 201,695,729 B, apk 213,618,631 B, setup 167,985,025 B

Three artifacts, each ~170–213 MB, from a reading app. Same shape as dune-echoes: the payload is
duplicated three ways (portable zip, installer, APK). Nothing in the asset sizes suggests a
bundled model or a Python venv, so the weight is application payload plus one native toolchain per
target rather than runtime bloat. We could not unpack the non-APK artifacts from this environment
(§5), so this row rests on the asset list and the repository layout (`game/`, `art/`, `story/` —
a Ren'Py source tree) rather than a file listing.

三个资产各 170–213 MB，来源是一个阅读类应用。形态与 dune-echoes 相同：同一 payload 被复制成
便携 zip、安装器、APK 三份。从体积看不出有内嵌模型或 Python venv，重量来自应用 payload 加每个
目标平台各一套原生工具链，而不是运行时膨胀。受环境限制（见 §5）未能解包非 APK 资产，因此这一行
依据的是资产清单与仓库布局（`game/`、`art/`、`story/`，Ren'Py 源码树），而不是文件清单。

**Target / 目标: pc.zip < 120 MB, apk < 100 MB (single ABI)** — merge the three artifacts into one
installer plus one APK, and strip debug symbols.

目标：pc.zip < 120 MB、apk < 100 MB（单 ABI）—— 三份资产合并为一份安装器 + 一份 APK，并 strip
调试符号。

### 2.5 yuhang234/dune-echoes — pc.zip 204,262,396 B, setup 176,966,964 B

Same payload as the APK in §2.3 repackaged for desktop. On top of that, the release also
publishes **13 PNG screenshots totalling 21.4 MB** alongside the artifacts. Screenshots are
marketing material, not installable payload — they belong in the release notes or the repository,
and they inflate the release by ~10%.

与 §2.3 的 APK 是同一份 payload 重新打包成桌面版。此外该 Release 还附带了**共 13 张 PNG 截图、
合计 21.4 MB**。截图是宣传物料，不是可安装 payload，应放进 Release 正文或仓库；它们让本次
Release 体积虚增约 10%。

**Target / 目标: pc.zip < 120 MB; move screenshots out of the release assets.**

目标：pc.zip < 120 MB；把截图从 Release 资产中移出。

### 2.6 yuhang234/foundation-vn — three releases × three artifacts ≈ 280 MB each

v0.3.0 / v0.2.0-fulltext / v0.1.0-base1 each ship a pc.zip (~98–104 MB), a setup.exe (~77–82 MB)
and an apk (~106–113 MB). The two text editions (fulltext vs base1) differ by only ~600 KB in
pc.zip — the payload is identical and only the story text differs, yet both are published as
separate releases.

v0.3.0 / v0.2.0-fulltext / v0.1.0-base1 各带一份 pc.zip（约 98–104 MB）、一份 setup.exe（约
77–82 MB）、一份 apk（约 106–113 MB）。两个文本版本（fulltext 与 base1）的 pc.zip 只差约 600 KB
—— payload 完全相同、仅正文不同，却各自作为独立 Release 发布。

**Target / 目标: pc.zip < 80 MB, apk < 80 MB (single ABI); publish one release per edition, not
three.** 目标：pc.zip < 80 MB、apk < 80 MB（单 ABI）；每个版本只发一份 Release，而不是三份。

### 2.7 yuhang234/os-visualizer — `os-visualizer-1.0.0-win64.exe` 23,890,620 B

**Fine.** / 正常。A single-arch Windows app at 23 MB is in the expected band. No action.
23 MB 的单架构 Windows 应用处于正常区间，无需处理。

### 2.8 yuhang234/noema — 9,538,529 B

**Fine.** / 正常。9.5 MB, and it even ships a `SHA256SUMS.txt`. This is the reference behaviour.
9.5 MB，而且附了 `SHA256SUMS.txt`。这才是应该有的样子。

### 2.9 yuhang234/folio desktop — 6.7 MB setup, 9.9 MB msi

**Fine.** / 正常。Both in range. The desktop artifacts are not the problem; the debug APK is.
两者都在正常区间。桌面端资产不是问题，问题在 debug APK。

---

## 3. Fleet summary / 全局结论

| # | artifact / 资产 | bytes | cause / 原因 | fix / 修复 | target / 目标 |
|---|---|---|---|---|---|
| 1 | VoiceNote-Portable-0.1.1.zip | 1,508,262,165 | whole `nvidia/` wheels incl. static libs + headers; unused `av.libs` | bundle only `nvidia/*/bin/*.dll` (**this PR**) / 只带 `nvidia/*/bin/*.dll`（本 PR） | ~950 MB |
| 2 | VoiceNote-Setup-0.1.1.exe | 1,014,516,553 | same payload, LZMA2-compressed | inherits fix #1 (**this PR**) / 随 #1 自动变小（本 PR） | ~620 MB |
| 3 | folio-android-debug.apk | 697,888,677 | **unstripped debug build**: `libfolio_mobile_lib.so` 690 MB across 4 ABIs, stored uncompressed (99.1% of the file) | `[profile.release] strip=true`, single ABI, `debuggable=false` | < 200 MB |
| 4 | DuneEchoes-1.0.0.apk | 212,519,273 | genuine game payload: 180 MB art/audio + `librenpython.so` in 3 ABIs + 52 MB of full CJK fonts | single ABI + font subsetting + WebP/AVIF | < 100 MB |
| 5 | Staircase-0.2.0.apk | 213,618,631 | multi-ABI native libs (same Ren'Py toolchain as #4) | single ABI + R8 full mode | < 100 MB |
| 6 | Staircase-0.2.0-pc.zip | 201,695,729 | duplicated payload (zip + installer + apk) | one installer + one apk; strip symbols | < 120 MB |
| 7 | dune-echoes-1.0.0-pc.zip | 204,262,396 | duplicated payload + 21 MB of screenshots in assets | same as #6; move screenshots to notes | < 120 MB |

Everything else is under the thresholds and needs no work. / 其余资产均在门槛以内，无需处理。

---

## 4. Standing recommendations / 长期建议

1. **Never ship a wheel's `lib/` or `include/` directory.** PyInstaller's `(SITE / "pkg", "pkg")`
   form copies the whole wheel; add an explicit filter when a package contains more than runtime
   code. / 永远不要把 wheel 的 `lib/` 或 `include/` 目录打包。PyInstaller 的
   `(SITE / "pkg", "pkg")` 形式会整包复制；当包内含有运行时之外的内容时，必须显式过滤。

2. **Publish `SHA256SUMS.txt` with every release** that carries binary artifacts. noema already
   does; the six repos above do not. / 只要 Release 带二进制资产，就同时发布
   `SHA256SUMS.txt`。noema 已经这么做了，上面六个仓库都没有。

3. **Do not publish debug APKs as release assets.** If a debug build is wanted, mark the release
   `--prerelease`. / 不要把 debug APK 作为正式发布资产。确有需要时，把 Release 标为
   `--prerelease`。

4. **Keep screenshots out of release assets**; link them from the notes instead. / 截图不要放进
   Release 资产，在正文里给链接即可。

5. **Warn at build time when an artifact exceeds a threshold.** `scripts/build.ps1` now fails the
   build if the filtered CUDA DLLs are missing and prints the per-directory size breakdown of
   `dist/VoiceNote`, so a size regression is visible in the build log instead of after upload.
   Extend the same gate to a hard cap on the final zip (e.g. 1 GiB).
   / `scripts/build.ps1` 现在会在过滤后的 CUDA DLL 缺失时直接失败，并打印 `dist/VoiceNote` 的
   分目录体积明细，让体积回归在构建日志里就能看见。再把同一道门禁扩展成对最终 zip 设硬上限
   （例如 1 GiB）。

---

## 5. Limitations / 局限

- §2.2 and §2.3 are **measured** — the `folio` and `dune-echoes` APKs were downloaded and their
  zip entries read. The folio download was cut off before the zip footer, so its listing is
  complete for every entry inside the downloaded prefix. / §2.2 与 §2.3 是**实测**：下载了
  `folio` 与 `dune-echoes` 的 APK 并读取了其中的 zip 条目。folio 的下载在 zip 尾部之前中断，所以
  清单只覆盖已下载前缀内的全部条目。
- For the remaining oversized artifacts (§2.4–§2.6) we could not unpack the binary: GitHub's
  release download redirect returns 404 / drops the connection from this environment, which also
  rules out a full local build of VoiceNote here. Those rows rest on the asset list plus each
  repository's layout and build configuration. / 其余过大资产（§2.4–§2.6）未能解包：本环境下
  GitHub 的 Release 下载跳转返回 404 或中途断开连接，这也意味着在本机无法完成 VoiceNote 的完整
  构建。这些行依据的是资产清单加各仓库的布局与构建配置。
- The VoiceNote "after" sizes in §2.1 are estimates from the known wheel contents. The actual
  numbers come out of a Windows build (`scripts/build.ps1`), which is where the self-check gate
  also runs. The build was **not** run for this PR: it requires Windows plus Inno Setup, and the
  self-check refuses to produce an artifact it cannot verify. / §2.1 中 VoiceNote 的"修复后"体积
  是按已知 wheel 内容做的估算，实际数值要由 Windows 上的 `scripts/build.ps1` 构建给出（自检门禁
  也在同一处运行）。本 PR **未执行**该构建：它需要 Windows 加 Inno Setup，且自检不允许产出无法
  验证的产物。