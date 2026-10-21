# Third-party components

- The bundled TCL-adapted launcher is derived from **CleanYourTV**, https://github.com/Gathin23/cleanyourtv, commit `f2a336a62965832daad607fa288e1d8f1de528d4`. Copyright (c) 2026 Gathin, MIT. Its license is included at `skills/tv-setup/assets/licenses/CleanYourTV-MIT.txt`; the source changes are at `skills/tv-setup/assets/oem/cleanyourtv-tcl.patch`. This is a locally adapted build, not the upstream publisher's release. The original build signing key is not distributed.
- The launcher uses AndroidX RecyclerView 1.3.2, DynamicAnimation 1.0.0 and their AndroidX dependencies, under Apache License 2.0. See `skills/tv-setup/assets/licenses/Apache-2.0.txt`; component sources are available from https://android.googlesource.com/platform/frameworks/support/.
- The launcher includes the **Outfit** font, Copyright The Outfit Project Authors, SIL Open Font License 1.1. See `skills/tv-setup/assets/licenses/Outfit-OFL.txt`.
- `TvInstallConfigTool.java` and the accompanying DEX JAR are supplied with this package under the root MIT license. They require an already authorized Android shell and a specifically reviewed OEM Provider; they do not grant root access.
- SmartTube F-Droid, Mihomo and MetaCubeX rule artifacts are **not bundled**. The tool downloads explicitly selected, hash-pinned artifacts from their upstream repositories. Their licenses, notices and upstream terms continue to apply; this package does not relicense them. See the source URLs in `skills/tv-setup/assets/artifacts.json`.
- Google platform-tools, Android SDK, firmware images, reverse-engineering applications and user proxy providers are not bundled.

Generated router runtime bundles include customer-provided provider data and generated secrets and are private operational outputs, not distributable software releases. Do not include them when redistributing this toolkit.
