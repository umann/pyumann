#define _XOPEN_SOURCE 700
#include <fnmatch.h>
#include <ftw.h>
#include <glob.h>
#include <openssl/evp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

/* FTW_SKIP_SUBTREE is a GNU extension; define it for portability */
#ifndef FTW_SKIP_SUBTREE
#define FTW_SKIP_SUBTREE 2
#endif

static int enable_md5 = 0;
static const char *filename_glob_pattern = NULL;
static const char *gitignore_path = NULL;

#define MAX_PATTERNS 1000
static char *ignore_patterns[MAX_PATTERNS];
static int ignore_pattern_count = 0;

/* Load and parse .gitignore file */
static void load_gitignore(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        perror(path);
        return;
    }
    char line[1024];
    while (fgets(line, sizeof(line), f) && ignore_pattern_count < MAX_PATTERNS) {
        /* Remove trailing newline */
        char *newline = strchr(line, '\n');
        if (newline) *newline = '\0';
        /* Skip empty lines and comments */
        if (line[0] == '\0' || line[0] == '#') continue;
        ignore_patterns[ignore_pattern_count++] = strdup(line);
    }
    fclose(f);
}

/* Check if a path matches any .gitignore pattern */
static int is_gitignore_match(const char *path) {
    if (ignore_pattern_count == 0) return 0; /* No patterns = nothing ignored */
    for (int i = 0; i < ignore_pattern_count; ++i) {
        const char *pattern_src = ignore_patterns[i];
        char patbuf[1024];
        /* Work on a mutable copy so we can strip trailing slash */
        strncpy(patbuf, pattern_src, sizeof(patbuf) - 1);
        patbuf[sizeof(patbuf) - 1] = '\0';
        char *pattern = patbuf;
        int negate = 0;
        /* Handle negation patterns (!) */
        if (pattern[0] == '!') {
            negate = 1;
            pattern++;
        }
        /* Remove trailing slash from pattern for matching */
        size_t pattern_len = strlen(pattern);
        if (pattern_len > 0 && pattern[pattern_len - 1] == '/') {
            pattern[pattern_len - 1] = '\0';
        }
        /* Match against full path and basename */
        int match = (fnmatch(pattern, path, FNM_PATHNAME) == 0) ||
                    (fnmatch(pattern, strrchr(path, '/') ? strrchr(path, '/') + 1 : path, 0) == 0);
        if (match) {
            return negate ? 0 : 1;
        }
    }
    return 0;
}

/* Check if any parent directory matches gitignore */
static int is_dir_gitignore_match(const char *path) {
    if (ignore_pattern_count == 0) return 0;
    char temp[4096];
    strncpy(temp, path, sizeof(temp) - 1);
    temp[sizeof(temp) - 1] = '\0';

    /* Test each parent directory */
    char *p = temp;
    while ((p = strrchr(p, '/')) != NULL) {
        *p = '\0';
        if (is_gitignore_match(temp)) {
            return 1;
        }
        p = temp;
    }
    return 0;
}

static int md5_file_hex(const char *path, char out_hex[33]) {
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned char buf[1 << 15]; /* 32 KiB */
    EVP_MD_CTX *ctx;
    unsigned int digest_len;

    FILE *f = fopen(path, "rb");
    if (!f) {
        perror(path);
        return -1;
    }

    ctx = EVP_MD_CTX_new();
    if (!ctx) {
        perror("EVP_MD_CTX_new");
        fclose(f);
        return -1;
    }

    if (!EVP_DigestInit_ex(ctx, EVP_md5(), NULL)) {
        perror("EVP_DigestInit_ex");
        EVP_MD_CTX_free(ctx);
        fclose(f);
        return -1;
    }

    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f)) > 0) {
        if (!EVP_DigestUpdate(ctx, buf, n)) {
            perror("EVP_DigestUpdate");
            EVP_MD_CTX_free(ctx);
            fclose(f);
            return -1;
        }
    }
    if (ferror(f)) {
        perror(path);
        EVP_MD_CTX_free(ctx);
        fclose(f);
        return -1;
    }
    fclose(f);

    if (!EVP_DigestFinal_ex(ctx, digest, &digest_len)) {
        perror("EVP_DigestFinal_ex");
        EVP_MD_CTX_free(ctx);
        return -1;
    }
    EVP_MD_CTX_free(ctx);

    for (unsigned int i = 0; i < digest_len; ++i) {
        sprintf(out_hex + (i * 2), "%02x", digest[i]);
    }
    out_hex[32] = '\0';
    return 0;
}

/* Check if a file should be processed based on --fnmatch filter */
static int matches_filename_filter(const char *path) {
    if (filename_glob_pattern == NULL) {
        return 1; /* No filter, accept all */
    }
    /* Extract basename (filename without directory) */
    const char *basename = strrchr(path, '/');
    if (basename == NULL) {
        basename = path; /* No directory separator */
    } else {
        basename++; /* Skip the '/' */
    }
    return fnmatch(filename_glob_pattern, basename, 0) == 0;
}

