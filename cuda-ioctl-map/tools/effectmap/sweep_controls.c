/*
 * sweep_controls.c — Experiment A1: the state-vector sweeper.
 *
 * Builds the minimal RM object ladder by hand — no libcuda, no LD_PRELOAD —
 * then issues NV_ESC_RM_CONTROL for every command in a list and records what
 * came back. The result is one "state vector": the readable configuration of
 * the GPU at a point in time.
 *
 *   open("/dev/nvidiactl")
 *     -> NV_ESC_RM_ALLOC  hClass=0x0000  NV01_ROOT         => hClient
 *     -> NV_ESC_RM_ALLOC  hClass=0x0080  NV01_DEVICE_0     => hDevice
 *     -> NV_ESC_RM_ALLOC  hClass=0x2080  NV20_SUBDEVICE_0  => hSubDevice
 *     -> NV_ESC_RM_CONTROL(cmd, size) for each command
 *
 * The ladder is not guessed. It was read out of sniffed/cu_init.jsonl, where
 * libcuda performs exactly this sequence (seq 0-13).
 *
 * Escape numbers come from nv_escape.h with magic 'F' (0x46):
 *   NV_ESC_RM_ALLOC   = 0x2B    NV_ESC_RM_CONTROL = 0x2A
 *   NV_ESC_RM_FREE    = 0x29    NV_ESC_CARD_INFO  = 0xD6
 * Note: lookup/ioctl_table.json in this repo names these wrongly. Do not use it.
 *
 * Build: gcc -O2 -Wall -Wextra -o sweep_controls sweep_controls.c
 *
 * Usage:
 *   ./sweep_controls --cmds cmds.txt --out state_vector.jsonl [--gpu N]
 *                    [--probe-mode normal|badsize|badobject|badboth]
 *
 * cmds.txt: one "0xCMD <paramsSize>" per line, '#' comments allowed.
 *
 * Output: JSON lines, one per command:
 *   {"cmd":"0x...","size":N,"ret":r,"errno":e,"status":"0x...","resp":"<hex>"}
 *
 * Safety: this issues only the commands it is given. Feed it GET commands.
 * gen_sweep_list.py applies the read-only filter.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

/* ── NVIDIA UAPI structs (from sdk/nvidia/inc/nvos.h) ── */

typedef struct {
    uint32_t hRoot;
    uint32_t hObjectParent;
    uint32_t hObjectNew;
    int32_t  hClass;
    uint64_t pAllocParms __attribute__((aligned(8)));
    uint32_t paramsSize;
    int32_t  status;
} NVOS21_PARAMETERS;                       /* 32 bytes */

typedef struct {
    uint32_t hRoot;
    uint32_t hObjectParent;
    uint32_t hObjectNew;
    int32_t  hClass;
    uint64_t pAllocParms      __attribute__((aligned(8)));
    uint64_t pRightsRequested __attribute__((aligned(8)));
    uint32_t paramsSize;
    uint32_t flags;
    int32_t  status;
} NVOS64_PARAMETERS;                       /* 48 bytes */

typedef struct {
    uint32_t hClient;
    uint32_t hObject;
    int32_t  cmd;
    uint32_t flags;
    uint64_t params __attribute__((aligned(8)));
    uint32_t paramsSize;
    int32_t  status;
} NVOS54_PARAMETERS;                       /* 32 bytes */

typedef struct {
    uint32_t deviceId;
    uint32_t hClientShare;
    uint32_t hTargetClient;
    uint32_t hTargetDevice;
    int32_t  flags;
    uint64_t vaSpaceSize    __attribute__((aligned(8)));
    uint64_t vaStartInternal __attribute__((aligned(8)));
    uint64_t vaLimitInternal __attribute__((aligned(8)));
    int32_t  vaMode;
} NV0080_ALLOC_PARAMETERS;

typedef struct {
    uint32_t subDeviceId;
} NV2080_ALLOC_PARAMETERS;

