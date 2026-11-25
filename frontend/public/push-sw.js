// Web Push handlers, loaded into the generated service worker via workbox `importScripts`.
// Plain JS on purpose: it is served as-is and must not depend on the app bundle.

self.addEventListener("push", (event) => {
  let title = "Orynthia Finance";
  let body = "";
  let url = "/";
  if (event.data) {
    const text = event.data.text();
    try {
      const data = JSON.parse(text);
      if (data && typeof data === "object") {
        if (typeof data.title === "string" && data.title) title = data.title;
        if (typeof data.body === "string") body = data.body;
        if (typeof data.url === "string") url = data.url;
      } else {
        body = text;
      }
    } catch {
      body = text;
    }
  }
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/pwa-192x192.png",
      badge: "/pwa-192x192.png",
      data: { url },
    }),
  );
});

// Only same-origin paths. Resolving the URL catches "//evil.example", "/\evil.example" and absolute URLs.
function safeUrl(value) {
  if (typeof value !== "string" || !value.startsWith("/")) return "/";
  const resolved = new URL(value, self.location.origin);
  return resolved.origin === self.location.origin ? resolved.pathname + resolved.search + resolved.hash : "/";
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = safeUrl(event.notification.data?.url);
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin) {
          await client.focus();
          // navigate() only works on windows this worker controls; open a new one otherwise.
          if ("navigate" in client && (await client.navigate(url).then(Boolean, () => false))) return;
          break;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
