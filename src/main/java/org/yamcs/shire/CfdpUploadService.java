package org.yamcs.shire;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.List;
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
import org.yamcs.cmdhistory.protobuf.Cmdhistory.Assignment;
import org.yamcs.cmdhistory.protobuf.Cmdhistory.AssignmentInfo;
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
 * Turns ground commands into CFDP uploads.
 *
 * <p>Two commands are handled. {@code /CCSDS/CFDP_UPLOAD_CHECKOUT} uploads the checkout stack's fixed payload.
 * {@code /CCSDS/CFDP_UPLOAD} uploads any object already in the upload bucket to a path the command names, which is
 * how a procedure uplinks a table or a patch that was built with the flight software.
 *
 * <p>The commands are routed to a dedicated Yamcs stream, so they are never sent to
 * the spacecraft as telecommands. Acknowledge_Sent is published only after the
 * CFDP transaction completes, which makes the stack wait without operator input.
 */
public class CfdpUploadService extends AbstractYamcsService
        implements StreamSubscriber, TransferMonitor {

    private static final String CHECKOUT_COMMAND = "/CCSDS/CFDP_UPLOAD_CHECKOUT";
    private static final String UPLOAD_COMMAND = "/CCSDS/CFDP_UPLOAD";
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
    private List<String> remotePrefixes;

    @Override
    public void init(String yamcsInstance, String serviceName, YConfiguration config) throws InitException {
        super.init(yamcsInstance, serviceName, config);

        bucketName = config.getString("bucket", "cfdpUp");
        objectName = config.getString("objectName", "AdcsComponent.ycs");
        remotePath = config.getString("remotePath", "/d/checkout_adcs.ycs");
        localEntity = config.getString("localEntity", "GSW");
        remoteEntity = config.getString("remoteEntity", "FSW");
        // A parameterized upload may only write where uploads belong, never over flight software in /cf.
        remotePrefixes = config.containsKey("remotePrefixes") ? config.<String>getList("remotePrefixes") : List.of("/d/");
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

        String commandName = commandId.getCommandName();
        if (UPLOAD_COMMAND.equals(commandName)) {
            uploadBucketObject(commandId, tuple);
        } else if (CHECKOUT_COMMAND.equals(commandName)) {
            uploadCheckoutPayload(commandId);
        } else {
            acknowledge(commandId, AckStatus.NOK, "Unsupported upload control command");
        }
    }

    private void uploadCheckoutPayload(CommandId commandId) {
        try (InputStream in = getClass().getResourceAsStream(PAYLOAD_RESOURCE)) {
            if (in == null) {
                throw new IOException("Missing checkout payload " + PAYLOAD_RESOURCE);
            }
            byte[] payload = in.readAllBytes();
            Bucket bucket = uploadBucket();

            bucket.putObjectAsync(objectName, "application/json", Map.of(), payload)
                    .whenComplete((unused, error) -> {
                        if (error != null) {
                            acknowledge(commandId, AckStatus.NOK,
                                    "Could not stage CFDP upload: " + error.getMessage());
                            return;
                        }
                        startUpload(commandId, bucket, objectName, remotePath);
                    });
        } catch (Exception e) {
            acknowledge(commandId, AckStatus.NOK, "Could not stage CFDP upload: " + e.getMessage());
        }
    }

    private void uploadBucketObject(CommandId commandId, Tuple tuple) {
        try {
            Map<String, String> arguments = new HashMap<>();
            // The stream tuple already carries the command's argument assignments.
            AssignmentInfo info = (AssignmentInfo) tuple.getColumn(PreparedCommand.CNAME_ASSIGNMENTS);
            if (info != null) {
                for (Assignment assignment : info.getAssignmentList()) {
                    arguments.put(assignment.getName(), assignment.getValue().getStringValue());
                }
            }
            String object = arguments.getOrDefault("OBJECT_NAME", "");
            String path = arguments.getOrDefault("REMOTE_PATH", "");
            String problem = validate(object, path);
            if (problem != null) {
                acknowledge(commandId, AckStatus.NOK, problem);
                return;
            }

            Bucket bucket = uploadBucket();
            bucket.findObjectAsync(object).whenComplete((properties, error) -> {
                if (error != null || properties == null) {
                    acknowledge(commandId, AckStatus.NOK,
                            "No object " + object + " in bucket " + bucketName);
                    return;
                }
                startUpload(commandId, bucket, object, path);
            });
        } catch (Exception e) {
            acknowledge(commandId, AckStatus.NOK, "Could not start CFDP upload: " + e.getMessage());
        }
    }

    /** Returns why an upload request is refused, or null when it is acceptable. */
    String validate(String object, String path) {
        return UploadRequestValidation.problem(object, path, remotePrefixes);
    }

    private Bucket uploadBucket() throws IOException {
        Bucket bucket = YamcsServer.getServer().getBucketManager().getBucket(bucketName);
        if (bucket == null) {
            throw new IOException("Unknown Yamcs bucket " + bucketName);
        }
        return bucket;
    }

    private void startUpload(CommandId commandId, Bucket bucket, String object, String path) {
        try {
            TransferOptions options = new TransferOptions();
            options.setReliable(true);
            options.setOverwrite(true);
            options.setCreatePath(true);

            FileTransfer transfer = cfdpService.startUpload(
                    localEntity, bucket, object, remoteEntity, path, options);
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
