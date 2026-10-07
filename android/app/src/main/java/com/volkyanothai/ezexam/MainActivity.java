package com.volkyanothai.ezexam;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.webkit.WebViewAssetLoader;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Only bundled assets can reach the Python bridge. Remote links open externally. */
public class MainActivity extends Activity {
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private static final String KEY_ALIAS = "ezexam-gemini";
    private WebView web;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean busy = new AtomicBoolean(false);
    private volatile boolean destroyed = false;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(10,18,40));
        getWindow().setNavigationBarColor(Color.rgb(10,18,40));
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(10,18,40));
        setContentView(web);
        // Android 15 enforces edge-to-edge: keep controls above bars and keyboard.
        web.setOnApplyWindowInsetsListener((view, insets) -> {
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            } else {
                view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(false);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (android.os.Build.VERSION.SDK_INT >= 26) web.getSettings().setSafeBrowsingEnabled(true);
        web.setWebChromeClient(new android.webkit.WebChromeClient() {
            @Override public boolean onJsConfirm(WebView view, String url, String message,
                    android.webkit.JsResult result) {
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("ตกลง", (d, w) -> result.confirm())
                    .setNegativeButton("ยกเลิก", (d, w) -> result.cancel())
                    .setOnCancelListener(d -> result.cancel()).show();
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "Android");
        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this)).build();
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                WebResourceResponse asset = loader.shouldInterceptRequest(request.getUrl());
                if (asset != null) return asset;
                return new WebResourceResponse("text/plain", "UTF-8",
                    new java.io.ByteArrayInputStream(new byte[0]));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (ORIGIN.equals(uri.getScheme() + "://" + uri.getAuthority()) &&
                    uri.getPath().startsWith("/assets/")) return false;
                openExternal(uri.toString());
                return true;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (url.equals(ORIGIN + "/assets/index.html")) {
                    boolean saved = getPreferences(MODE_PRIVATE).contains("gemini");
                    emit("ready", new JSONObject(), saved ? "บันทึก API Key ในเครื่องแล้ว" : "");
                }
            }
        });
        web.loadUrl(ORIGIN + "/assets/index.html");
    }

    private void emit(String event, JSONObject data, String message) {
        try {
            JSONObject result = new JSONObject().put("event", event).put("data", data).put("message", message);
            final String js = "window.nativeEvent(" + result.toString() + ")";
            runOnUiThread(() -> { if (!destroyed) web.evaluateJavascript(js, null); });
        } catch (Exception ignored) { }
    }

    private void openExternal(String value) {
        runOnUiThread(() -> {
            Uri uri = Uri.parse(value);
            if (!"https".equals(uri.getScheme()) || uri.getHost() == null) return;
            try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
            catch (Exception e) { emit("error", new JSONObject(), "ไม่พบเบราว์เซอร์สำหรับเปิดลิงก์"); }
        });
    }

    private SecretKey encryptionKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY_ALIAS, null);
    }

    private String savedKey() throws Exception {
        String saved = getPreferences(MODE_PRIVATE).getString("gemini", "");
        if (saved.isEmpty()) return "";
        String[] parts = saved.split(":");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, encryptionKey(),
            new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    private void saveKey(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, encryptionKey());
        String encrypted = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" +
            Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
        getPreferences(MODE_PRIVATE).edit().putString("gemini", encrypted).apply();
    }

    public class Progress {
        // Called on the worker / Python analysis threads.
        public void progress(String message) { emit("progress", new JSONObject(), message); }
    }

    public class Bridge {
        @JavascriptInterface public void open(String url) { openExternal(url); }
        @JavascriptInterface public void forgetKey() {
            getPreferences(MODE_PRIVATE).edit().remove("gemini").apply();
            emit("key", new JSONObject(), "ลบ API Key ที่บันทึกไว้แล้ว");
        }
        @JavascriptInterface public void request(String action, String input) {
            if (!java.util.Arrays.asList("load", "analyze", "prefill", "submit", "reset", "saveKey").contains(action)) return;
            if (!busy.compareAndSet(false, true)) {
                emit("progress", new JSONObject(), "กำลังทำงาน กรุณารอสักครู่"); return;
            }
            if ("submit".equals(action)) {
                runOnUiThread(() -> new AlertDialog.Builder(MainActivity.this)
                    .setTitle("ยืนยันส่ง Google Forms")
                    .setMessage("ส่งคำตอบและข้อมูลที่คุณตรวจแล้วไปยัง Google Forms ฟอร์มนี้จริงหรือไม่?")
                    .setPositiveButton("ยืนยันส่ง", (dialog, which) -> execute(action, input))
                    .setNegativeButton("ยกเลิก", (dialog, which) -> cancelled())
                    .setOnCancelListener(dialog -> cancelled()).show());
            } else execute(action, input);
        }
    }

    private void cancelled() {
        busy.set(false);
        emit("cancelled", new JSONObject(), "ยกเลิกการส่งแล้ว");
    }

    private void execute(String action, String input) {
        runOnUiThread(() -> web.setKeepScreenOn(true));
        worker.execute(() -> {
            try {
                JSONObject args = new JSONObject(input);
                String typed = args.optString("api_key", "").trim();
                if ("saveKey".equals(action)) {
                    if (typed.isEmpty()) throw new IllegalArgumentException("กรุณาใส่ API Key");
                    saveKey(typed);
                    emit("key", new JSONObject(), "บันทึก API Key แบบเข้ารหัสแล้ว");
                } else {
                    String key = "analyze".equals(action) ? (typed.isEmpty() ? savedKey() : typed) : "";
                    args.remove("api_key");
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(MainActivity.this));
                    PyObject module = Python.getInstance().getModule("android_bridge");
                    String output = module.callAttr("dispatch", action, args.toString(), key, new Progress()).toString();
                    emit(action, new JSONObject(output), "");
                }
            } catch (Exception error) {
                // Python messages never include keys; Java crypto failures get a generic message.
                String message = (error instanceof com.chaquo.python.PyException ||
                    error instanceof IllegalArgumentException) ? error.getMessage()
                    : "ไม่สามารถทำงานได้ กรุณาลองอีกครั้งหรือตั้งค่า API Key ใหม่";
                if (message == null) message = "เกิดข้อผิดพลาด กรุณาลองอีกครั้ง";
                if (message.length() > 600) message = message.substring(0,600);
                emit("error", new JSONObject(), message);
            } finally {
                busy.set(false);
                runOnUiThread(() -> { if (!destroyed) web.setKeepScreenOn(false); });
            }
        });
    }

    @Override public void onBackPressed() {
        if (busy.get()) {
            new AlertDialog.Builder(this).setMessage("กำลังทำงาน ออกจากแอปหรือไม่?")
                .setPositiveButton("ออก", (d,w) -> finish()).setNegativeButton("อยู่ต่อ", null).show();
        } else {
            web.evaluateJavascript("window.handleBack()", result -> {
                if ("false".equals(result)) super.onBackPressed();
            });
        }
    }
    @Override protected void onDestroy() {
        destroyed = true;
        web.removeJavascriptInterface("Android");
        web.destroy();
        worker.shutdown();
        super.onDestroy();
    }
}
