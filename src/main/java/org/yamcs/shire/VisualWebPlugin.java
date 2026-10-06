package org.yamcs.shire;

import java.nio.file.Path;
import org.yamcs.AbstractPlugin;
import org.yamcs.PluginException;
import org.yamcs.YamcsServer;
import org.yamcs.http.HttpServer;
import org.yamcs.http.HandlerContext;
import org.yamcs.http.StaticFileHandler;

/** Serves the offline viewer on Yamcs's own authenticated HTTP origin. */
public class VisualWebPlugin extends AbstractPlugin {
    @Override
    public void init() throws PluginException {
        HttpServer server = YamcsServer.getServer().getGlobalService(HttpServer.class);
        if (server == null) {
            throw new PluginException("SHIRE visualization requires Yamcs HTTP server");
        }
        Path root = Path.of("/app/shire-static/visualization");
        server.addRoute("visualization", () -> new StaticFileHandler("visualization", root) {
            @Override
            protected String getFilePath(HandlerContext context) {
                String path = super.getFilePath(context);
                return path.equals("/") ? "index.html" : path.replaceFirst("^/", "");
            }
            @Override
            public boolean requireAuth() {
                return true;
            }
        });
    }
}
