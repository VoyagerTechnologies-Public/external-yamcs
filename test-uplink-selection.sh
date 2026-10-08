#!/bin/sh
set -eu
cd "$(dirname "$0")"
test_classes=$(mktemp -d)
trap 'rm -rf "$test_classes"' EXIT
javac -d "$test_classes" src/main/java/org/yamcs/shire/UplinkSelection.java \
    src/test/java/org/yamcs/shire/UplinkSelectionTest.java
java -ea -cp "$test_classes" org.yamcs.shire.UplinkSelectionTest
