// ftlog.dylib — present-interval probe for Metal renderers (mtld3d, DXMT, ...).
// Loaded into wine via DYLD_INSERT_LIBRARIES. Inert unless FTLOG_DIR is set;
// then every -[CAMetalLayer nextDrawable] (one per presented frame) appends a
// monotonic nanosecond timestamp to $FTLOG_DIR/ftlog-<pid>.txt. Frame times
// are the deltas. Build: see Makefile (universal: x86_64 wine under Rosetta,
// arm64 x87sidecar).
#import <QuartzCore/CAMetalLayer.h>
#import <objc/runtime.h>
#include <mach/mach_time.h>
#include <os/lock.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static IMP g_orig;
static FILE *g_out;
static mach_timebase_info_data_t g_tb;
static os_unfair_lock g_lock = OS_UNFAIR_LOCK_INIT;

static id ftlog_next_drawable(id self, SEL cmd) {
    uint64_t now = mach_absolute_time() * g_tb.numer / g_tb.denom;
    os_unfair_lock_lock(&g_lock);
    if (!g_out) {
        char path[1024];
        snprintf(path, sizeof path, "%s/ftlog-%d.txt", getenv("FTLOG_DIR"), getpid());
        g_out = fopen(path, "a");
        // Line-buffered: each frame is on disk as soon as it is logged, so the
        // bench's growth check and window slicing see current data at any FPS.
        if (g_out) setvbuf(g_out, NULL, _IOLBF, 0);
    }
    if (g_out) fprintf(g_out, "%llu\n", (unsigned long long)now);
    os_unfair_lock_unlock(&g_lock);
    return ((id (*)(id, SEL))g_orig)(self, cmd);
}

__attribute__((constructor)) static void ftlog_init(void) {
    if (!getenv("FTLOG_DIR")) return;
    mach_timebase_info(&g_tb);
    Method m = class_getInstanceMethod([CAMetalLayer class], @selector(nextDrawable));
    if (m) g_orig = method_setImplementation(m, (IMP)ftlog_next_drawable);
}
