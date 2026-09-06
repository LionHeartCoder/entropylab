/**
 * Cloudflare Worker: serve Entropy Lab at https://www.bryankoury.com/entropylab/
 * by proxying to the Modal deployment (HTTP and WebSocket).
 *
 * Deploy:
 *   cd deploy && npx wrangler login && npx wrangler deploy
 * Then set ORIGIN in wrangler.toml to the URL `modal deploy` printed.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const prefix = env.PREFIX || "/entropylab";
    if (url.pathname === prefix) {
      return Response.redirect(url.origin + prefix + "/" + url.search, 301);
    }
    if (!url.pathname.startsWith(prefix + "/")) {
      return new Response("not found", { status: 404 });
    }
    const origin = new URL(env.ORIGIN);
    const target = new URL(url.pathname.slice(prefix.length) || "/", origin);
    target.search = url.search;

    const headers = new Headers(request.headers);
    headers.set("Host", origin.host);
    headers.set("X-Forwarded-Host", url.host);
    headers.set("X-Forwarded-Proto", "https");

    // WebSocket upgrade passes straight through; Workers support this via fetch.
    const init = { method: request.method, headers, redirect: "manual" };
    if (request.method !== "GET" && request.method !== "HEAD") init.body = request.body;
    const resp = await fetch(target.toString(), init);

    // Rewrite cookies so the owner cookie is scoped to the sub-path on this domain.
    const out = new Response(resp.body, resp);
    const sc = resp.headers.get("set-cookie");
    if (sc) out.headers.set("set-cookie", sc.replace(/;\s*Path=\/[^;]*/i, "; Path=" + prefix + "/"));
    return out;
  },
};
