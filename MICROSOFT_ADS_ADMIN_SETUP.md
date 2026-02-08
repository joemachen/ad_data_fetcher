# Microsoft Ads – Admin consent for "Ad Data Fetcher"

If users see **"Need admin approval"** when running `setup_ms_auth.py`, the Azure app has **Microsoft Graph → User.Read** granted but is missing the **Microsoft Advertising API** permission. The script requests the `msads.manage` scope to access Microsoft Advertising (Bing Ads) data.

## What the admin needs to do

### 1. Add the Microsoft Advertising API permission

**Important:** Do **not** use the **"Bing"** API (the one that shows `https://cn.bing.com`). That is a different API and does **not** have `msads.manage`. You need the **Microsoft Advertising** API (app ID below).

1. In **Azure Portal** → **App registrations** → open **Ad Data Fetcher**.
2. Go to **API permissions**.
3. Click **+ Add a permission**.
4. Choose **APIs my organization uses** (or **Microsoft APIs**).
5. In the search box, search for **"Microsoft Advertising"** (not "Bing").
   - If **"Microsoft Advertising"** does **not** appear in the list, the app may not be in your tenant yet. The admin must add it first:
     - Use **Microsoft Graph** (e.g. Graph Explorer, or PowerShell) and run:
       ```http
       POST https://graph.microsoft.com/v1.0/servicePrincipals
       Content-Type: application/json

       {"appId": "d42ffc93-c136-491d-b4fd-6f18168c68fd"}
       ```
     - Or in Azure: **Enterprise applications** → **+ New application** → **+ Create your own application** → **Integrate any other application you don't find in the gallery** → under "Application ID" enter **d42ffc93-c136-491d-b4fd-6f18168c68fd** and add it. Then go back to **App registrations → Ad Data Fetcher → API permissions** and try adding a permission again; "Microsoft Advertising" should now appear.
   - After adding the app to the tenant, when you **Add a permission** and search, select **Microsoft Advertising** (not "Bing").
6. Under **Microsoft Advertising**, choose **Delegated permissions**.
7. Check **msads.manage** (the only delegated permission for this API).
8. Click **Add permissions**.

### 2. Grant admin consent

1. On the **API permissions** page, click **Grant admin consent for [Your Org]** (e.g. **Grant admin consent for Mabels Labels**).
2. Confirm. The **Status** column for **Microsoft Advertising → msads.manage** should show a green check and "Granted for [Org]".

### 3. User can retry

After the above, the user runs `setup_ms_auth.py` again and completes the browser sign-in. They should no longer see "Need admin approval" (unless other permissions are required by your tenant).

## Reference

- [Register an application - Microsoft Advertising API](https://learn.microsoft.com/en-us/advertising/guides/authentication-oauth-register?view=bingads-13)
- Microsoft Advertising API app ID: `d42ffc93-c136-491d-b4fd-6f18168c68fd`
- Scope used by this app: `msads.manage`
