#define _GNU_SOURCE
#include <errno.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/statfs.h>
#include <unistd.h>

#ifndef CGROUP2_SUPER_MAGIC
#define CGROUP2_SUPER_MAGIC 0x63677270
#endif

static void fail(const char *operation) {
    perror(operation);
    exit(125);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fputs("usage: opsforge-cgroup-namespace PROGRAM [ARG...]\n", stderr);
        return 125;
    }
    struct statfs fs;
    if (statfs("/sys/fs/cgroup", &fs) != 0) fail("statfs private cgroup");
    if ((unsigned long)fs.f_type != CGROUP2_SUPER_MAGIC) {
        fputs("OpsForge private K3s requires cgroup v2\n", stderr);
        return 125;
    }
    /* Both namespace changes affect only this sidecar and its descendants.
       No outer kubelet/runtime setting or outer cgroup is modified. */
    if (unshare(CLONE_NEWCGROUP | CLONE_NEWNS) != 0) fail("unshare private cgroup/mount namespace");
    if (mount(NULL, "/sys/fs/cgroup", NULL, MS_REC | MS_PRIVATE, NULL) != 0) fail("private cgroup mount propagation");
    if (umount2("/sys/fs/cgroup", MNT_DETACH) != 0) fail("detach inherited cgroup mount");
    if (mount("none", "/sys/fs/cgroup", "cgroup2", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) != 0) fail("mount private cgroup view");
    FILE *file = fopen("/proc/self/cgroup", "r");
    if (!file) fail("read private cgroup");
    char line[4096];
    if (!fgets(line, sizeof(line), file)) fail("read private cgroup line");
    fclose(file);
    if (strcmp(line, "0::/\n") != 0) {
        fputs("Private cgroup root does not map to this sidecar\n", stderr);
        return 125;
    }
    fprintf(stderr, "OPSF_PRIVATE_CGROUP_NAMESPACE_READY\n");
    execvp(argv[1], argv + 1);
    fail("exec private sidecar entrypoint");
}
