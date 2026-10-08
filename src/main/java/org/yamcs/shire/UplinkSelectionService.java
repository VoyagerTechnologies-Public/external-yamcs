package org.yamcs.shire;

import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import org.yamcs.AbstractYamcsService;
import org.yamcs.InitException;
import org.yamcs.YConfiguration;
import org.yamcs.YamcsServer;
import org.yamcs.cmdhistory.CommandHistoryPublisher;
import org.yamcs.cmdhistory.CommandHistoryPublisher.AckStatus;
import org.yamcs.cmdhistory.StreamCommandHistoryPublisher;
import org.yamcs.commanding.PreparedCommand;
import org.yamcs.management.LinkManager;
import org.yamcs.protobuf.Commanding.CommandId;
import org.yamcs.tctm.TcDataLink;
import org.yamcs.yarch.Stream;
import org.yamcs.yarch.StreamSubscriber;
import org.yamcs.yarch.Tuple;

/** Ground-only stack commands for temporary selection of an existing uplink. */
public class UplinkSelectionService extends AbstractYamcsService implements StreamSubscriber {
    private static final String SELECT = "/SHIRE_GROUND/USE_RADIO_UPLINK";
    private static final String RESTORE = "/SHIRE_GROUND/RESTORE_UPLINK";
    private static final String SELECT_DEBUG = "/SHIRE_GROUND/USE_DEBUG_UPLINK";
    private Stream stream;
    private CommandHistoryPublisher history;
    private UplinkSelection selection;
    private ScheduledExecutorService timer;
    private long deadline;
    private long leaseNanos;

    @Override
    public void init(String instance, String name, YConfiguration config) throws InitException {
        super.init(instance, name, config);
        int leaseSeconds = config.getInt("leaseSeconds", 30);
        if (leaseSeconds <= 0) {
            throw new InitException("leaseSeconds must be positive");
        }
        leaseNanos = TimeUnit.SECONDS.toNanos(leaseSeconds);
    }

    @Override
    protected void doStart() {
        try {
            LinkManager links = YamcsServer.getServer().getInstance(yamcsInstance).getLinkManager();
            String primary = config.getString("primaryLink", "debug-out");
            String alternate = config.getString("alternateLink", "radio-out");
            if (!(links.getLink(primary) instanceof TcDataLink)
                    || !(links.getLink(alternate) instanceof TcDataLink)) {
                throw new IllegalArgumentException("Configured uplinks must exist and support commands");
            }
            selection = new UplinkSelection(new UplinkSelection.Control() {
                public boolean isDisabled(String name) {
                    return links.getLink(name).isDisabled();
                }

                public void setDisabled(String name, boolean disabled) {
                    if (disabled) {
                        links.disableLink(name);
                    } else {
                        links.enableLink(name);
                    }
                }
            }, primary, alternate);
            history = new StreamCommandHistoryPublisher(yamcsInstance);
            stream = findStream(config.getString("stream", "ground_control"));
            timer = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread thread = new Thread(r, "shire-uplink-restoration-" + yamcsInstance);
                thread.setDaemon(true);
                return thread;
            });
            timer.scheduleWithFixedDelay(this::expireSelection, 1, 1, TimeUnit.SECONDS);
            stream.addSubscriber(this);
            notifyStarted();
        } catch (Exception e) {
            if (timer != null) {
                timer.shutdownNow();
            }
            notifyFailed(e);
        }
    }

    @Override
    public synchronized void onTuple(Stream stream, Tuple tuple) {
        CommandId id;
        try {
            id = PreparedCommand.getCommandId(tuple);
        } catch (Exception e) {
            log.error("Ignoring malformed ground control tuple", e);
            return;
        }
        try {
            String name = id.getCommandName();
            if (SELECT_DEBUG.equals(name)) {
                selection.selectPrimary();
            } else if (SELECT.equals(name)) {
                selection.selectAlternate();
                deadline = System.nanoTime() + leaseNanos;
            } else if (RESTORE.equals(name)) {
                // Expiry is an error to the stack even if links already recovered.
                if (selection.isActive() && System.nanoTime() >= deadline) {
                    selection.restore();
                    throw new IllegalStateException("Uplink selection expired before restoration command");
                }
                selection.restore();
            } else {
                throw new IllegalArgumentException("Unsupported ground control command");
            }
            acknowledge(id, AckStatus.OK, SELECT_DEBUG.equals(name)
                    ? "Debug uplink selected exclusively for normal commanding"
                    : SELECT.equals(name) ? "Radio uplink selected; prior link states saved"
                    : "Prior uplink states restored");
        } catch (Exception e) {
            acknowledge(id, AckStatus.NOK, e.getMessage());
        }
    }

    private synchronized void expireSelection() {
        if (selection.isActive() && System.nanoTime() >= deadline) {
            try {
                selection.restore();
                log.warn("Uplink selection expired; prior link states restored");
            } catch (Exception e) {
                log.error("Could not restore expired uplink selection; retrying", e);
            }
        }
    }

    @Override
    protected synchronized void doStop() {
        if (stream != null) {
            stream.removeSubscriber(this);
        }
        if (timer != null) {
            timer.shutdownNow();
        }
        try {
            if (selection != null && selection.isActive()) {
                selection.restore();
            }
            notifyStopped();
        } catch (Exception e) {
            notifyFailed(e);
        }
    }

    private void acknowledge(CommandId id, AckStatus status, String message) {
        history.publishAck(id, CommandHistoryPublisher.AcknowledgeSent_KEY,
                YamcsServer.getTimeService(yamcsInstance).getMissionTime(), status, message);
    }
}
