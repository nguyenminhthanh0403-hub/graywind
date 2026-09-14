// Fires graywind's live-trading.yml on a schedule, bypassing GitHub Actions'
// own `schedule:` trigger entirely -- see wrangler.toml and
// ../.github/workflows/live-trading.yml's top-of-file comment for why.
// workflow_dispatch (a plain REST call) isn't subject to the same
// best-effort delay/drop behavior GitHub documents for `schedule:` events,
// so this Worker's own cron only needs to be reliable, not GitHub's.

async function triggerGraywindCycle(env) {
  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW_FILE}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "graywind-cron-trigger",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const bodyText = res.ok ? "" : await res.text();
  if (!res.ok) {
    console.error(`workflow_dispatch failed: ${res.status} ${bodyText}`);
  }
  return { ok: res.ok, status: res.status, bodyText };
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerGraywindCycle(env));
  },

  // Manual GET lets you confirm the trigger works right now instead of
  // waiting for the next cron tick: hit /?key=<TRIGGER_SECRET>. This used to
  // be an unauthenticated GET -- "treat the URL as effectively secret" --
  // but that's exactly what let something (never identified; no local cron/
  // launchd job on this machine was responsible) hit it every 15 minutes
  // on a Sunday, when the Worker's own weekday-only Cron Trigger correctly
  // stayed silent. Harmless (live_loop.py's market-hours gate no-ops any
  // out-of-window run) but wasteful, so this now requires TRIGGER_SECRET
  // (set via `wrangler secret put TRIGGER_SECRET`) and 404s -- same as an
  // unrecognized route -- on anything else, so a prober can't tell a wrong
  // key from no route at all.
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" || url.searchParams.get("key") !== env.TRIGGER_SECRET) {
      return new Response("not found", { status: 404 });
    }
    const result = await triggerGraywindCycle(env);
    return new Response(
      result.ok ? "dispatched" : `failed: ${result.status} ${result.bodyText}`,
      { status: result.ok ? 200 : 502 }
    );
  },
};