/* Escape a path for CSV by wrapping in double quotes and doubling any quotes. */
static void print_csv_row(const char *path, off_t size, double mtime, const char *md5_hex) {
    fputc('"', stdout);
    for (const char *p = path; *p; ++p) {
        if (*p == '"') {
            fputc('"', stdout);
        }
        fputc(*p, stdout);
    }
    fputc('"', stdout);
    printf(",%lld,%.6f", (long long)size, mtime);
    if (enable_md5) {
        printf(",%s", md5_hex);
    }
    printf("\n");
}

static int visit(const char *fpath, const struct stat *sb, int typeflag, struct FTW *ftwbuf) {
    (void)ftwbuf;

    /* Skip if matches gitignore */
    if (is_gitignore_match(fpath) || is_dir_gitignore_match(fpath)) {
        return FTW_SKIP_SUBTREE; /* Skip this file/dir and its subtree */
    }

    if (typeflag == FTW_F) {
        if (!matches_filename_filter(fpath)) {
            return 0; /* skip files not matching filter */
        }
        char md5_hex[33] = {0};
        if (enable_md5) {
            if (md5_file_hex(fpath, md5_hex) == -1) {
                return 0; /* skip on error */
            }
        }
        print_csv_row(fpath, sb->st_size, (double)sb->st_mtim.tv_sec + sb->st_mtim.tv_nsec / 1e9, md5_hex);
    }
    return 0; /* continue */
}

/* Process a single file: check if it's a file or directory */
static void process_path(const char *path) {
    struct stat sb;
    if (stat(path, &sb) == -1) {
        /* File does not exist - print with mtime=-1, size=-1 */
        print_csv_row(path, -1, -1, "");
        return;
    }

    if (S_ISDIR(sb.st_mode)) {
        /* It's a directory - use nftw to traverse it */
        nftw(path, visit, 20, FTW_PHYS);
    } else if (S_ISREG(sb.st_mode)) {
        /* It's a regular file - check filter and process it */
        if (!matches_filename_filter(path)) {
            return; /* skip files not matching filter */
        }
        char md5_hex[33] = {0};
        if (enable_md5) {
            if (md5_file_hex(path, md5_hex) == -1) {
                return; /* skip on error */
            }
        }
        print_csv_row(path, sb.st_size, (double)sb.st_mtim.tv_sec + sb.st_mtim.tv_nsec / 1e9, md5_hex);
    }
}

/* Process a single argument (may be a glob pattern) */
static void process_argument(const char *arg) {
    /* Check if arg contains glob metacharacters */
    if (strchr(arg, '*') || strchr(arg, '?') || strchr(arg, '[')) {
        glob_t globbuf;
        int ret = glob(arg, GLOB_NOSORT | GLOB_MARK, NULL, &globbuf);

        if (ret == 0) {
            /* Glob succeeded - process each match */
            for (size_t i = 0; i < globbuf.gl_pathc; ++i) {
                process_path(globbuf.gl_pathv[i]);
            }
            globfree(&globbuf);
        } else if (ret == GLOB_NOMATCH) {
            /* No matches - print with mtime=-1, size=-1 */
            print_csv_row(arg, -1, -1, "");
        } else {
            /* Glob error */
            perror("glob");
        }
    } else {
        /* No glob metacharacters - process as regular path */
        process_path(arg);
    }
}

/* Print usage help and return failure */
static int help(const char *progname) {
    fprintf(stderr, "Usage: %s [--md5] [--fnmatch PATTERN] [--gitignore FILE] <path|fnmatch> [<path|fnmatch> ...]\n", progname);
    return EXIT_FAILURE;
}

int main(int argc, char **argv) {
    int arg_start = 1;

    if (argc < 2) {
        return help(argv[0]);
    }

    /* Parse options */
    while (arg_start < argc) {
        if (strcmp(argv[arg_start], "--md5") == 0) {
            enable_md5 = 1;
            arg_start++;
        } else if (strcmp(argv[arg_start], "--fnmatch") == 0) {
            if (arg_start + 1 >= argc) {
                fprintf(stderr, "Error: --fnmatch requires a pattern argument\n");
                return EXIT_FAILURE;
            }
            filename_glob_pattern = argv[arg_start + 1];
            arg_start += 2;
        } else if (strcmp(argv[arg_start], "--gitignore") == 0) {
            if (arg_start + 1 >= argc) {
                fprintf(stderr, "Error: --gitignore requires a file argument\n");
                return EXIT_FAILURE;
            }
            gitignore_path = argv[arg_start + 1];
            load_gitignore(gitignore_path);
            arg_start += 2;
        } else {
            break; /* Not an option, treat as path argument */
        }
    }

    /* Require at least one path/fnmatch argument */
    if (arg_start >= argc) {
        return help(argv[0]);
    }

    /* Process each argument */
    for (int i = arg_start; i < argc; ++i) {
        process_argument(argv[i]);
    }

    return EXIT_SUCCESS;
}
