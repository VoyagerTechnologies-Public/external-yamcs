package org.yamcs.shire;

import java.io.IOException;
import java.io.InputStream;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.yamcs.AbstractYamcsService;
import org.yamcs.InitException;
import org.yamcs.YConfiguration;
import org.yamcs.YamcsServer;
import org.yamcs.buckets.Bucket;
import org.yamcs.cfdp.CfdpService;
import org.yamcs.cmdhistory.CommandHistoryPublisher;
import org.yamcs.cmdhistory.CommandHistoryPublisher.AckStatus;
import org.yamcs.cmdhistory.StreamCommandHistoryPublisher;
import org.yamcs.commanding.PreparedCommand;
import org.yamcs.filetransfer.FileTransfer;
import org.yamcs.filetransfer.TransferMonitor;
import org.yamcs.filetransfer.TransferOptions;
import org.yamcs.protobuf.Commanding.CommandId;
import org.yamcs.protobuf.TransferState;
import org.yamcs.yarch.Stream;
import org.yamcs.yarch.StreamSubscriber;
import org.yamcs.yarch.Tuple;

/**
 * Turns the checkout stack's ground command into a CFDP upload.
 *
 * <p>The command is routed to a dedicated Yamcs stream, so it is never sent to
 * the spacecraft as a telecommand. Acknowledge_Sent is published only after the
 * CFDP transaction completes, which makes the stack wait without operator input.
 */
public class CheckoutCfdpUploadService extends AbstractYamcsService
        implements StreamSubscriber, TransferMonitor {

    private static final String EXPECTED_COMMAND = "/CCSDS/CFDP_UPLOAD_CHECKOUT";
    private static final String PAYLOAD_RESOURCE = "/yamcs/procedures/components/adcs/AdcsComponent.ycs";

    private final Map<Long, CommandId> pendingCommands = new ConcurrentHashMap<>();

    private Stream commandStream;
    private CfdpService cfdpService;
    private CommandHistoryPublisher commandHistory;
    private String bucketName;
    private String objectName;
    private String remotePath;
    private String localEntity;
    private String remoteEntity;

    @Override
    public void init(String yamcsInstance, String serviceName, YConfiguration config) throws InitException {
        super.init(yamcsInstance, serviceName, config);

        bucketName = config.getString("bucket", "cfdpUp");
        objectName = config.getString("objectName", "AdcsComponent.ycs");
        remotePath = config.getString("remotePath", "/d/checkout_adcs.ycs");
        localEntity = config.getString("localEntity", "GSW");
        remoteEntity = config.getString("remoteEntity", "FSW");
    }

    @Override
    protected void doStart() {
        try {
            commandStream = findStream(config.getString("stream", "checkout_control"));
            cfdpService = YamcsServer.getServer()
                    .getInstance(yamcsInstance)
                    .getService(CfdpService.class, config.getString("cfdpService", "cfdp"));
            if (cfdpService == null) {
                throw new IllegalStateException("CFDP service is not configured");
            }

            commandHistory = new StreamCommandHistoryPublisher(yamcsInstance);
            cfdpService.registerTransferMonitor(this);
            commandStream.addSubscriber(this);
            notifyStarted();
        } catch (Exception e) {
            notifyFailed(e);
        }
    }

    @Override
    protected void doStop() {
        if (commandStream != null) {
            commandStream.removeSubscriber(this);
        }
        if (cfdpService != null) {
            cfdpService.unregisterTransferMonitor(this);
        }
        notifyStopped();
    }

    @Override
    public void onTuple(Stream stream, Tuple tuple) {
        CommandId commandId;
        try {
            commandId = PreparedCommand.getCommandId(tuple);
        } catch (Exception e) {
            log.error("Ignoring malformed checkout command tuple", e);
            return;
        }

        if (!EXPECTED_COMMAND.equals(commandId.getCommandName())) {
            acknowledge(commandId, AckStatus.NOK, "Unsupported checkout control command");
            return;
        }

        try (InputStream in = getClass().getResourceAsStream(PAYLOAD_RESOURCE)) {
            if (in == null) {
                throw new IOException("Missing checkout payload " + PAYLOAD_RESOURCE);
            }
            byte[] payload = in.readAllBytes();
            Bucket bucket = YamcsServer.getServer().getBucketManager().getBucket(bucketName);
            if (bucket == null) {
                throw new IOException("Unknown Yamcs bucket " + bucketName);
            }

            bucket.putObjectAsync(objectName, "application/json", Map.of(), payload)
                    .whenComplete((unused, error) -> {
                        if (error != null) {
                            acknowledge(commandId, AckStatus.NOK,
                                    "Could not stage CFDP upload: " + error.getMessage());
                            return;
                        }
                        startUpload(commandId, bucket);
                    });
        } catch (Exception e) {
            acknowledge(commandId, AckStatus.NOK, "Could not stage CFDP upload: " + e.getMessage());
        }
    }

    private void startUpload(CommandId commandId, Bucket bucket) {
        try {
            TransferOptions options = new TransferOptions();
            options.setReliable(true);
            options.setOverwrite(true);
            options.setCreatePath(true);

            FileTransfer transfer = cfdpService.startUpload(
                    localEntity, bucket, objectName, remoteEntity, remotePath, options);
            pendingCommands.put(transfer.getId(), commandId);
            handleTerminalState(transfer);
        } catch (Exception e) {
            acknowledge(commandId, AckStatus.NOK, "Could not start CFDP upload: " + e.getMessage());
        }
    }

    @Override
    public void stateChanged(FileTransfer transfer) {
        handleTerminalState(transfer);
    }

    private void handleTerminalState(FileTransfer transfer) {
        CommandId commandId = pendingCommands.get(transfer.getId());
        if (commandId == null) {
            return;
        }

        TransferState state = transfer.getTransferState();
        if (state == TransferState.COMPLETED) {
            if (pendingCommands.remove(transfer.getId(), commandId)) {
                acknowledge(commandId, AckStatus.OK, "CFDP upload completed");
            }
        } else if (state == TransferState.FAILED || state == TransferState.PAUSED) {
            if (pendingCommands.remove(transfer.getId(), commandId)) {
                String reason = transfer.getFailuredReason();
                if (state == TransferState.PAUSED && transfer.cancellable()) {
                    cfdpService.cancel(transfer);
                }
                acknowledge(commandId, AckStatus.NOK,
                        reason == null
                                ? "CFDP upload " + state.name().toLowerCase()
                                : "CFDP upload failed: " + reason);
            }
        }
    }

    private void acknowledge(CommandId commandId, AckStatus status, String message) {
        long missionTime = YamcsServer.getTimeService(yamcsInstance).getMissionTime();
        commandHistory.publishAck(
                commandId,
                CommandHistoryPublisher.AcknowledgeSent_KEY,
                missionTime,
                status,
                message);
    }
}