/* ── escape codes: _IOWR('F', nr, struct) ── */
#define NV_IOWR(nr, type)  _IOWR('F', (nr), type)
#define ESC_RM_ALLOC_21    NV_IOWR(0x2B, NVOS21_PARAMETERS)   /* 0xC020462B */
#define ESC_RM_ALLOC_64    NV_IOWR(0x2B, NVOS64_PARAMETERS)   /* 0xC030462B */
#define ESC_RM_CONTROL     NV_IOWR(0x2A, NVOS54_PARAMETERS)   /* 0xC020462A */

#define CLASS_NV01_ROOT        0x0000
#define CLASS_NV01_DEVICE_0    0x0080
#define CLASS_NV20_SUBDEVICE_0 0x2080

/* A command with a bogus object handle still has to pass the paramsSize check
 * first (control.c rejects a size mismatch before it resolves the object), so
 * the three probe modes below produce three distinguishable status codes. */
enum probe_mode { PROBE_NORMAL, PROBE_BADSIZE, PROBE_BADOBJECT, PROBE_BADBOTH };

#define MAX_CMDS      8192
#define MAX_PARAM_SZ  (1u << 20)   /* 1 MiB cap; largest real struct is ~64 KiB */

/*
 * Many NVIDIA GET controls are request-driven: the caller writes the indices it
 * wants into the params buffer and the driver fills in the values. Sweeping
 * with an all-zero buffer asks for nothing, so those commands either return
 * NV_ERR_INVALID_ARGUMENT or hand back a buffer of zeros that never changes.
 * FB_GET_INFO_V2 is the clearest case: zeroed it fails outright, but with three
 * indices filled in it reports free framebuffer and tracks a 2 GiB allocation
 * exactly. A prefill lets the command list carry that request template.
 */
/*
 * Request-template caps. Three numbers must stay in step:
 *   MAX_PREFILL    bytes of template we store
 *   MAX_HEX_CHARS  hex characters that encode them, exactly 2x
 *   HEX_SCAN_FMT   the sscanf field width, one past the legal maximum so a
 *                  too-long field is detectable instead of silently truncated
 *
 * The static assert catches the first two drifting. The field width has to be
 * a literal, because the preprocessor cannot stringify an expression into a
 * scanf conversion, so it is spelled out and guarded by the assert below it.
 *
 * Raised from 512 on 2026-08-06. The 610 SDK declares
 * NV2080_CTRL_FB_INFO_MAX_LIST_SIZE = 128, a 1028-byte struct. The old cap
 * silently dropped any template that large and swept with a zeroed buffer
 * instead, which reads nothing. See code.md finding E2 at commit aaf7d18.
 */
#define MAX_PREFILL    2048
#define MAX_HEX_CHARS  4096
#define HEX_SCAN_FMT   "%lx %lu %4097s"
_Static_assert(MAX_HEX_CHARS == 2 * MAX_PREFILL,
               "MAX_HEX_CHARS must be exactly 2 * MAX_PREFILL");

/* Templates that could not be used. Non-zero fails the run; see main(). */
static int g_template_errors;

struct cmd_entry {
    uint32_t cmd;
    uint32_t size;
    uint32_t prefill_len;
    uint8_t  prefill[MAX_PREFILL];
};

static int    g_fd = -1;
static uint32_t g_hClient, g_hDevice, g_hSubDevice;

static int rm_alloc21(uint32_t hRoot, uint32_t hParent, int32_t hClass,
                      void *parms, uint32_t psz, uint32_t *out_handle)
{
    NVOS21_PARAMETERS a;
    memset(&a, 0, sizeof(a));
    a.hRoot = hRoot;
    a.hObjectParent = hParent;
    a.hObjectNew = 0;
    a.hClass = hClass;
    a.pAllocParms = (uint64_t)(uintptr_t)parms;
    a.paramsSize = psz;

    if (ioctl(g_fd, ESC_RM_ALLOC_21, &a) < 0) {
        fprintf(stderr, "[sweep] RM_ALLOC(class=0x%04x) ioctl: %s\n",
                hClass, strerror(errno));
        return -1;
    }
    if (a.status != 0) {
        fprintf(stderr, "[sweep] RM_ALLOC(class=0x%04x) status=0x%08x\n",
                hClass, a.status);
        return -1;
    }
    *out_handle = a.hObjectNew;
    return 0;
}

