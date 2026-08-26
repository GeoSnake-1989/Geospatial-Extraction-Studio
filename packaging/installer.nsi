Unicode True
RequestExecutionLevel user
SetCompressor zlib

!include "MUI2.nsh"

!ifndef APP_SOURCE
  !error "APP_SOURCE must identify the PyInstaller onedir output"
!endif
!ifndef OUTPUT_FILE
  !error "OUTPUT_FILE must identify the installer executable"
!endif
!ifndef APP_VERSION
  !define APP_VERSION "0.4.5"
!endif
!ifndef LICENSE_FILE
  !error "LICENSE_FILE must identify the project Apache-2.0 license"
!endif

Name "Geospatial Extraction Studio"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\Geospatial Extraction Studio"
InstallDirRegKey HKCU "Software\Geospatial Extraction Studio" "InstallDir"
BrandingText "Geospatial Extraction Studio ${APP_VERSION}"

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "Geospatial Extraction Studio"
VIAddVersionKey "FileDescription" "Geospatial Extraction Studio installer"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "See the installed LICENSE, NOTICE, and third-party license bundle"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\GeospatialExtractionStudio.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch Geospatial Extraction Studio"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Application" SecApplication
  SetOutPath "$INSTDIR"
  File /r "${APP_SOURCE}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Geospatial Extraction Studio" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "DisplayName" "Geospatial Extraction Studio"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "DisplayIcon" "$INSTDIR\GeospatialExtractionStudio.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio" "NoRepair" 1
  CreateDirectory "$SMPROGRAMS\Geospatial Extraction Studio"
  CreateShortcut "$SMPROGRAMS\Geospatial Extraction Studio\Geospatial Extraction Studio.lnk" "$INSTDIR\GeospatialExtractionStudio.exe"
  CreateShortcut "$SMPROGRAMS\Geospatial Extraction Studio\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\Geospatial Extraction Studio\Geospatial Extraction Studio.lnk"
  Delete "$SMPROGRAMS\Geospatial Extraction Studio\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Geospatial Extraction Studio"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Geospatial Extraction Studio"
  DeleteRegKey HKCU "Software\Geospatial Extraction Studio"
  RMDir /r "$INSTDIR"
  ; User-created datasets remain under $LOCALAPPDATA\Geospatial Extraction Studio.
SectionEnd
