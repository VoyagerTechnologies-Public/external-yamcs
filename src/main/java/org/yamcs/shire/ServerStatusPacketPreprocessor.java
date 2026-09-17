package org.yamcs.shire;

import java.nio.ByteBuffer;

import org.yamcs.TmPacket;
import org.yamcs.YConfiguration;
import org.yamcs.tctm.AbstractPacketPreprocessor;
import org.yamcs.utils.TimeEncoding;

/**
 * Parses the Simulith Server's raw pause/speed status heartbeat (paused:uint8,
 * speed:float64, sim_time_ns:uint64, little-endian, no CCSDS header). Unlike
 * {@link Truth42PacketPreprocessor}, this link is not a simulation time
 * source, so the packet's generation time is simply "now".
 */
public class ServerStatusPacketPreprocessor extends AbstractPacketPreprocessor {
    private static final int EXPECTED_SIZE = 17; // paused(1) + speed(8) + sim_time_ns(8)

    public ServerStatusPacketPreprocessor(String yamcsInstance) {
        this(yamcsInstance, YConfiguration.emptyConfig());
    }

    public ServerStatusPacketPreprocessor(String yamcsInstance, YConfiguration config) {
        super(yamcsInstance, config);
    }

    @Override
    public TmPacket process(TmPacket packet) {
        byte[] bytes = packet.getPacket();
        if (bytes.length < EXPECTED_SIZE) {
            log.warn("Short packet of {} bytes (expected {})", bytes.length, EXPECTED_SIZE);
            return null;
        }

        ByteBuffer bb = ByteBuffer.wrap(bytes);
        bb.order(java.nio.ByteOrder.LITTLE_ENDIAN);

        // Parsed for validation only; the XTCE container decodes PAUSED/SPEED/SIM_TIME_NS.
        bb.get();
        bb.getDouble();
        bb.getLong();

        packet.setGenerationTime(TimeEncoding.getWallclockTime());
        return packet;
    }
}