static int rm_alloc64(uint32_t hRoot, uint32_t hParent, int32_t hClass,
                      void *parms, uint32_t psz, uint32_t *out_handle)
{
    NVOS64_PARAMETERS a;
    memset(&a, 0, sizeof(a));
    a.hRoot = hRoot;
    a.hObjectParent = hParent;
    a.hObjectNew = 0;
    a.hClass = hClass;
    a.pAllocParms = (uint64_t)(uintptr_t)parms;
    a.paramsSize = psz;

    if (ioctl(g_fd, ESC_RM_ALLOC_64, &a) < 0) {
        fprintf(stderr, "[sweep] RM_ALLOC64(class=0x%04x) ioctl: %s\n",
                hClass, strerror(errno));
        return -1;
    }
    if (a.status != 0) {
        fprintf(stderr, "[sweep] RM_ALLOC64(class=0x%04x) status=0x%08x\n",
                hClass, a.status);
        return -1;
    }
    *out_handle = a.hObjectNew;
    return 0;
}

/* Issue one RM control. Returns the RM status; -1 if the ioctl itself failed. */
static int rm_control(uint32_t hObject, uint32_t cmd, void *params, uint32_t size)
{
    NVOS54_PARAMETERS c;
    memset(&c, 0, sizeof(c));
    c.hClient    = g_hClient;
    c.hObject    = hObject;
    c.cmd        = (int32_t)cmd;
    c.params     = size ? (uint64_t)(uintptr_t)params : 0;
    c.paramsSize = size;

    if (ioctl(g_fd, ESC_RM_CONTROL, &c) < 0)
        return -1;
    return c.status;
}

#define NV_MAX_DEVICES               32
#define CTRL_GPU_GET_PROBED_IDS      0x00000214
#define CTRL_GPU_ATTACH_IDS          0x00000215
#define GPU_INVALID_ID               0xFFFFFFFFu

/*
 * Build hClient -> hDevice -> hSubDevice.
 *
 * The device allocation fails with NV_ERR_INSUFFICIENT_PERMISSIONS (0x1B)
 * unless the GPU is attached to this client first. libcuda does this with
 * GET_PROBED_IDS then ATTACH_IDS, and then opens /dev/nvidiaN — see
 * sniffed/cu_init.jsonl seq 19-27. Reproduce that order exactly.
 */
