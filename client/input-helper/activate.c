// activate.exe — bring the GAME's window to the foreground from inside wine.
// Enumerates ALL top-level windows (any process), picks the largest visible
// one owned by a *different* wine process (the game runs as its own process
// from the launcher), and calls SetForegroundWindow on it.
// Usage: activate.exe [title-substring]  (default: largest foreign window)
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND g_best = NULL;
static LONG g_best_area = 0;
static char g_title_sub[256] = {0};

static BOOL CALLBACK enumcb(HWND hwnd, LPARAM lp) {
    char title[256] = {0};
    char cls[64] = {0};
    if (!IsWindowVisible(hwnd)) return TRUE;
    HWND owner = GetWindow(hwnd, GW_OWNER);
    if (owner) return TRUE;
    LONG ex = GetWindowLongW(hwnd, GWL_EXSTYLE);
    if (ex & WS_EX_TOOLWINDOW) return TRUE;
    DWORD wpid = 0;
    GetWindowThreadProcessId(hwnd, &wpid);
    if (wpid == GetCurrentProcessId()) return TRUE; /* skip self */
    RECT r; if (!GetWindowRect(hwnd, &r)) return TRUE;
    LONG area = (r.right-r.left) * (r.bottom-r.top);
    if (area > g_best_area) {
        if (g_title_sub[0]) {
            GetWindowTextA(hwnd, title, sizeof(title));
            if (!strstr(title, g_title_sub)) return TRUE;
        }
        g_best_area = area;
        g_best = hwnd;
    }
    return TRUE;
}

int main(int argc, char **argv) {
    if (argc > 1 && argv[1][0]) strncpy(g_title_sub, argv[1], sizeof(g_title_sub)-1);
    EnumWindows(enumcb, 0);
    if (!g_best) { printf("NO_WINDOW\n"); return 1; }
    char title[256] = {0};
    GetWindowTextA(g_best, title, sizeof(title));
    LONG ex = GetWindowLongW(g_best, GWL_EXSTYLE);
    /* Alt-key hack: attach thread input so SetForegroundWindow is permitted */
    keybd_event(VK_MENU, 0, 0, 0);
    SetForegroundWindow(g_best);
    SetFocus(g_best);
    keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0);
    printf("ACTIVATED %p pid-watched title='%s' area=%ld exstyle=0x%lx\n",
           (void*)g_best, title, g_best_area, (unsigned long)ex);
    fflush(stdout);
    return 0;
}
