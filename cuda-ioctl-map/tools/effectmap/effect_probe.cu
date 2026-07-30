/*
 * effect_probe.cu — Experiment A3: hold one CUDA operation open while the
 * state vector is swept.
 *
 * The existing corpus under programs/ performs an operation and exits. That is
 * right for capturing an ioctl trace, but wrong for a state delta: the driver
 * tears the process down, so a snapshot taken afterwards sees the original
 * state and every effect measures as zero.
 *
 * This program instead performs the operation, prints READY, and blocks until
 * a line arrives on stdin. The driver script sweeps while it is blocked, so
 * the snapshot observes the GPU with the operation still in force.
 *
 * Build:  nvcc -arch=native -O0 -lcuda -o effect_probe effect_probe.cu
 * Usage:  ./effect_probe <op>
 *
 * Ops (each is cumulative on the one before, which is what makes the
 * rung-to-rung diff attributable to exactly one new operation):
 *   baseline      nothing at all — measures the harness itself
 *   cuinit        cuInit(0)
 *   ctx_create    + cuCtxCreate
 *   mem_1m        + cuMemAlloc(1 MiB)
 *   mem_2g        + cuMemAlloc(2 GiB)      <- the A4 correctness check
 *   stream        + cuStreamCreate
 *   module        + cuModuleLoadData(empty PTX)
 *   launch        + cuLaunchKernel of a null kernel
 */

#include <cuda.h>
#include <stdio.h>
#include <string.h>

/* Minimal valid PTX holding one empty kernel. */
static const char *kNullPtx =
    ".version 6.0\n"
    ".target sm_50\n"
    ".address_size 64\n"
    ".visible .entry nullk()\n"
    "{\n"
    "    ret;\n"
    "}\n";

static int fail(const char *what, CUresult r)
{
    const char *msg = NULL;
    cuGetErrorString(r, &msg);
    fprintf(stderr, "FAILED %s: %s\n", what, msg ? msg : "?");
    return 1;
}

#define TRY(call, what)                                    \
    do {                                                   \
        CUresult _r = (call);                              \
        if (_r != CUDA_SUCCESS) return fail((what), _r);   \
    } while (0)

int main(int argc, char **argv)
{
    const char *op = (argc > 1) ? argv[1] : "baseline";

    int want_init   = strcmp(op, "baseline") != 0;
    int want_ctx    = !strcmp(op, "ctx_create") || !strcmp(op, "mem_1m")
                   || !strcmp(op, "mem_2g")     || !strcmp(op, "stream")
                   || !strcmp(op, "module")     || !strcmp(op, "launch");
    int want_mem1m  = !strcmp(op, "mem_1m");
    int want_mem2g  = !strcmp(op, "mem_2g");
    int want_stream = !strcmp(op, "stream");
    int want_module = !strcmp(op, "module") || !strcmp(op, "launch");
    int want_launch = !strcmp(op, "launch");

    CUcontext  ctx = NULL;
    CUdeviceptr ptr = 0;
    CUstream   stream = NULL;
    CUmodule   mod = NULL;

    if (want_init)   TRY(cuInit(0), "cuInit");

    if (want_ctx) {
        CUdevice dev;
        TRY(cuDeviceGet(&dev, 0), "cuDeviceGet");
        TRY(cuCtxCreate(&ctx, 0, dev), "cuCtxCreate");
    }
    if (want_mem1m)  TRY(cuMemAlloc(&ptr, 1ull << 20), "cuMemAlloc(1MiB)");
    if (want_mem2g)  TRY(cuMemAlloc(&ptr, 2ull << 30), "cuMemAlloc(2GiB)");
    if (want_stream) TRY(cuStreamCreate(&stream, CU_STREAM_DEFAULT), "cuStreamCreate");
    if (want_module) TRY(cuModuleLoadData(&mod, kNullPtx), "cuModuleLoadData");

    if (want_launch) {
        CUfunction fn;
        TRY(cuModuleGetFunction(&fn, mod, "nullk"), "cuModuleGetFunction");
        TRY(cuLaunchKernel(fn, 1, 1, 1, 1, 1, 1, 0, NULL, NULL, NULL), "cuLaunchKernel");
        TRY(cuCtxSynchronize(), "cuCtxSynchronize");
    }

    /* Hold the state open for the sweeper. */
    printf("READY\n");
    fflush(stdout);

    char line[64];
    if (!fgets(line, sizeof(line), stdin)) { /* parent closed the pipe */ }

    if (mod)    cuModuleUnload(mod);
    if (stream) cuStreamDestroy(stream);
    if (ptr)    cuMemFree(ptr);
    if (ctx)    cuCtxDestroy(ctx);
    return 0;
}