static int build_ladder(unsigned gpu_index)
{
    g_fd = open("/dev/nvidiactl", O_RDWR);
    if (g_fd < 0) {
        fprintf(stderr, "[sweep] open /dev/nvidiactl: %s\n", strerror(errno));
        return -1;
    }

    if (rm_alloc21(0, 0, CLASS_NV01_ROOT, NULL, 0, &g_hClient) != 0)
        return -1;

    /*
     * GET_PROBED_IDS is 2 arrays (256 B) on driver 555 and 3 arrays (384 B)
     * on the vendored 610 headers. The driver rejects the wrong size, so ask
     * it which one it wants rather than trusting the header.
     */
    uint32_t probed[3 * NV_MAX_DEVICES];
    uint32_t probe_sizes[2] = {2 * NV_MAX_DEVICES * 4, 3 * NV_MAX_DEVICES * 4};
    int got = -1;
    for (int i = 0; i < 2; i++) {
        memset(probed, 0, sizeof(probed));
        int st = rm_control(g_hClient, CTRL_GPU_GET_PROBED_IDS,
                            probed, probe_sizes[i]);
        if (st == 0) {
            fprintf(stderr, "[sweep] GET_PROBED_IDS accepted size %u\n",
                    probe_sizes[i]);
            got = 0;
            break;
        }
    }
    if (got != 0) {
        fprintf(stderr, "[sweep] GET_PROBED_IDS failed at both sizes\n");
        return -1;
    }

    int nprobed = 0;
    while (nprobed < NV_MAX_DEVICES && probed[nprobed] != GPU_INVALID_ID
           && probed[nprobed] != 0)
        nprobed++;
    fprintf(stderr, "[sweep] %d GPU(s) probed; first gpuId=0x%08x\n",
            nprobed, nprobed ? probed[0] : 0);
    if (gpu_index >= (unsigned)nprobed) {
        fprintf(stderr, "[sweep] --gpu %u out of range (%d probed)\n",
                gpu_index, nprobed);
        return -1;
    }

    /* ATTACH_IDS: gpuIds[NV_MAX_DEVICES] then failedId. 33 * 4 = 132 bytes,
     * which matches what libcuda sends on this driver. */
    uint32_t attach[NV_MAX_DEVICES + 1];
    memset(attach, 0, sizeof(attach));
    attach[0] = probed[gpu_index];
    attach[1] = GPU_INVALID_ID;
    int st = rm_control(g_hClient, CTRL_GPU_ATTACH_IDS,
                        attach, sizeof(attach));
    if (st != 0) {
        fprintf(stderr, "[sweep] ATTACH_IDS status=0x%08x\n", st);
        return -1;
    }

    /* libcuda opens the per-GPU node here; the attach is not complete without
     * it. Keep the fd open for the life of the sweep. */
    char node[32];
    snprintf(node, sizeof(node), "/dev/nvidia%u", gpu_index);
    int gfd = open(node, O_RDWR);
    if (gfd < 0)
        fprintf(stderr, "[sweep] warning: open %s: %s\n", node, strerror(errno));

    NV0080_ALLOC_PARAMETERS dev;
    memset(&dev, 0, sizeof(dev));
    dev.deviceId     = gpu_index;
    dev.hClientShare = g_hClient;
    if (rm_alloc64(g_hClient, g_hClient, CLASS_NV01_DEVICE_0,
                   &dev, sizeof(dev), &g_hDevice) != 0)
        return -1;

    NV2080_ALLOC_PARAMETERS sub;
    memset(&sub, 0, sizeof(sub));
    sub.subDeviceId = 0;
    if (rm_alloc64(g_hClient, g_hDevice, CLASS_NV20_SUBDEVICE_0,
                   &sub, sizeof(sub), &g_hSubDevice) != 0)
        return -1;

    fprintf(stderr,
            "[sweep] ladder ok: hClient=0x%08x hDevice=0x%08x hSubDevice=0x%08x\n",
            g_hClient, g_hDevice, g_hSubDevice);
    return 0;
}

/* Choose the object a command is routed to, from its class (high 16 bits). */
static uint32_t object_for_cmd(uint32_t cmd)
{
    uint32_t klass = (cmd >> 16) & 0xFFFF;
    switch (klass) {
    case 0x0000: return g_hClient;      /* NV01_ROOT        */
    case 0x0080: return g_hDevice;      /* NV01_DEVICE_0    */
    case 0x2080: return g_hSubDevice;   /* NV20_SUBDEVICE_0 */
    default:     return g_hSubDevice;   /* best effort      */
    }
}

/*
 * Size scan — recover the driver's own paramsSize for each command.
 *
 * control.c:445-456 looks the command up in the NVOC export table and compares
 * paramsSize against the compiled-in paramSize *before* it resolves the object
 * or touches the GPU. So:
 *
 *   NV_ERR_NOT_SUPPORTED   (0x56) -> command is not in this driver at all
 *   NV_ERR_INVALID_ARGUMENT(0x1F) -> command exists, this size is wrong
 *   anything else                 -> this size is the one the driver expects
 *
 * Scanning therefore reads the true 555 ABI size straight out of the shipped
 * binary, with no header involved. It is also safe on write commands: a wrong
 * size is rejected before the handler runs, and the scan stops at the first
 * accepted size rather than issuing it a second time.
 */
