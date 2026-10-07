package com.volkyanothai.ezexam;

import android.app.Instrumentation;
import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class SmokeTest {
    @Rule public ActivityTestRule<MainActivity> activity = new ActivityTestRule<>(MainActivity.class);

    private String evaluate(String script) throws Exception {
        String[] result = new String[1];
        CountDownLatch latch = new CountDownLatch(1);
        Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        instrumentation.runOnMainSync(() ->
            activity.getActivity().webViewForTest().evaluateJavascript(script,
                value -> { result[0] = value; latch.countDown(); }));
        assertTrue(latch.await(10, TimeUnit.SECONDS));
        return result[0];
    }

    private String evaluateLive(String script) throws Exception {
        // Community Cloud embeds Streamlit at /~/+/ on the same origin.
        return evaluate("(function(document){return (" + script + ");})(" +
            "document.querySelector('iframe[title=streamlitApp]')?.contentDocument || document)");
    }

    private void awaitTrue(String script) throws Exception {
        for (int attempt = 0; attempt < 60; attempt++) {
            if ("true".equals(evaluate(script))) return;
            Thread.sleep(250);
        }
        fail("WebView condition timed out: " + script);
    }

    @Test public void configuredLiveWebsiteShowsTheOriginalFormUi() throws Exception {
        org.junit.Assume.assumeFalse("No deployment URL supplied yet",
            "example.invalid".equals(Uri.parse(BuildConfig.WEB_APP_URL).getHost()));
        // Read the real UI only; do not invoke Gemini or submit any form.
        boolean formVisible = false;
        for (int attempt = 0; attempt < 240 && !formVisible; attempt++) {
            formVisible = "true".equals(evaluateLive(
                "document.querySelector('input[placeholder=\\\"https://forms.gle/...\\\"]')!==null"));
            if (!formVisible) {
                if (attempt % 20 == 0) {
                    System.out.println("WEB_PAGE_DIAGNOSTICS " + evaluateLive(
                        "JSON.stringify({title:document.title,url:location.origin+location.pathname," +
                        "body:document.body.innerText.slice(0,1200),agent:navigator.userAgent})"));
                }
                evaluateLive("Array.from(document.querySelectorAll('button')).find(" +
                    "b=>['เริ่มต้นใช้งาน','Yes, get this app back up!'].includes(b.textContent.trim()))?.click()");
                Thread.sleep(1000);
            }
        }
        String diagnostics = evaluateLive("JSON.stringify({url:location.origin+location.pathname," +
            "title:document.title,body:document.body.innerText.slice(0,1800),agent:navigator.userAgent})");
        assertTrue("Hosted EZEXAM form did not load. Page diagnostics: " + diagnostics, formVisible);
        assertEquals("true", evaluateLive("document.querySelector('input[type=password]')===null"));
    }

    @Test public void onlyAppOriginAndExpectedCloudAuthRemainInApp() {
        Uri home = Uri.parse(BuildConfig.WEB_APP_URL);
        assertTrue(WebNavigation.inApp(home));
        assertEquals("android", Uri.parse(WebNavigation.startUrl()).getQueryParameter("client"));
        assertFalse(WebNavigation.inApp(Uri.parse("https://docs.google.com/forms/d/e/123/viewform")));
        assertFalse(WebNavigation.inApp(Uri.parse("https://" + home.getHost() + ".evil.example/")));
        assertFalse(WebNavigation.inApp(Uri.parse("https://" + home.getHost() + "@evil.example/")));
        assertFalse(WebNavigation.inApp(Uri.parse("http://" + home.getHost() + "/")));
        assertFalse(WebNavigation.inApp(Uri.parse("javascript:alert(1)")));
    }

    @Test public void remoteWebUiSupportsJavascriptStorageAndUploadsWithoutNativeKeyBridge() throws Exception {
        Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        instrumentation.runOnMainSync(() -> {
            WebView web = activity.getActivity().webViewForTest();
            web.stopLoading();
            web.setWebViewClient(new WebViewClient() {
                @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                    String html = "<!doctype html><html lang='th'><head><meta name='viewport' " +
                        "content='width=device-width,initial-scale=1'></head><body>" +
                        "<h1>EZEXAM</h1><input id='form' placeholder='https://forms.gle/...'>" +
                        "<input id='picture' type='file' accept='image/*'>" +
                        "<button id='analyze'>เริ่มวิเคราะห์</button><p id='result'></p>" +
                        "<script>document.getElementById('analyze').onclick=()=>{" +
                        "document.getElementById('result').textContent=document.getElementById('form').value;};" +
                        "sessionStorage.setItem('session-test','works');</script></body></html>";
                    return new WebResourceResponse("text/html", "UTF-8",
                        new ByteArrayInputStream(html.getBytes(StandardCharsets.UTF_8)));
                }
            });
            web.loadUrl(WebNavigation.startUrl());
        });
        awaitTrue("document.readyState==='complete' && document.getElementById('form')!==null");
        assertEquals("true", evaluate(
            "typeof window.Android==='undefined' && " +
            "sessionStorage.getItem('session-test')==='works' && " +
            "document.querySelector('input[type=password]')===null && " +
            "document.getElementById('picture').type==='file'"));
        evaluate("document.getElementById('form').value='https://forms.gle/test';" +
            "document.getElementById('analyze').click()");
        assertEquals("\"https://forms.gle/test\"", evaluate("document.getElementById('result').textContent"));
        instrumentation.runOnMainSync(() -> {
            WebView web = activity.getActivity().webViewForTest();
            assertTrue(web.getSettings().getDomStorageEnabled());
            assertTrue(web.getSettings().getJavaScriptEnabled());
            assertFalse(web.getSettings().getAllowFileAccess());
        });
    }
}
