package org.yamcs.shire;

import java.net.SocketException;
import org.yamcs.tctm.UdpTmDataLink;

/** Increase the kernel receive queue for accelerated visualization bursts. */
public class BufferedVisualTmDataLink extends UdpTmDataLink {
    private static final int RECEIVE_BUFFER_BYTES = 4 * 1024 * 1024;

    @Override
    public void doEnable() throws SocketException {
        super.doEnable();
        tmSocket.setReceiveBufferSize(RECEIVE_BUFFER_BYTES);
        log.info("Visualization UDP receive buffer: {} bytes", tmSocket.getReceiveBufferSize());
    }
}