static int run_size_scan(const struct cmd_entry *cmds, int ncmds,
                         const char *out_path, uint32_t max_size)
{
    FILE *out = fopen(out_path, "w");
    if (!out) {
        fprintf(stderr, "[sweep] open %s: %s\n", out_path, strerror(errno));
        return 1;
    }
    uint8_t *buf = calloc(1, max_size + 8);
    if (!buf) return 1;

    for (int i = 0; i < ncmds; i++) {
        uint32_t cmd = cmds[i].cmd;

        /*
         * Presence needs a *real* object. With a bogus handle an absent command
         * also stops at object resolution (0x57), which hides the 0x56 that
         * distinguishes "not in this driver". So: real object for presence,
         * bogus object for the size scan below.
         */
        int st_probe = rm_control(object_for_cmd(cmd), cmd, buf, max_size + 7);
        if (st_probe == 0x56) {
            fprintf(out,
                    "{\"cmd\":\"0x%08X\",\"present\":false,\"found_size\":null,"
                    "\"probe_status\":\"0x%08X\"}\n", cmd, 0x56);
            continue;
        }

        /*
         * Scan against a handle that cannot resolve.
         *
         * NV_ERR_INVALID_ARGUMENT (0x1F) is overloaded: the size check emits it,
         * but so does a handler that dislikes an all-zero params buffer. Running
         * the scan on a real object therefore cannot tell "wrong size" from
         * "right size, unhappy handler", and it silently under-reports.
         *
         * A bogus hObject removes the ambiguity, because the size check at
         * control.c:450 runs before object resolution at line 516:
         *
         *   wrong size  -> 0x1F NV_ERR_INVALID_ARGUMENT  (size check)
         *   right size  -> 0x57 NV_ERR_OBJECT_NOT_FOUND  (resolution)  <- accept
         *
         * The handler never executes, so this is safe on write commands too.
         */
        long found = -1;
        int  found_status = 0;
        for (uint32_t s = 0; s <= max_size; s += 1) {
            memset(buf, 0, s ? s : 1);
            int st = rm_control(0xDEADBEEF, cmd, s ? buf : NULL, s);
            if (st != 0x1F) {          /* not a size rejection -> size accepted */
                found = (long)s;
                found_status = st;
                break;
            }
        }
        fprintf(out,
                "{\"cmd\":\"0x%08X\",\"present\":true,\"found_size\":%ld,"
                "\"accept_status\":\"0x%08X\",\"probe_status\":\"0x%08X\"}\n",
                cmd, found, (uint32_t)found_status, (uint32_t)st_probe);
        fflush(out);
    }

    fclose(out);
    free(buf);
    fprintf(stderr, "[sweep] size scan complete -> %s\n", out_path);
    return 0;
}

static void hex_encode(const uint8_t *b, size_t n, char *out)
{
    static const char h[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        out[2 * i]     = h[(b[i] >> 4) & 0xf];
        out[2 * i + 1] = h[b[i] & 0xf];
    }
    out[2 * n] = '\0';
}

