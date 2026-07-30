; ================================================================
;  vibe programs - SHARED install convention (Inno Setup 6, ISPP)
;  ----------------------------------------------------------------
;  All vibe (VibeVendor) programs install the SAME way by including
;  this file from inside the [Setup] section of each program's .iss.
;
;  Before the #include line, each program's .iss must define:
;     VibeVendor    - vendor / Start-menu group (Korean value in the .iss)
;     MyAppNameEN   - ASCII folder/leaf name (e.g. vibe-blogpost-free)
;     MyAppName     - display name (Korean OK)
;     MyAppExeName  - main exe file name
;     MyAppVersion  - version string
;  ...and its own UNIQUE AppId (never shared between programs).
;
;  This file is ASCII-only on purpose: the only vendor/Korean value
;  (VibeVendor) is supplied by the including .iss, which carries a
;  UTF-8 BOM. Keep this file free of non-ASCII characters.
;
;  Canonical spec: see the Claude project doc for the vibe install rule.
; ================================================================

; --- Publisher / links (whole vibe family) ---
AppPublisher={#VibeVendor}
AppPublisherURL=https://github.com/samho4987-rgb
AppSupportURL=https://github.com/samho4987-rgb
AppUpdatesURL=https://github.com/samho4987-rgb

; --- Install location: gather every vibe program under ONE parent ---
;   lowest privileges => {autopf} = C:\Users\<name>\AppData\Local\Programs
;   => C:\Users\<name>\AppData\Local\Programs\<VibeVendor>\<MyAppNameEN>
DefaultDirName={autopf}\{#VibeVendor}\{#MyAppNameEN}

; --- Start-menu group: ONE folder shared by all vibe programs ---
DefaultGroupName={#VibeVendor}
DisableProgramGroupPage=yes

; --- Per-user install (no UAC) so all programs land in the same base ---
PrivilegesRequired=lowest

; --- Architecture / packaging (shared defaults) ---
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
