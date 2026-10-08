package com.volkyanothai.ezexam;

import android.net.Uri;

/** Navigation policy for the hosted EZEXAM UI; no API keys or native JS bridge. */
final class WebNavigation {
    static boolean isHttps(Uri uri) {
        return uri != null && "https".equalsIgnoreCase(uri.getScheme()) &&
            uri.getHost() != null && uri.getUserInfo() == null;
    }

    static boolean sameOrigin(Uri left, Uri right) {
        if (!isHttps(left) || !isHttps(right)) return false;
        int leftPort = left.getPort() == -1 ? 443 : left.getPort();
        int rightPort = right.getPort() == -1 ? 443 : right.getPort();
        return left.getHost().equalsIgnoreCase(right.getHost()) && leftPort == rightPort;
    }

    static boolean inApp(Uri uri) {
        Uri home = Uri.parse(BuildConfig.WEB_APP_URL);
        if (sameOrigin(uri, home)) return true;
        // Streamlit Cloud may establish an anonymous session through this
        // service before redirecting back to the app. Keep those cookies.
        return isHttps(uri) && home.getHost().endsWith(".streamlit.app") &&
            "share.streamlit.io".equalsIgnoreCase(uri.getHost()) &&
            (uri.getPort() == -1 || uri.getPort() == 443) &&
            uri.getPath() != null && uri.getPath().startsWith("/-/auth/");
    }

    static String startUrl() {
        Uri home = Uri.parse(BuildConfig.WEB_APP_URL);
        Uri.Builder builder = home.buildUpon().clearQuery();
        for (String key : home.getQueryParameterNames()) {
            if (!"client".equals(key)) {
                for (String value : home.getQueryParameters(key)) builder.appendQueryParameter(key, value);
            }
        }
        return builder.appendQueryParameter("client", "android").build().toString();
    }
}