static int load_cmds(const char *path, struct cmd_entry *out, int max)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "[sweep] open %s: %s\n", path, strerror(errno));
        return -1;
    }
    /* Must hold a full request template: 2 hex chars per byte, plus the cmd,
     * the size and a trailing comment. A short buffer truncates the template
     * and fgets then re-parses the tail as another command, so an over-long
     * line is reported and drained rather than silently split. */
    char line[MAX_HEX_CHARS + 1024];
    int n = 0;
    unsigned long lineno = 0;

    while (fgets(line, sizeof(line), f) && n < max) {
        lineno++;
        size_t ll = strlen(line);
        if (ll == sizeof(line) - 1 && line[ll - 1] != '\n') {
            fprintf(stderr,
                    "[sweep] ERROR line %lu: longer than %zu bytes; raise the "
                    "line buffer\n", lineno, sizeof(line) - 1);
            g_template_errors++;
            int c;
            while ((c = fgetc(f)) != EOF && c != '\n') { }
            continue;
        }

        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\n' || *p == '\0') continue;
        unsigned long cmd, sz;
        char hex[MAX_HEX_CHARS + 3];
        hex[0] = '\0';
        int nf = sscanf(p, HEX_SCAN_FMT, &cmd, &sz, hex);
        if (nf < 2) continue;
        if (sz > MAX_PARAM_SZ) {
            fprintf(stderr, "[sweep] skip 0x%08lx: size %lu over cap\n", cmd, sz);
            continue;
        }

        uint32_t prefill_len = 0;
        /* Third field, when present and not a comment, is a hex request
         * template written into the head of the params buffer. */
        if (nf == 3 && hex[0] != '#' && hex[0] != '\0') {
            size_t hl = strlen(hex);
            const char *why = NULL;
            if (hl > MAX_HEX_CHARS)        why = "template longer than MAX_HEX_CHARS";
            else if (hl % 2)               why = "odd number of hex characters";
            else if (hl / 2 > MAX_PREFILL) why = "template exceeds MAX_PREFILL";
            else if (hl / 2 > sz)          why = "template larger than the declared paramsSize";

            if (!why) {
                for (size_t i = 0; i < hl / 2; i++) {
                    unsigned byte;
                    if (sscanf(hex + 2 * i, "%2x", &byte) != 1) {
                        why = "non-hex character in template";
                        break;
                    }
                    out[n].prefill[i] = (uint8_t)byte;
                }
            }

            /*
             * Never fall through to a zeroed buffer. A request-driven GET with
             * count == 0 returns nothing, so the sweep would emit a normal
             * looking row carrying no data at all — the exact silent failure in
             * code.md finding E2. Skip the command and fail the run instead.
             */
            if (why) {
                fprintf(stderr,
                        "[sweep] ERROR line %lu cmd 0x%08lx: %s (%zu hex chars "
                        "= %zu bytes, paramsSize %lu, cap %d)\n",
                        lineno, cmd, why, hl, hl / 2, sz, MAX_PREFILL);
                g_template_errors++;
                continue;
            }
            prefill_len = (uint32_t)(hl / 2);
        }

        out[n].cmd  = (uint32_t)cmd;
        out[n].size = (uint32_t)sz;
        out[n].prefill_len = prefill_len;
        n++;
    }
    fclose(f);
    return n;
}

