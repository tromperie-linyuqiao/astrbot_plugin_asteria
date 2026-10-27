package com.asteria.chat;

import java.net.URI;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;

/** System trust first; an optional exact leaf pin applies only to the compiled default origin. */
final class PinnedTls {
    private PinnedTls() { }

    static void configure(HttpsURLConnection connection, String server) throws Exception {
        final String pin = BuildConfig.DEFAULT_CERT_SHA256;
        if (pin.isEmpty() || !BuildConfig.DEFAULT_SERVER.equals(server)) return;
        final String host = URI.create(BuildConfig.DEFAULT_SERVER).getHost();
        TrustManagerFactory factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        factory.init((KeyStore) null);
        X509TrustManager found = null;
        for (TrustManager manager : factory.getTrustManagers())
            if (manager instanceof X509TrustManager) found = (X509TrustManager) manager;
        if (found == null) throw new IllegalStateException("system_trust_unavailable");
        final X509TrustManager system = found;
        X509TrustManager manager = new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return system.getAcceptedIssuers(); }
            public void checkClientTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                system.checkClientTrusted(chain, authType);
            }
            public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
                try { system.checkServerTrusted(chain, authType); }
                catch (CertificateException rejected) {
                    if (chain == null || chain.length == 0 || !matches(chain[0], pin)) throw rejected;
                    chain[0].checkValidity();
                }
            }
        };
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, new TrustManager[] { manager }, null);
        connection.setSSLSocketFactory(context.getSocketFactory());
        final HostnameVerifier normal = HttpsURLConnection.getDefaultHostnameVerifier();
        connection.setHostnameVerifier((hostname, session) -> {
            if (normal.verify(hostname, session)) return true;
            if (!host.equalsIgnoreCase(hostname)) return false;
            try {
                java.security.cert.Certificate[] peers = session.getPeerCertificates();
                return peers.length > 0 && peers[0] instanceof X509Certificate
                        && matches((X509Certificate) peers[0], pin);
            } catch (Exception rejected) { return false; }
        });
    }

    private static boolean matches(X509Certificate cert, String pin) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(cert.getEncoded());
            byte[] expected = new byte[32];
            if (!pin.matches("[0-9a-fA-F]{64}")) return false;
            for (int i = 0; i < expected.length; i++)
                expected[i] = (byte) Integer.parseInt(pin.substring(i * 2, i * 2 + 2), 16);
            return MessageDigest.isEqual(digest, expected);
        } catch (Exception rejected) { return false; }
    }
}
