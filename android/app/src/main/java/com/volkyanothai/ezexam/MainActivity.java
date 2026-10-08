package com.volkyanothai.ezexam;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Message;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import java.security.KeyStore;

/** Displays the actual deployed UI. Gemini credentials stay on its server. */
public class MainActivity extends Activity {
    private static final int FILE_PICKER = 901;
    private static final int BACKGROUND = Color.rgb(10, 18, 40);
    private WebView web;
    private ProgressBar progress;
    private LinearLayout errorPanel;
    private TextView errorMessage;
    private ValueCallback<Uri[]> fileCallback;
    private boolean mainLoadFailed;
    private boolean exitPending;
    private boolean rendererGone;

    @Override public void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        clearLegacyCredentials();
        getWindow().setStatusBarColor(BACKGROUND);
        getWindow().setNavigationBarColor(BACKGROUND);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BACKGROUND);
        setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
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

        web = new WebView(this);
        web.setBackgroundColor(BACKGROUND);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        FrameLayout.LayoutParams progressLayout = new FrameLayout.LayoutParams(-1, dp(3), Gravity.TOP);
        root.addView(progress, progressLayout);
        createErrorPanel(root);

        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setSupportMultipleWindows(true);
        web.getSettings().setJavaScriptCanOpenWindowsAutomatically(false);
        web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (android.os.Build.VERSION.SDK_INT >= 26) web.getSettings().setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);
        web.setWebViewClient(new AppWebClient());
        web.setWebChromeClient(new AppChromeClient());
        web.setDownloadListener((url, userAgent, disposition, mime, length) -> openBrowser(Uri.parse(url)));

        // A fresh session opens the form entry stage. Restoring rotation keeps
        // the current WebSocket-backed Streamlit session and edited answers.
        if (savedState == null || web.restoreState(savedState) == null) loadHome();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void createErrorPanel(FrameLayout root) {
        errorPanel = new LinearLayout(this);
        errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setGravity(Gravity.CENTER);
        errorPanel.setPadding(dp(28), dp(28), dp(28), dp(28));
        errorPanel.setBackgroundColor(BACKGROUND);
        TextView title = new TextView(this);
        title.setText("EZEXAM");
        title.setTextSize(30);
        title.setTextColor(Color.rgb(127, 179, 255));
        title.setGravity(Gravity.CENTER);
        errorPanel.addView(title);
        errorMessage = new TextView(this);
        errorMessage.setTextColor(Color.rgb(234, 240, 255));
        errorMessage.setTextSize(16);
        errorMessage.setGravity(Gravity.CENTER);
        errorMessage.setPadding(0, dp(18), 0, dp(18));
        errorPanel.addView(errorMessage);
        Button retry = new Button(this);
        retry.setText("ลองเชื่อมต่ออีกครั้ง");
        retry.setOnClickListener(view -> loadHome());
        errorPanel.addView(retry);
        Button browser = new Button(this);
        browser.setText("เปิดเว็บในเบราว์เซอร์");
        browser.setOnClickListener(view -> openBrowser(Uri.parse(WebNavigation.startUrl())));
        errorPanel.addView(browser);
        errorPanel.setVisibility(View.GONE);
        root.addView(errorPanel, new FrameLayout.LayoutParams(-1, -1));
    }

    private void loadHome() {
        if (rendererGone) { recreate(); return; }
        mainLoadFailed = false;
        errorPanel.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
        progress.setVisibility(View.VISIBLE);
        web.loadUrl(WebNavigation.startUrl());
    }

    private void showLoadError(String message) {
        mainLoadFailed = true;
        progress.setVisibility(View.GONE);
        errorMessage.setText(message);
        errorPanel.setVisibility(View.VISIBLE);
    }

    private void openBrowser(Uri uri) {
        if (!WebNavigation.isHttps(uri)) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (ActivityNotFoundException error) {
            Toast.makeText(this, "ไม่พบเบราว์เซอร์สำหรับเปิดลิงก์", Toast.LENGTH_LONG).show();
        }
    }

    private class AppWebClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (!request.isForMainFrame()) return false;
            if (WebNavigation.inApp(request.getUrl())) return false;
            openBrowser(request.getUrl());
            return true;
        }
        @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
            mainLoadFailed = false;
            errorPanel.setVisibility(View.GONE);
            progress.setVisibility(View.VISIBLE);
        }
        @Override public void onPageFinished(WebView view, String url) {
            if (!mainLoadFailed) progress.setVisibility(View.GONE);
            CookieManager.getInstance().flush();
        }
        @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                showLoadError("เชื่อมต่อ EZEXAM ไม่สำเร็จ ตรวจสอบอินเทอร์เน็ตแล้วลองอีกครั้ง");
            }
        }
        @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (request.isForMainFrame() && response.getStatusCode() >= 400) {
                showLoadError("เว็บไซต์ไม่พร้อมใช้งานในขณะนี้ (HTTP " + response.getStatusCode() + ") กรุณาลองอีกครั้ง");
            }
        }
        @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            handler.cancel();
            showLoadError("ตรวจสอบการเชื่อมต่อที่ปลอดภัยไม่ได้ กรุณาตรวจวันเวลาในเครื่องแล้วลองอีกครั้ง");
        }
        @Override public boolean onRenderProcessGone(WebView view, android.webkit.RenderProcessGoneDetail detail) {
            rendererGone = true;
            // Do not silently reload and lose an in-progress submission.
            showLoadError("หน้าจอหยุดทำงาน กรุณาปิดแล้วเปิดแอปใหม่ หากเพิ่งส่งคำตอบให้ตรวจใน Google Forms ก่อนส่งซ้ำ");
            web.setVisibility(View.GONE);
            return true;
        }
    }

    private class AppChromeClient extends WebChromeClient {
        @Override public void onProgressChanged(WebView view, int value) {
            progress.setProgress(value);
        }
        @Override public boolean onJsConfirm(WebView view, String url, String message, android.webkit.JsResult result) {
            new AlertDialog.Builder(MainActivity.this).setMessage(message)
                .setPositiveButton("ตกลง", (dialog, which) -> result.confirm())
                .setNegativeButton("ยกเลิก", (dialog, which) -> result.cancel())
                .setOnCancelListener(dialog -> result.cancel()).show();
            return true;
        }
        @Override public boolean onJsAlert(WebView view, String url, String message, android.webkit.JsResult result) {
            new AlertDialog.Builder(MainActivity.this).setMessage(message)
                .setPositiveButton("ตกลง", (dialog, which) -> result.confirm())
                .setOnCancelListener(dialog -> result.cancel()).show();
            return true;
        }
        @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                FileChooserParams params) {
            if (!WebNavigation.inApp(Uri.parse(view.getUrl() == null ? "" : view.getUrl()))) return false;
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = callback;
            try {
                // Uses the system picker with scoped URI access, no storage permission.
                startActivityForResult(params.createIntent(), FILE_PICKER);
                return true;
            } catch (ActivityNotFoundException error) {
                fileCallback = null;
                callback.onReceiveValue(null);
                Toast.makeText(MainActivity.this, "ไม่พบแอปสำหรับเลือกรูป", Toast.LENGTH_LONG).show();
                return true;
            }
        }
        @Override public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message message) {
            if (!isUserGesture) return false;
            WebView popup = new WebView(MainActivity.this);
            popup.setWebViewClient(new WebViewClient() {
                private boolean handled;
                private void open(String url) {
                    if (handled || "about:blank".equals(url)) return;
                    handled = true;
                    Uri uri = Uri.parse(url);
                    if (WebNavigation.inApp(uri)) web.loadUrl(url);
                    else openBrowser(uri);
                    popup.post(popup::destroy);
                }
                @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    open(request.getUrl().toString());
                    return true;
                }
                @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                    open(url);
                }
            });
            ((WebView.WebViewTransport) message.obj).setWebView(popup);
            message.sendToTarget();
            return true;
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == FILE_PICKER && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
        }
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        if (!rendererGone) web.saveState(state);
        super.onSaveInstanceState(state);
    }
    @Override protected void onPause() {
        CookieManager.getInstance().flush();
        super.onPause();
    }
    @Override public void onBackPressed() {
        if (web.canGoBack()) { web.goBack(); return; }
        if (exitPending) return;
        exitPending = true;
        new AlertDialog.Builder(this).setTitle("ออกจาก EZEXAM?")
            .setMessage("คำตอบที่ยังไม่ได้ส่งอาจหายเมื่อปิดแอป")
            .setPositiveButton("ออก", (dialog, which) -> finish())
            .setNegativeButton("อยู่ต่อ", (dialog, which) -> exitPending = false)
            .setOnCancelListener(dialog -> exitPending = false).show();
    }
    private void clearLegacyCredentials() {
        getPreferences(MODE_PRIVATE).edit().remove("gemini").apply();
        try {
            KeyStore keys = KeyStore.getInstance("AndroidKeyStore");
            keys.load(null);
            if (keys.containsAlias("ezexam-gemini")) keys.deleteEntry("ezexam-gemini");
        } catch (Exception ignored) { }
    }
    @Override protected void onDestroy() {
        if (fileCallback != null) fileCallback.onReceiveValue(null);
        web.stopLoading();
        web.destroy();
        super.onDestroy();
    }

    // Package-private access for instrumentation; never exposed to web JavaScript.
    WebView webViewForTest() { return web; }
}
