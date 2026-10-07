package com.volkyanothai.ezexam;
import android.content.Context;
import android.webkit.WebView;
import android.app.Instrumentation;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.rule.ActivityTestRule;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.junit.Test;
import org.junit.Rule;
import org.junit.runner.RunWith;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class SmokeTest {
    @Rule public ActivityTestRule<MainActivity> activity = new ActivityTestRule<>(MainActivity.class);
    @Test public void pythonCoreAndImageCodecWorkOnAndroid() {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        if (!Python.isStarted()) Python.start(new AndroidPlatform(context));
        assertEquals("ok", Python.getInstance().getModule("android_bridge").callAttr("self_test").toString());
    }
    @Test public void bundledInterfaceLoadsWithAndroidBridge() throws Exception {
        Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        String[] result = new String[1];
        boolean loaded = false;
        for (int attempt = 0; attempt < 30 && !loaded; attempt++) {
            CountDownLatch latch = new CountDownLatch(1);
            instrumentation.runOnMainSync(() -> {
                // Activity content root contains the app's single WebView.
                android.view.ViewGroup root = activity.getActivity().findViewById(android.R.id.content);
                ((WebView) root.getChildAt(0)).evaluateJavascript(
                    "document.readyState === 'complete' && typeof window.Android === 'object' && " +
                    "typeof window.nativeEvent === 'function' && document.getElementById('load') !== null",
                    value -> { result[0] = value; latch.countDown(); });
            });
            assertTrue(latch.await(10, TimeUnit.SECONDS));
            loaded = "true".equals(result[0]);
            if (!loaded) Thread.sleep(500);
        }
        assertTrue("Bundled HTML/JS and native bridge loaded", loaded);
        instrumentation.runOnMainSync(() -> {
            android.view.ViewGroup root = activity.getActivity().findViewById(android.R.id.content);
            ((WebView) root.getChildAt(0)).evaluateJavascript(
                "window.testImageLoaded=false;let image=new Image();" +
                "image.onload=()=>{window.testImageLoaded=image.naturalWidth>0;};" +
                "image.src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQ0AAAAASUVORK5CYII=';",
                null);
        });
        boolean imageLoaded = false;
        for (int attempt = 0; attempt < 20 && !imageLoaded; attempt++) {
            CountDownLatch latch = new CountDownLatch(1);
            instrumentation.runOnMainSync(() -> {
                android.view.ViewGroup root = activity.getActivity().findViewById(android.R.id.content);
                ((WebView) root.getChildAt(0)).evaluateJavascript("window.testImageLoaded",
                    value -> { result[0] = value; latch.countDown(); });
            });
            assertTrue(latch.await(10, TimeUnit.SECONDS));
            imageLoaded = "true".equals(result[0]);
            if (!imageLoaded) Thread.sleep(250);
        }
        assertTrue("Embedded question images render in the WebView", imageLoaded);
    }
}
