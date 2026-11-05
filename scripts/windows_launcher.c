/* Native Windows x64 entry point. Launch only the adjacent offline runtime.
 * Cross-compiled with Zig 0.14.1; execution still needs Windows acceptance.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t root[32768], python[32768], script[32768], command[32768];
    DWORD length = GetModuleFileNameW(NULL, root, 32768);
    if (!length || length >= 32768) return 1;
    wchar_t *separator = wcsrchr(root, L'\\');
    if (!separator) return 1;
    *separator = 0;
    if (wcslen(root) * 2 + wcslen(args) + 120 >= 32768) return 1;
    swprintf(python, 32768, L"%ls\\runtime\\pythonw.exe", root);
    swprintf(script, 32768, L"%ls\\launch_mathbank.py", root);
    swprintf(command, 32768, L"\"%ls\" -I \"%ls\" %ls", python, script, args);
    STARTUPINFOW startup = {0}; startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, root, &startup, &process)) {
        MessageBoxW(NULL,
            L"MathBank runtime could not start. Extract the whole ZIP first.\n"
            L"Check runtime/pythonw.exe and Windows 11 x64 compatibility.",
            L"MathBank Desktop", MB_OK | MB_ICONERROR);
        return 1;
    }
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1; GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    if (code) MessageBoxW(NULL,
        L"MathBank exited with an error. Check startup-error.log in\n"
        L"%LOCALAPPDATA%/MathBankDesktop. Run VERIFY_WINDOWS.cmd for diagnostics.",
        L"MathBank Desktop", MB_OK | MB_ICONERROR);
    return (int)code;
}
