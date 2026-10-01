package org.yamcs.shire;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import org.yamcs.TmPacket;
import org.yamcs.YConfiguration;
import org.yamcs.tctm.AbstractPacketPreprocessor;
import org.yamcs.utils.TimeEncoding;

/** Validates a SHIRE visualization packet and assigns 42's UTC generation time. */
public class VisualPacketPreprocessor extends AbstractPacketPreprocessor {
    private static final int SIZE = 256;
    private static final int MAGIC = 0x31564853;
    private static final long J2000_UNIX_MILLIS = 946728000000L;

    public VisualPacketPreprocessor(String instance) {
        this(instance, YConfiguration.emptyConfig());
    }

    public VisualPacketPreprocessor(String instance, YConfiguration config) {
        super(instance, config);
    }

    @Override
    public TmPacket process(TmPacket packet) {
        byte[] data = packet.getPacket();
        if (data.length != SIZE) {
            log.warn("Unexpected SHIRE visualization packet size: {}", data.length);
            return null;
        }
        ByteBuffer bytes = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        if (bytes.getInt() != MAGIC || bytes.getShort() != 1) {
            log.warn("Unsupported SHIRE visualization packet");
            return null;
        }
        double utc = bytes.getDouble(44); // header 36 + elapsed time 8
        if (!Double.isFinite(utc)) {
            log.warn("Non-finite SHIRE visualization UTC time");
            return null;
        }
        packet.setGenerationTime(TimeEncoding.fromUnixMillisec(
                J2000_UNIX_MILLIS + Math.round(utc * 1000.0)));
        return packet;
    }
}
