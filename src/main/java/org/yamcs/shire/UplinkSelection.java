package org.yamcs.shire;

/** Saves and restores a pair of uplink states, including partial failures. */
final class UplinkSelection {
    interface Control {
        boolean isDisabled(String name);
        void setDisabled(String name, boolean disabled);
    }

    private final Control control;
    private final String primary;
    private final String alternate;
    private boolean[] saved;

    UplinkSelection(Control control, String primary, String alternate) {
        if (primary.equals(alternate)) {
            throw new IllegalArgumentException("Uplinks must be distinct");
        }
        this.control = control;
        this.primary = primary;
        this.alternate = alternate;
    }

    synchronized void selectAlternate() {
        if (saved != null) {
            throw new IllegalStateException("An uplink selection is already active");
        }
        boolean[] snapshot = {control.isDisabled(primary), control.isDisabled(alternate)};
        saved = snapshot;
        try {
            apply(primary, true);
            apply(alternate, false);
        } catch (RuntimeException failure) {
            try {
                restore();
            } catch (RuntimeException restoration) {
                failure.addSuppressed(restoration);
            }
            throw failure;
        }
    }

    synchronized boolean isActive() {
        return saved != null;
    }

    synchronized void selectPrimary() {
        if (saved != null) {
            restore(); // Recover an interrupted temporary selection first.
        }
        saved = new boolean[] {control.isDisabled(primary), control.isDisabled(alternate)};
        try {
            apply(alternate, true);
            apply(primary, false);
            saved = null; // Establish the normal path, rather than a temporary lease.
        } catch (RuntimeException failure) {
            try {
                restore();
            } catch (RuntimeException restoration) {
                failure.addSuppressed(restoration);
            }
            throw failure;
        }
    }

    synchronized void restore() {
        if (saved == null) {
            throw new IllegalStateException("No active uplink selection (possibly expired)");
        }
        RuntimeException failure = null;
        // Disable first, then enable, so restoration cannot duplicate traffic.
        String[] names = {primary, alternate};
        for (boolean disabled : new boolean[] {true, false}) {
            for (int i = 0; i < names.length; i++) {
                if (saved[i] != disabled) {
                    continue;
                }
                try {
                    apply(names[i], disabled);
                } catch (RuntimeException e) {
                    if (failure == null) {
                        failure = e;
                    } else {
                        failure.addSuppressed(e);
                    }
                }
            }
        }
        if (failure != null) {
            throw failure; // Retain the snapshot for a later recovery attempt.
        }
        saved = null;
    }

    private void apply(String name, boolean disabled) {
        control.setDisabled(name, disabled);
        if (control.isDisabled(name) != disabled) {
            throw new IllegalStateException("Uplink state did not change: " + name);
        }
    }
}
