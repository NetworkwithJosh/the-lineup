// Visitor stats. Paste the Cloudflare Web Analytics token below to turn them on.
// Cloudflare's beacon sets no cookies and stores no personal data, so no cookie banner is needed.
(function () {
  var TOKEN = "";
  if (!TOKEN || location.hostname !== "thelineup.dev") return;
  var s = document.createElement("script");
  s.defer = true;
  s.src = "https://static.cloudflareinsights.com/beacon.min.js";
  s.setAttribute("data-cf-beacon", JSON.stringify({ token: TOKEN }));
  document.head.appendChild(s);
})();
