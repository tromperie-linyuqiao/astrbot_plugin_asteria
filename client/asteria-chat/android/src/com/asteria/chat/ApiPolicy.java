package com.asteria.chat;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** Pure policy: no network, storage or Android dependencies. */
public final class ApiPolicy {
    private ApiPolicy() { }

    public static String server(String value) {
        try {
            if (value == null || value.length() > 2048) throw new IllegalArgumentException("invalid_server");
            URI u = new URI(value.trim());
            if (!"https".equalsIgnoreCase(u.getScheme()) || u.getHost() == null
                    || u.getUserInfo() != null || u.getRawQuery() != null || u.getRawFragment() != null
                    || (u.getPort() != -1 && (u.getPort() < 1 || u.getPort() > 65535)))
                throw new IllegalArgumentException("https_server_required");
            String path = u.getPath() == null ? "" : u.getPath();
            safePath(path);
            while (path.endsWith("/")) path = path.substring(0, path.length() - 1);
            return new URI("https", null, u.getHost().toLowerCase(Locale.ROOT), u.getPort(),
                    path, null, null).toASCIIString();
        } catch (URISyntaxException e) {
            throw new IllegalArgumentException("invalid_server");
        }
    }

    public static String requestPath(String value) {
        try {
            if (value == null || value.length() > 8192 || !value.startsWith("/") || value.startsWith("//"))
                throw new IllegalArgumentException("invalid_path");
            URI u = new URI(value);
            if (u.isAbsolute() || u.getRawAuthority() != null || u.getRawFragment() != null)
                throw new IllegalArgumentException("invalid_path");
            String path = u.getPath();
            safePath(path);
            if (!("/auth/login".equals(path) || "/chat".equals(path) || path.startsWith("/chat/")
                    || "/v1".equals(path) || path.startsWith("/v1/")))
                throw new IllegalArgumentException("route_not_allowed");
            if (hasControl(value)) throw new IllegalArgumentException("invalid_path");
            return u.toASCIIString();
        } catch (URISyntaxException e) {
            throw new IllegalArgumentException("invalid_path");
        }
    }

    public static String method(String value) {
        String m = value == null ? "GET" : value.toUpperCase(Locale.ROOT);
        if (!(m.equals("GET") || m.equals("POST") || m.equals("PUT") || m.equals("DELETE")))
            throw new IllegalArgumentException("method_not_supported");
        return m;
    }

    public static boolean isLogin(String path) {
        return "/auth/login".equals(URI.create(path).getPath());
    }

    public static boolean sameOrigin(String first, String second) {
        URI a = URI.create(first), b = URI.create(second);
        int ap = a.getPort() == -1 ? 443 : a.getPort();
        int bp = b.getPort() == -1 ? 443 : b.getPort();
        return "https".equalsIgnoreCase(a.getScheme()) && "https".equalsIgnoreCase(b.getScheme())
                && a.getHost() != null && a.getHost().equalsIgnoreCase(b.getHost()) && ap == bp;
    }

    public static boolean jwt(String value) {
        return value != null && value.length() >= 16 && value.length() <= 65536
                && value.matches("[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+");
    }

    private static void safePath(String value) {
        if (value == null || value.indexOf('\\') >= 0 || value.indexOf('%') >= 0
                || value.contains("//") || hasControl(value)) throw new IllegalArgumentException("unsafe_path");
        for (String segment : value.split("/"))
            if (segment.equals(".") || segment.equals("..")) throw new IllegalArgumentException("unsafe_path");
    }

    private static boolean hasControl(String value) {
        for (int i = 0; i < value.length(); i++)
            if (value.charAt(i) <= 0x20 || value.charAt(i) == 0x7f) return true;
        return false;
    }
}
