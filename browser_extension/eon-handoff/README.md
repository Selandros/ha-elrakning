# Mitt E.ON browser handoff

This Manifest V3 helper completes a single pending handoff created by the Elräkning E.ON provider.

1. Open `chrome://extensions` and enable Developer mode.
2. Choose **Load unpacked** and select this directory.
3. Open the extension options and enter the Home Assistant origin, for example `https://homeassistant.example`.
4. Grant permission for that exact origin.
5. In Elräkning, choose **Anslut Mitt E.ON**.
6. Complete the normal E.ON login in the opened tab.

The helper reads only the five allowlisted `MyEon*` cookies on `https://www.eon.se`, keeps them in memory for the request, and sends them only to the authenticated pending Home Assistant handoff endpoint. It does not store E.ON cookies, access passwords or browsing history, and it does not use DevTools, CAPTCHA bypass, CAT, DPoP, or browser-attestation emulation.
