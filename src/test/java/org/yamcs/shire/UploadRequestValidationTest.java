package org.yamcs.shire;

import java.util.List;

/** Dependency-free checks, run by test-upload-validation.sh. */
public class UploadRequestValidationTest {
    static final List<String> DATA_ONLY = List.of("/d/");

    static void accepted(String object, String path, List<String> prefixes) {
        String problem = UploadRequestValidation.problem(object, path, prefixes);
        if (problem != null) {
            throw new AssertionError("Expected " + object + " to " + path + " to be accepted, got: " + problem);
        }
    }

    static void refused(String object, String path, List<String> prefixes, String expected) {
        String problem = UploadRequestValidation.problem(object, path, prefixes);
        if (problem == null) {
            throw new AssertionError("Expected " + object + " to " + path + " to be refused");
        }
        if (!problem.contains(expected)) {
            throw new AssertionError("Expected '" + expected + "' in '" + problem + "'");
        }
    }

    public static void main(String[] args) {
        // Ordinary uploads to the data directory.
        accepted("up_sc_rts012.tbl", "/d/rts12.tbl", DATA_ONLY);
        accepted("a", "/d/x", DATA_ONLY);
        accepted("Patch-1_v2.so", "/d/sub/dir/Patch-1_v2.so", DATA_ONLY);
        accepted("o".repeat(128), "/d/" + "p".repeat(10), DATA_ONLY);

        // The object must be a plain file name.
        for (String object : new String[] {"", ".hidden", "-flag", "dir/file", "../file", "with space", "semi;colon",
                "o".repeat(129)}) {
            refused(object, "/d/file", DATA_ONLY, "OBJECT_NAME");
        }

        // The path must be an absolute file path.
        for (String path : new String[] {"", "/", "relative/file", "d/file", "/d/dir/", "/d/../cf/core-cpu1",
                "/d/a..b", "/d/with space", "/d/semi;colon", "/d/" + "p".repeat(200)}) {
            refused("file", path, DATA_ONLY, "REMOTE_PATH must be an absolute file path");
        }

        // Uploads never reach flight software unless the configuration allows it.
        refused("core", "/cf/core-cpu1", DATA_ONLY, "must start with /d/");
        refused("core", "/data/file", DATA_ONLY, "must start with /d/");
        refused("core", "/dfile", DATA_ONLY, "must start with /d/");
        accepted("core", "/cf/patch.so", List.of("/d/", "/cf/"));
        refused("core", "/tmp/file", List.of("/d/", "/cf/"), "must start with /d/ or /cf/");
        refused("core", "/d/file", List.of(), "must start with ");
        System.out.println("UploadRequestValidationTest passed");
    }
}
