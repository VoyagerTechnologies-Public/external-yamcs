package org.yamcs.shire;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.util.concurrent.TimeUnit;

import org.yamcs.commanding.PreparedCommand;
import org.yamcs.tctm.UdpTcDataLink;

/**
 * UDP command link for peers that join the Compose network after Yamcs starts.
 * The stock link resolves its destination once at startup and cannot recover
 * when Docker DNS does not yet know that container.
 */
public class DeferredUdpTcDataLink extends UdpTcDataLink {
    private static final long RESOLVE_TIMEOUT_NS = TimeUnit.SECONDS.toNanos(10);

    @Override
    protected void startUp() {
        // Resolve on send, after the destination container joins the network.
    }

    @Override
    public void shutDown() {
        if (socket != null) {
            socket.close();
            socket = null;
        }
    }

    @Override
    public void uplinkCommand(PreparedCommand command) throws IOException {
        byte[] binary = postprocess(command);
        if (binary == null) {
            return;
        }

        long deadline = System.nanoTime() + RESOLVE_TIMEOUT_NS;
        InetAddress destination;
        while (true) {
            try {
                destination = InetAddress.getByName(host);
                break;
            } catch (java.net.UnknownHostException e) {
                if (System.nanoTime() >= deadline) {
                    throw e;
                }
                try {
                    Thread.sleep(250);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IOException("Interrupted while resolving " + host, interrupted);
                }
            }
        }

        if (socket == null) {
            socket = new DatagramSocket();
        }
        socket.send(new DatagramPacket(binary, binary.length, destination, port));
        dataOut(1, binary.length);
        ackCommand(command.getCommandId());
    }
}
