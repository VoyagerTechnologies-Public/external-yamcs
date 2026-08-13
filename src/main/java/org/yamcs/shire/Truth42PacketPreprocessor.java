package org.yamcs.shire;

import java.nio.ByteBuffer;

import org.yamcs.TmPacket;
import org.yamcs.YConfiguration;
import org.yamcs.tctm.AbstractPacketPreprocessor;
import org.yamcs.utils.TimeEncoding;

public class Truth42PacketPreprocessor extends AbstractPacketPreprocessor {
    // Constructor used when this preprocessor is used without YAML configuration
    public Truth42PacketPreprocessor(String yamcsInstance) {
        this(yamcsInstance, YConfiguration.emptyConfig());
    }

    // Constructor used when this preprocessor is used with YAML configuration
    // (packetPreprocessorClassArgs)
    public Truth42PacketPreprocessor(String yamcsInstance, YConfiguration config) {
        super(yamcsInstance, config);
    }

    @Override
    public TmPacket process(TmPacket packet) {

        byte[] bytes = packet.getPacket();
        if (bytes.length < 276) { // Exact expected size for XTCE/C packet (34 doubles + 1 int = 34*8 + 4 = 276)
            log.warn("Short packet of {} bytes (expected 276)", bytes.length);
            return null;
        }

        ByteBuffer bb = ByteBuffer.wrap(bytes);
        bb.order(java.nio.ByteOrder.LITTLE_ENDIAN); // C default is little-endian

        // Parse fields in XTCE/C order
        double dyn_time = bb.getDouble();
        double[] pos_n = new double[3];
        for (int i = 0; i < 3; i++) pos_n[i] = bb.getDouble();
        double[] svb = new double[3];
        for (int i = 0; i < 3; i++) svb[i] = bb.getDouble();
        double[] bvb = new double[3];
        for (int i = 0; i < 3; i++) bvb[i] = bb.getDouble();
        double[] hvb = new double[3];
        for (int i = 0; i < 3; i++) hvb[i] = bb.getDouble();
        double[] wn = new double[3];
        for (int i = 0; i < 3; i++) wn[i] = bb.getDouble();
        double[] qn = new double[4];
        for (int i = 0; i < 4; i++) qn[i] = bb.getDouble();
        double mass = bb.getDouble();
        double[] cm = new double[3];
        for (int i = 0; i < 3; i++) cm[i] = bb.getDouble();
        double[][] inertia = new double[3][3];
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) inertia[i][j] = bb.getDouble();
        int eclipse = bb.getInt();
        double atmo_density = bb.getDouble();

        // Set generation time from dyn_time (seconds since J2000)
        // J2000 epoch: 2000-01-01T12:00:00 UTC
        long j2000UnixMillis = 946728000000L;
        long unixMillis = j2000UnixMillis + Math.round(dyn_time * 1000.0);
        packet.setGenerationTime(TimeEncoding.fromUnixMillisec(unixMillis));

        return packet;
    }

}
