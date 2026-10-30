package org.yamcs.shire;

import java.util.List;
import java.util.regex.Pattern;

/** Decides whether an upload request names a file the ground may stage and a place the flight software lets it write. */
final class UploadRequestValidation {
    private static final Pattern OBJECT_NAME = Pattern.compile("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}");
    private static final Pattern REMOTE_PATH = Pattern.compile("/[A-Za-z0-9_./-]{1,200}");

    private UploadRequestValidation() {
    }

    /** Returns why a request is refused, or null when it is acceptable. */
    static String problem(String object, String path, List<String> remotePrefixes) {
        if (!OBJECT_NAME.matcher(object).matches()) {
            return "OBJECT_NAME must be a plain file name, got '" + object + "'";
        }
        if (!REMOTE_PATH.matcher(path).matches() || path.contains("..") || path.endsWith("/")) {
            return "REMOTE_PATH must be an absolute file path, got '" + path + "'";
        }
        if (remotePrefixes.stream().noneMatch(path::startsWith)) {
            return "REMOTE_PATH must start with " + String.join(" or ", remotePrefixes) + ", got '" + path + "'";
        }
        return null;
    }
}
