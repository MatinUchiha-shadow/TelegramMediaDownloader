package ir.freebuff.tgviewer;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {

    private WebView webView;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        setContentView(webView);

        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setAllowContentAccess(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setDatabaseEnabled(true);
        webView.getSettings().setAllowFileAccessFromFileURLs(true);
        webView.getSettings().setAllowUniversalAccessFromFileURLs(true);
        webView.getSettings().setLoadWithOverviewMode(true);
        webView.getSettings().setUseWideViewPort(true);
        // زوم (پینچ/دابل‌تپ) کاملاً غیرفعال است — فقط خود app.js زوم عکس را دارد
        webView.getSettings().setSupportZoom(false);
        webView.getSettings().setBuiltInZoomControls(false);
        webView.getSettings().setDisplayZoomControls(false);
        webView.getSettings().setTextZoom(100);

        // حافظه مطمئن اندروید برای ذخیره اسکرول (حتی اگر localStorage file:// پاک شد)
        try {
            webView.addJavascriptInterface(new ScrollStore(), "AndroidStore");
        } catch (Exception ignored) {}

        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url.startsWith("file://") || url.startsWith("about:")) {
                    view.loadUrl(url);
                    return true;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                }
                return true;
            }
        });
        webView.loadUrl("file:///android_asset/www/index.html");
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) {
            try {
                // ذخیره ثانیه‌به‌ثانیه — هم y خام، هم payload کامل با کلید درست چت
                int y = webView.getScrollY();
                getSharedPreferences("tg_scroll", MODE_PRIVATE).edit().putString("webview_y", String.valueOf(y)).apply();
                // ذخیره با کلید درست چت از داخل JS (دقیق‌ترین)
                webView.evaluateJavascript("(function(){ try{ if(typeof saveNow==='function') saveNow(); var k=(typeof commonKey==='function'?commonKey():'tgpos_'+location.pathname); var yy=window.pageYOffset||document.documentElement.scrollTop||0; var p=JSON.stringify({y:yy,t:Date.now()}); try{ AndroidStore.savePos(k,p); AndroidStore.savePos('tg_last_pos',p); }catch(e){} }catch(e){} })();", null);
            } catch (Exception ignored) {}
            webView.onPause();
        }
    }
    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }
    @Override
    protected void onDestroy() {
        if (webView != null) {
            try {
                int y = webView.getScrollY();
                getSharedPreferences("tg_scroll", MODE_PRIVATE).edit().putString("webview_y", String.valueOf(y)).apply();
                webView.evaluateJavascript("(function(){ try{ if(typeof saveNow==='function') saveNow(); }catch(e){} })();", null);
            } catch (Exception ignored) {}
        }
        super.onDestroy();
    }

    // کلاس حافظه مطمئن اسکرول — JS صدا میزند AndroidStore.savePos / loadPos
    public class ScrollStore {
        @JavascriptInterface
        public void savePos(String key, String val) {
            try {
                SharedPreferences p = getSharedPreferences("tg_scroll", MODE_PRIVATE);
                p.edit().putString(key, val).apply();
            } catch (Exception ignored) {}
        }
        @JavascriptInterface
        public String loadPos(String key) {
            try {
                SharedPreferences p = getSharedPreferences("tg_scroll", MODE_PRIVATE);
                return p.getString(key, null);
            } catch (Exception e) { return null; }
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView != null && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
