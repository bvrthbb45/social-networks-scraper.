# The JavaScript bridge is looked up by name from the page; keep exactly its annotated methods.
-keepclassmembers class app.opsec.monitor.DownloadBridge {
    @android.webkit.JavascriptInterface <methods>;
}
