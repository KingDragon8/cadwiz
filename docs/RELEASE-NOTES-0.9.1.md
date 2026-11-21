# CADWiz Beta 0.9.1

Install CADWiz first; choose your AI inside FreeCAD.

- AIWiz now has AI Wiz Setup and AI Wiz Management tabs. New or unverified connections land in Setup; a recorded successful assistant handshake selects Management on later launches. Set up later returns to the model without discarding work.
- Claude Desktop and OpenAI / Codex use existing explicit connection paths. Other AI shows support status. Free AIWiz retains seven API-account enrollment options, clearly separated from CAD-ready assistant connections.
- Direct free-provider CAD requests and automatic switching remain disabled. No account, quota, or paid-service access is assumed.
- Windows Setup defaults to opening FreeCAD; the shared panel opens AI Wiz Setup without a separate navigation step. Existing safety checks still require saving work and closing FreeCAD for installation. No extra GUI is launched if FreeCAD is already open.
- macOS/Linux retain Addon Manager/manual installation and require restarting FreeCAD. They share the panel navigation code, not the Windows executable. A real Mac GUI/device install is not claimed.
- The website detects the operating system, provides a Change override and one matching primary download, and no longer asks which AI to use. Windows instructions explicitly name the downloaded executable and Downloads folder.

The Windows installer remains unsigned. Windows security software may warn or block it; signing is not replaced by checksums. FreeCAD 1.1+ with the bundled Python 3.11 helper platform is required. General file/Cura control requires separate tools and permissions. Retain FreeCAD Python until graphical uninstall is complete.

Release checks include platform-independent first-run state simulations, corrupt-state recovery, real Qt layout/route checks at multiple panel sizes, responsive website/OS simulations, packaged native FreeCAD 1.1.4 install/upgrade/uninstall/recovery, source checks on Windows/macOS/Linux, and actual local FreeCAD GUI communication/model checks. The delivery audit distinguishes tests actually run from unverified scenarios and external account enrollment.