int main(int argc, char **argv)
{
    const char *cmds_path = NULL, *out_path = NULL;
    unsigned gpu = 0;
    uint32_t size_scan_max = 0;
    enum probe_mode mode = PROBE_NORMAL;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--cmds") && i + 1 < argc)      cmds_path = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc)  out_path  = argv[++i];
        else if (!strcmp(argv[i], "--gpu") && i + 1 < argc)  gpu = (unsigned)atoi(argv[++i]);
        /* Size scan runs the handler once, at the size the driver accepts.
         * Only ever feed it read-only commands (see gen_sweep_list.py). */
        else if (!strcmp(argv[i], "--size-scan") && i + 1 < argc)
            size_scan_max = (uint32_t)strtoul(argv[++i], NULL, 0);
        else if (!strcmp(argv[i], "--probe-mode") && i + 1 < argc) {
            const char *m = argv[++i];
            if      (!strcmp(m, "normal"))    mode = PROBE_NORMAL;
            else if (!strcmp(m, "badsize"))   mode = PROBE_BADSIZE;
            else if (!strcmp(m, "badobject")) mode = PROBE_BADOBJECT;
            else if (!strcmp(m, "badboth"))   mode = PROBE_BADBOTH;
            else { fprintf(stderr, "[sweep] bad --probe-mode %s\n", m); return 2; }
        } else {
            fprintf(stderr, "usage: %s --cmds F --out F [--gpu N] "
                            "[--probe-mode normal|badsize|badobject|badboth]\n", argv[0]);
            return 2;
        }
    }
    if (!cmds_path || !out_path) {
        fprintf(stderr, "[sweep] --cmds and --out are required\n");
        return 2;
    }

    struct cmd_entry *cmds = calloc(MAX_CMDS, sizeof(*cmds));
    if (!cmds) return 1;
    int ncmds = load_cmds(cmds_path, cmds, MAX_CMDS);
    if (ncmds < 0) return 1;
    fprintf(stderr, "[sweep] %d commands loaded from %s\n", ncmds, cmds_path);

    /* Refuse to sweep with a partly-unusable command list. Runs before the
     * ladder is built, so this path never touches the driver. */
    if (g_template_errors) {
        fprintf(stderr,
                "[sweep] %d command(s) had an unusable request template and were "
                "skipped.\n[sweep] Refusing to run: a zeroed params buffer reads "
                "nothing (see code.md finding E2).\n", g_template_errors);
        free(cmds);
        return 3;
    }

    if (size_scan_max > 0) {
        if (build_ladder(gpu) != 0) {
            fprintf(stderr, "[sweep] could not build the RM object ladder\n");
            return 1;
        }
        return run_size_scan(cmds, ncmds, out_path, size_scan_max);
    }

    if (build_ladder(gpu) != 0) {
        fprintf(stderr, "[sweep] could not build the RM object ladder\n");
        return 1;
    }

    FILE *out = fopen(out_path, "w");
    if (!out) {
        fprintf(stderr, "[sweep] open %s: %s\n", out_path, strerror(errno));
        return 1;
    }

    uint8_t *pbuf   = malloc(MAX_PARAM_SZ);
    char    *hexbuf = malloc(2 * MAX_PARAM_SZ + 1);
    if (!pbuf || !hexbuf) return 1;

    int ok = 0;
    for (int i = 0; i < ncmds; i++) {
        uint32_t cmd  = cmds[i].cmd;
        uint32_t size = cmds[i].size;

        memset(pbuf, 0, size ? size : 1);
        if (cmds[i].prefill_len)
            memcpy(pbuf, cmds[i].prefill, cmds[i].prefill_len);

        NVOS54_PARAMETERS c;
        memset(&c, 0, sizeof(c));
        c.hClient    = g_hClient;
        c.hObject    = object_for_cmd(cmd);
        c.cmd        = (int32_t)cmd;
        c.flags      = 0;
        c.params     = size ? (uint64_t)(uintptr_t)pbuf : 0;
        c.paramsSize = size;

        if (mode == PROBE_BADSIZE || mode == PROBE_BADBOTH)
            c.paramsSize = size + 4;       /* deliberately wrong size */
        if (mode == PROBE_BADOBJECT || mode == PROBE_BADBOTH)
            c.hObject = 0xDEADBEEF;        /* handle that cannot resolve */

        errno = 0;
        int r  = ioctl(g_fd, ESC_RM_CONTROL, &c);
        int er = errno;

        /* Only hex-dump the response when the call actually succeeded; a
         * failed control leaves the buffer as we zeroed it. */
        size_t dump = (r == 0 && c.status == 0) ? size : 0;
        hex_encode(pbuf, dump, hexbuf);

        fprintf(out,
                "{\"cmd\":\"0x%08X\",\"size\":%u,\"ret\":%d,\"errno\":%d,"
                "\"status\":\"0x%08X\",\"resp\":\"%s\"}\n",
                cmd, size, r, er, (uint32_t)c.status, hexbuf);

        if (r == 0 && c.status == 0) ok++;
    }

    fclose(out);
    fprintf(stderr, "[sweep] done: %d/%d commands returned status 0 -> %s\n",
            ok, ncmds, out_path);
    close(g_fd);
    free(pbuf); free(hexbuf); free(cmds);
    return 0;
}
