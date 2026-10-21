import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.IBinder;
import android.os.Bundle;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;

/** Task-local tool: accesses only this TV's installation policy as the existing ADB shell user. */
public final class TvInstallConfigTool {
    private static final Uri URI = Uri.parse("content://com.tcl.providers.config/InstallConfig");

    public static void main(String[] args) {
        try {
            run(args);
            System.exit(0);
        } catch (Throwable error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void run(String[] args) throws Exception {
        if (args.length < 1) throw new IllegalArgumentException("read or write required");
        // Use the same shell-user provider API as this firmware's stock `content` command.
        Class<?> am = Class.forName("android.app.ActivityManager");
        Class<?> iam = Class.forName("android.app.IActivityManager");
        Object service = am.getMethod("getService").invoke(null);
        IBinder token = new Binder();
        Object holder = iam.getMethod("getContentProviderExternal", String.class, int.class,
                IBinder.class, String.class).invoke(service, URI.getAuthority(), 0, token, "*cmd*");
        if (holder == null) throw new IllegalStateException("Provider unavailable");
        Object provider = holder.getClass().getField("provider").get(holder);
        Class<?> icp = Class.forName("android.content.IContentProvider");
        try {
          if ("read".equals(args[0])) {
            Class<?> cancel = Class.forName("android.os.ICancellationSignal");
            try (Cursor c = (Cursor) icp.getMethod("query", String.class, String.class, Uri.class,
                    String[].class, Bundle.class, cancel).invoke(provider, "com.android.shell", null,
                    URI, new String[]{"config_content"}, new Bundle(), null)) {
                if (c == null || !c.moveToFirst()) throw new IllegalStateException("Policy missing");
                System.out.println("POLICY=" + c.getString(0));
            }
          } else if ("write".equals(args[0]) && args.length == 2) {
            String json = new String(Base64.decode(args[1], Base64.DEFAULT), StandardCharsets.UTF_8);
            JSONArray policy = new JSONArray(json);
            if (policy.length() != 1 || !policy.getJSONObject(0).has("strategies")) {
                throw new IllegalArgumentException("Unexpected installation policy");
            }
            ContentValues values = new ContentValues();
            values.put("config_content", json);
            int count = (Integer) icp.getMethod("update", String.class, String.class, Uri.class,
                    ContentValues.class, Bundle.class).invoke(provider, "com.android.shell", null,
                    URI, values, new Bundle());
            System.out.println("UPDATED=" + count);
            if (count != 1) throw new IllegalStateException("Expected exactly one updated policy");
          } else {
            throw new IllegalArgumentException("Unsupported action");
          }
        } finally {
            iam.getMethod("removeContentProviderExternalAsUser", String.class, IBinder.class,
                    int.class).invoke(service, URI.getAuthority(), token, 0);
        }
    }
}
