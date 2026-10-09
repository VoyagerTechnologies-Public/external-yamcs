package org.yamcs.shire;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Dependency-free checks, run by test-uplink-selection.sh. */
public class UplinkSelectionTest {
    static class FakeControl implements UplinkSelection.Control {
        final Map<String, Boolean> states = new HashMap<>();
        final List<String> operations = new ArrayList<>();
        String fail;

        FakeControl(boolean primary, boolean alternate) {
            states.put("debug", primary);
            states.put("radio", alternate);
        }

        public boolean isDisabled(String name) {
            return states.get(name);
        }

        public void setDisabled(String name, boolean disabled) {
            operations.add(name + ":" + disabled);
            if (name.equals(fail)) {
                throw new IllegalStateException("Injected failure: " + name);
            }
            states.put(name, disabled);
        }
    }

    static void rejected(Runnable action) {
        try {
            action.run();
            throw new AssertionError("Expected rejection");
        } catch (IllegalStateException expected) {
            // Expected.
        }
    }

    public static void main(String[] args) {
        for (boolean primary : new boolean[] {true, false}) {
            for (boolean alternate : new boolean[] {true, false}) {
                FakeControl control = new FakeControl(primary, alternate);
                UplinkSelection selection = new UplinkSelection(control, "debug", "radio");
                rejected(selection::restore);
                selection.selectAlternate();
                assert control.isDisabled("debug") && !control.isDisabled("radio");
                rejected(selection::selectAlternate);
                assert selection.isActive();
                selection.restore();
                assert control.isDisabled("debug") == primary;
                assert control.isDisabled("radio") == alternate;
                assert !selection.isActive();
                rejected(selection::restore);
                selection.selectAlternate();
                selection.restore(); // A second run saves a new snapshot.
                selection.selectPrimary();
                assert !control.isDisabled("debug") && control.isDisabled("radio");
                assert !selection.isActive();
                selection.selectPrimary(); // Idempotent, including initially disabled debug.
                selection.selectAlternate();
                selection.restore();
                assert !control.isDisabled("debug") && control.isDisabled("radio");
                selection.selectAlternate();
                selection.selectPrimary(); // Recover an interrupted RF probe.
                assert !selection.isActive() && !control.isDisabled("debug") && control.isDisabled("radio");
            }
        }

        FakeControl control = new FakeControl(false, true);
        UplinkSelection selection = new UplinkSelection(control, "debug", "radio");
        control.fail = "radio";
        rejected(selection::selectAlternate);
        assert !control.isDisabled("debug"); // Rollback attempted despite failure on radio.
        assert selection.isActive(); // Snapshot retained for recovery retry.
        control.fail = null;
        selection.restore();
        assert !selection.isActive() && !control.isDisabled("debug") && control.isDisabled("radio");

        selection.selectAlternate();
        control.operations.clear();
        control.fail = "radio";
        rejected(selection::restore);
        assert control.operations.equals(List.of("radio:true", "debug:false"));
        control.fail = null;
        selection.restore();
        assert !selection.isActive();

        // Failed startup selection must roll back both original link states.
        FakeControl startupControl = new FakeControl(true, false);
        UplinkSelection startup = new UplinkSelection(startupControl, "debug", "radio");
        startupControl.fail = "debug";
        rejected(startup::selectPrimary);
        assert !startupControl.isDisabled("radio");
        assert startup.isActive();
        startupControl.fail = null;
        startup.restore();
        assert startupControl.isDisabled("debug") && !startupControl.isDisabled("radio");
        startup.selectPrimary();
        assert !startupControl.isDisabled("debug") && startupControl.isDisabled("radio");
        assert !startup.isActive();

        // A link that silently ignores enable/disable must not acknowledge success.
        UplinkSelection ignored = new UplinkSelection(new UplinkSelection.Control() {
            public boolean isDisabled(String name) { return false; }
            public void setDisabled(String name, boolean disabled) { }
        }, "debug", "radio");
        rejected(ignored::selectAlternate);
        assert !ignored.isActive();
        System.out.println("Uplink selection: snapshot, exclusivity, rollback and recovery checks passed");
    }
}
